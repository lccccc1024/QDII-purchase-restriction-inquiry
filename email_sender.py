"""邮件推送模块：通过 Gmail SMTP 发送监控结果。

正文为 HTML 格式，直接展示本次变化明细（状态/限额变化）；
附件为全量检测结果 CSV（所有被监控标的），UTF-8 BOM 编码，Excel 可直接打开。

凭证通过环境变量读取（GMAIL_USER / GMAIL_APP_PASSWORD），
不写入代码或配置文件。Gmail 需开启两步验证并使用应用专用密码。
"""

import csv
import html
import io
import logging
import os
import smtplib
from datetime import datetime, timezone, timedelta

from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)

INDEX_LABELS = {"nasdaq100": "纳斯达克100", "sp500": "标普500"}

STATUS_HTML_COLOR = {
    "开放申购": "#2E7D5B",
    "限制大额申购": "#C8913A",
    "暂停申购": "#C43A31",
    "已清盘/终止": "#8A8A8A",
    "未知": "#999999",
}
STATUS_SORT = {
    "暂停申购": 0, "限制大额申购": 1, "开放申购": 2,
    "已清盘/终止": 3, "未知": 4,
}

CSV_HEADERS = [
    "扫描时间", "基金代码", "基金简称", "跟踪指数",
    "申购状态", "申购限额(元)", "数据源",
]

SUBJECT_TMPL = "[基金监控] {n} 只基金申购状态变化 - {date}"
HEARTBEAT_SUBJECT_TMPL = "[基金监控] 周报：{n} 只基金无状态变化 - {date}"

# 发送结果：上层据此决定补发、告警与心跳节流。
# SENT=邮件服务器已接收；SKIPPED=本地缺凭证（不算错误）；FAILED=需要补发/告警。
SEND_SENT = "sent"
SEND_SKIPPED = "skipped"
SEND_FAILED = "failed"


def _now_bj() -> datetime:
    """当前北京时间。"""
    return datetime.now(timezone(timedelta(hours=8)))


def _get_sender(config: dict) -> str:
    """发件地址：优先环境变量，其次配置。"""
    env_sender = os.environ.get("GMAIL_USER", "").strip()
    cfg_sender = str(config.get("email", {}).get("sender") or "").strip()
    return env_sender or cfg_sender


def _resolve_credentials(config: dict):
    """校验发信凭证，返回 (creds, status)。

    缺少凭证时：GitHub Actions 环境按 FAILED 处理（必须告警，否则会永久静默），
    本地运行按 SKIPPED 处理（仅提示，不阻塞本地使用）。
    """
    email_cfg = config.get("email", {})
    sender = _get_sender(config)
    recipient = str(email_cfg.get("recipient") or "").strip()
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    missing = []
    if not sender:
        missing.append("email.sender")
    if not recipient:
        missing.append("email.recipient")
    if not user:
        missing.append("GMAIL_USER")
    if not password:
        missing.append("GMAIL_APP_PASSWORD")

    if missing:
        message = "邮件未发送：缺少 " + " / ".join(missing)
        if os.environ.get("GITHUB_ACTIONS"):
            logger.error(message + "（CI 环境按发送失败处理，请检查仓库 Secrets）")
            return None, SEND_FAILED
        logger.warning(message)
        return None, SEND_SKIPPED

    return {
        "sender": sender,
        "recipients": [r.strip() for r in recipient.split(",") if r.strip()],
        "user": user,
        "password": password,
    }, SEND_SENT


def _deliver(config: dict, msg, creds: dict) -> bool:
    """投递邮件；成功返回 True，失败记录日志并返回 False（由上层补发/告警）。"""
    try:
        email_cfg = config.get("email", {})
        host = email_cfg.get("smtp_host", "smtp.gmail.com")
        port = int(email_cfg.get("smtp_port", 587))
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(creds["user"], creds["password"])
            smtp.sendmail(creds["sender"], creds["recipients"], msg.as_string())
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


def _build_csv_attachment(results: list[dict]) -> MIMEBase:
    """生成全量检测结果 CSV 附件（所有标的，暂停/限大额排前）。"""
    sorted_results = sorted(
        results,
        key=lambda r: (
            STATUS_SORT.get(r.get("purchase_status", "未知"), 99),
            -(r.get("purchase_limit") or 0),
        ),
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    for r in sorted_results:
        writer.writerow([
            r.get("checked_at", ""),
            r.get("code", ""),
            r.get("name", ""),
            INDEX_LABELS.get(r.get("index", ""), r.get("index", "")),
            r.get("purchase_status", ""),
            f"{r.get('purchase_limit'):,.2f}" if r.get("purchase_limit") is not None else "",
            r.get("source", ""),
        ])

    part = MIMEBase("text", "csv", charset="utf-8")
    part.set_payload(buf.getvalue().encode("utf-8-sig"))
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition", "attachment",
        filename=("utf-8", "", "基金监控结果.csv"),
    )
    return part


