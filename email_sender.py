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


def _get_sender(config: dict) -> str:
    """发件地址：优先环境变量，其次配置。"""
    return os.environ.get("GMAIL_USER", "").strip() or config.get("email", {}).get("sender", "").strip()


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


def _build_html_body(changes: list[dict], results: list[dict]) -> str:
    """构建 HTML 正文：摘要 + 变化明细表。"""
    checked_at = ""
    if results:
        checked_at = results[0].get("checked_at", "")
    try:
        if checked_at:
            dt = datetime.fromisoformat(checked_at)
            checked_at = dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

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


def send_monitor_email(config: dict, changes: list[dict], results: list[dict]) -> None:
    """发送监控邮件。凭证缺失或发送失败时记录日志，不抛出异常（不影响主流程）。"""
    if not changes or not results:
        return

    email_cfg = config.get("email", {})
    sender = _get_sender(config)
    recipient = email_cfg.get("recipient", "").strip()
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not sender or not recipient:
        logger.warning("邮件未发送：缺少 email.sender / email.recipient 配置")
        return
    if not user or not password:
        logger.warning("邮件未发送：缺少环境变量 GMAIL_USER / GMAIL_APP_PASSWORD")
        return

    try:
        dt = datetime.now(timezone(timedelta(hours=8)))  # 北京时间
        subject = SUBJECT_TMPL.format(n=len(changes), date=dt.strftime("%Y-%m-%d"))

        msg = MIMEMultipart("mixed")
        msg["From"] = formataddr((str(Header("QDII基金监控", "utf-8")), sender))
        msg["To"] = recipient
        msg["Subject"] = Header(subject, "utf-8")

        msg.attach(MIMEText(_build_html_body(changes, results), "html", "utf-8"))
        msg.attach(_build_csv_attachment(results))

        host = email_cfg.get("smtp_host", "smtp.gmail.com")
        port = int(email_cfg.get("smtp_port", 587))

        smtp = smtplib.SMTP(host, port, timeout=30)
        try:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.sendmail(sender, [r.strip() for r in recipient.split(",") if r.strip()], msg.as_string())
            logger.info(f"监控邮件已发送至 {recipient}（{len(changes)} 条变更）")
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