def _fmt_limit(limit) -> str:
    """格式化限额用于 HTML 正文。"""
    if limit is None:
        return ""
    if limit >= 10000:
        return f"¥{limit / 10000:.2f}万"
    return f"¥{limit:,.2f}"


def _format_checked_at(results: list[dict]) -> str:
    """把本轮扫描时间格式化为人类可读文本。"""
    checked_at = results[0].get("checked_at", "") if results else ""
    if not checked_at:
        return ""
    try:
        return datetime.fromisoformat(checked_at).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return checked_at


def _format_minute(value: str) -> str:
    """把 ISO 时间格式化为"年-月-日 时:分"，用于"最近一次变化"。"""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _build_html_body(changes: list[dict], results: list[dict]) -> str:
    """构建 HTML 正文：摘要 + 变化明细表。"""
    checked_at = _format_checked_at(results)

    # 状态分布摘要
    counts: dict[str, int] = {}
    for r in results:
        s = r.get("purchase_status", "未知")
        counts[s] = counts.get(s, 0) + 1
    parts = " · ".join(
        f"{html.escape(k, quote=False)} {v}" for k, v in counts.items()
    ) or "无数据"

    rows = []
    for ch in changes:
        name = html.escape(str(ch.get("name", "?")), quote=False)
        code = html.escape(str(ch.get("code", "?")), quote=False)
        index = html.escape(INDEX_LABELS.get(ch.get("index", ""), ch.get("index", "")), quote=False)
        old_s_raw = str(ch.get("old_status", "?"))
        new_s_raw = str(ch.get("new_status", "?"))
        old_s = html.escape(old_s_raw, quote=False)
        new_s = html.escape(new_s_raw, quote=False)
        old_l = _fmt_limit(ch.get("old_limit"))
        new_l = _fmt_limit(ch.get("new_limit"))
        new_color = STATUS_HTML_COLOR.get(new_s_raw, "#333333")
        old_color = STATUS_HTML_COLOR.get(old_s_raw, "#333333")

        limit_cell = ""
        if old_l != new_l:
            limit_cell = (
                f'<span style="color:#666">({old_l} → <b>{new_l}</b>)</span>'
                if old_l and new_l
                else f'限额: <b>{new_l}</b>'
            )

        rows.append(
            f'<tr style="border-bottom:1px solid #eee">'
            f'<td style="padding:6px 10px">{name}<br>'
            f'<span style="color:#888;font-size:12px">{code} · {index}</span></td>'
            f'<td style="padding:6px 10px">'
            f'<span style="color:{old_color}">{old_s}</span> → '
            f'<b style="color:{new_color}">{new_s}</b></td>'
            f'<td style="padding:6px 10px;color:#444">{limit_cell}</td>'
            f'</tr>'
        )

    return f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222">
<div style="max-width:680px;margin:0 auto;padding:20px;background:#faf9f7;border-radius:8px">
  <div style="border-bottom:3px solid #D4513E;padding-bottom:10px;margin-bottom:16px">
    <h2 style="margin:0;color:#1C1C1C">QDII 基金申购状态监控</h2>
    <span style="color:#888;font-size:13px">扫描时间: {checked_at or "N/A"}</span>
  </div>

  <div style="background:#fff;border:1px solid #e5e0d8;border-radius:6px;padding:10px 16px;margin-bottom:16px">
    <b>本次扫描 {len(results)} 只基金</b> — 状态分布: {parts}
  </div>

  <h3 style="color:#B03A2C">⚠ 检测到 {len(changes)} 条变更</h3>
  <table style="border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5e0d8;border-radius:6px;font-size:14px">
    <tr style="background:#f0ece4;text-align:left">
      <th style="padding:8px 10px">基金</th>
      <th style="padding:8px 10px">状态变化</th>
      <th style="padding:8px 10px">限额变化</th>
    </tr>
    {''.join(rows)}
  </table>

  <p style="color:#999;font-size:12px;margin-top:18px">
    完整检测结果见附件 <b>基金监控结果.csv</b>（可按 Excel 打开）。<br>
    数据来源: 天天基金网 / 蛋卷基金
  </p>
</div></body></html>"""


def _build_heartbeat_body(results: list[dict], last_change_at: str = "",
                          last_change_count: int = 0) -> str:
    """构建心跳/周报正文：当前全量状态，用于证明监控仍在正常运行。"""
    checked_at = _format_checked_at(results)

    counts: dict[str, int] = {}
    for r in results:
        s = r.get("purchase_status", "未知")
        counts[s] = counts.get(s, 0) + 1
    parts = " · ".join(
        f"{html.escape(k, quote=False)} {v}" for k, v in counts.items()
    ) or "无数据"

    last_change = _format_minute(last_change_at)
    if last_change:
        change_line = f"最近一次变更：{last_change}（{last_change_count} 条）"
    else:
        change_line = "最近一次变更：暂无记录"

    rows = []
    for r in sorted(
        results,
        key=lambda x: (
            STATUS_SORT.get(x.get("purchase_status", "未知"), 99),
            x.get("name", ""),
        ),
    ):
        name = html.escape(str(r.get("name", "?")), quote=False)
        code = html.escape(str(r.get("code", "?")), quote=False)
        index = html.escape(INDEX_LABELS.get(r.get("index", ""), r.get("index", "")), quote=False)
        status_raw = str(r.get("purchase_status", "未知"))
        status = html.escape(status_raw, quote=False)
        color = STATUS_HTML_COLOR.get(status_raw, "#333333")
        limit = _fmt_limit(r.get("purchase_limit")) or "—"
        rows.append(
            f'<tr style="border-bottom:1px solid #eee">'
            f'<td style="padding:6px 10px">{name}<br>'
            f'<span style="color:#888;font-size:12px">{code} · {index}</span></td>'
            f'<td style="padding:6px 10px;color:{color}">{status}</td>'
            f'<td style="padding:6px 10px;color:#444">{limit}</td>'
            f'</tr>'
        )

    return f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222">
<div style="max-width:680px;margin:0 auto;padding:20px;background:#faf9f7;border-radius:8px">
  <div style="border-bottom:3px solid #D4513E;padding-bottom:10px;margin-bottom:16px">
    <h2 style="margin:0;color:#1C1C1C">QDII 基金申购状态周报</h2>
    <span style="color:#888;font-size:13px">扫描时间: {checked_at or "N/A"}</span>
  </div>

  <div style="background:#fff;border:1px solid #e5e0d8;border-radius:6px;padding:10px 16px;margin-bottom:16px">
    <b>本次扫描 {len(results)} 只基金</b> — 状态分布: {parts}<br>
    <span style="color:#777;font-size:13px">{change_line}</span>
  </div>

  <p style="color:#2E7D5B;margin:0 0 14px">
    ✓ 本期未检测到申购状态变化。本邮件为定期心跳，用于确认监控仍在正常运行。
  </p>

  <table style="border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5e0d8;border-radius:6px;font-size:14px">
    <tr style="background:#f0ece4;text-align:left">
      <th style="padding:8px 10px">基金</th>
      <th style="padding:8px 10px">申购状态</th>
      <th style="padding:8px 10px">限额</th>
    </tr>
    {''.join(rows)}
  </table>

  <p style="color:#999;font-size:12px;margin-top:18px">
    完整检测结果见附件 <b>基金监控结果.csv</b>（可按 Excel 打开）。<br>
    数据来源: 天天基金网 / 蛋卷基金
  </p>
</div></body></html>"""


def send_monitor_email(config: dict, changes: list[dict], results: list[dict],
                       retry: bool = False) -> str:
    """发送变更邮件，返回 SEND_SENT / SEND_SKIPPED / SEND_FAILED。

    retry=True 表示本次包含上次未送达的变更（补发），主题会加标注。
    不抛出异常：由调用方决定补发与告警。
    """
    if not changes or not results:
        return SEND_SKIPPED

    creds, status = _resolve_credentials(config)
    if creds is None:
        return status

    dt = _now_bj()
    subject = SUBJECT_TMPL.format(n=len(changes), date=dt.strftime("%Y-%m-%d"))
    if retry:
        subject += "（补发）"

    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((str(Header("QDII基金监控", "utf-8")), creds["sender"]))
    msg["To"] = ", ".join(creds["recipients"])
    msg["Subject"] = Header(subject, "utf-8")

    msg.attach(MIMEText(_build_html_body(changes, results), "html", "utf-8"))
    msg.attach(_build_csv_attachment(results))

    if not _deliver(config, msg, creds):
        return SEND_FAILED

    suffix = "，含补发" if retry else ""
    logger.info(
        f"监控邮件已发送至 {', '.join(creds['recipients'])}"
        f"（{len(changes)} 条变更{suffix}）"
    )
    return SEND_SENT


def send_heartbeat_email(config: dict, results: list[dict],
                         last_change_at: str = "", last_change_count: int = 0) -> str:
    """发送心跳/周报邮件（无变化时证明监控存活），返回发送结果状态。"""
    if not results:
        return SEND_SKIPPED

    creds, status = _resolve_credentials(config)
    if creds is None:
        return status

    dt = _now_bj()
    subject = HEARTBEAT_SUBJECT_TMPL.format(
        n=len(results), date=dt.strftime("%Y-%m-%d")
    )

    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((str(Header("QDII基金监控", "utf-8")), creds["sender"]))
    msg["To"] = ", ".join(creds["recipients"])
    msg["Subject"] = Header(subject, "utf-8")

    msg.attach(MIMEText(
        _build_heartbeat_body(results, last_change_at, last_change_count),
        "html", "utf-8",
    ))
    msg.attach(_build_csv_attachment(results))

    if not _deliver(config, msg, creds):
        return SEND_FAILED

    logger.info(f"心跳邮件已发送至 {', '.join(creds['recipients'])}（{len(results)} 只基金，无变化）")
    return SEND_SENT
