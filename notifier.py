"""通知模块：控制台输出、CSV 变更记录、Webhook 推送。"""

import csv
import json
import logging
import os
import sys

import requests

logger = logging.getLogger(__name__)

def _use_color() -> bool:
    """检测当前是否为交互终端（实时判断，适配输出重定向）。"""
    return sys.stdout.isatty()

INDEX_LABELS = {"nasdaq100": "纳斯达克100", "sp500": "标普500"}
STATUS_COLORS = {
    "开放申购": "\033[92m",   # 绿
    "暂停申购": "\033[91m",   # 红
    "限制大额申购": "\033[93m",  # 黄
    "已清盘/终止": "\033[90m",  # 灰
    "未知": "\033[94m",        # 蓝
}
RESET = "\033[0m"


def _color_status(status: str) -> str:
    """给状态加 ANSI 颜色（终端显示）。"""
    c = STATUS_COLORS.get(status, "")
    return f"{c}{status}{RESET}" if c else status


def _build_summary(results: list[dict]) -> list[str]:
    """构建扫描摘要（各指数状态分布）。"""
    lines = []
    for idx, label in [("nasdaq100", "纳指100"), ("sp500", "标普500")]:
        funds = [r for r in results if r.get("index") == idx]
        if not funds:
            continue
        statuses = {}
        for f in funds:
            s = f["purchase_status"]
            statuses[s] = statuses.get(s, 0) + 1
        parts = []
        for s in ["暂停申购", "限制大额申购", "开放申购", "未知"]:
            if s in statuses:
                parts.append(f"{s.replace('申购','').replace('限制大额','限大额')} {statuses[s]}")
        lines.append(f"  {label}: {len(funds)}只 ({' · '.join(parts)})")
    return lines


def _build_status_table(results: list[dict], with_color: bool = True) -> list[str]:
    """构建状态表格的每一行文本。"""
    lines = []
    sep = "=" * 85
    lines.append("")
    lines.append(sep)
    lines.append(f"{'代码':<8} {'简称':<24} {'指数':<10} {'申购状态':<10} {'限额/备注'}")
    lines.append("-" * 85)

    for r in results:
        code = r["code"]
        name = r["name"][:22]
        index_label = INDEX_LABELS.get(r.get("index", ""), r.get("index", ""))
        status = r["purchase_status"]
        display_status = _color_status(status) if with_color else status
        limit = r.get("purchase_limit")
        limit_str = f"¥{limit:,.0f}" if limit else ""
        unknown_mark = " ⚠" if status == "未知" and with_color else " ?" if status == "未知" else ""
        lines.append(
            f"{code:<8} {name:<24} {index_label:<10} "
            f"{display_status:<12}{unknown_mark} {limit_str}"
        )
    lines.append(sep)
    lines.append("")
    return lines


def _build_change_lines(changes: list[dict], with_color: bool = True) -> list[str]:
    """构建变更记录的每一行文本。"""
    lines = []
    if not changes:
        lines.append("未检测到申购状态变化。")
        lines.append("")
        return lines

    lines.append("")
    lines.append("!" * 85)
    lines.append(f"检测到 {len(changes)} 条状态变更：")
    lines.append("-" * 85)

    for ch in changes:
        code = ch.get("code", "?")
        name = ch.get("name", "?")
        index_label = INDEX_LABELS.get(ch.get("index", ""), ch.get("index", ""))
        old_status = ch.get("old_status", "?")
        new_status = ch.get("new_status", "?")
        old_limit = ch.get("old_limit")
        new_limit = ch.get("new_limit")
        time_str = ch.get("checked_at", "")

        lines.append(f"  [{time_str}]")
        lines.append(f"  基金: {code} {name} ({index_label})")
        if with_color:
            lines.append(f"  申购状态: {_color_status(old_status)} -> {_color_status(new_status)}")
        else:
            lines.append(f"  申购状态: {old_status} -> {new_status}")

        if old_limit != new_limit:
            old_l = f"¥{old_limit:,.0f}" if old_limit else "无限制"
            new_l = f"¥{new_limit:,.0f}" if new_limit else "无限制"
            lines.append(f"  申购限额: {old_l} -> {new_l}")
        lines.append("")
    lines.append("!" * 85)
    lines.append("")
    return lines


def generate_report(
    results: list[dict],
    changes: list[dict],
    path: str,
):
    """将扫描结果写入纯文本报告文件（不含 ANSI 颜色码）。"""
    lines = []
    if not results:
        lines.append("=" * 80)
        lines.append("  场外纳斯达克100 / 标普500 基金申购限额监控报告")
        lines.append("=" * 80)
        lines.append("")
        lines.append("扫描时间: N/A")
        lines.append("基金总数: 0")
        lines.append("")
        lines.append("无基金数据。")
        lines.append("")
        lines.append("=" * 80)
        lines.append("报告结束")
        lines.append("=" * 80)
        content = "\n".join(lines)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"报告已写入 {path}（空数据）")
        return

    lines.append("=" * 80)
    lines.append("  场外纳斯达克100 / 标普500 基金申购限额监控报告")
    lines.append("=" * 80)

    # 统计各状态数量
    status_counts = {}
    for r in results:
        s = r["purchase_status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    lines.append("")
    lines.append(f"扫描时间: {results[0]['checked_at']}")
    lines.append(f"基金总数: {len(results)}")
    lines.append("状态分布: " + " | ".join(f"{k}: {v}" for k, v in status_counts.items()))
    lines.append("")

    # 全部基金状态表格
    lines.append(f"[全部基金状态]")
    lines.extend(_build_status_table(results, with_color=False))

    # 变更详情
    lines.append(f"[变更检测]")
    lines.extend(_build_change_lines(changes, with_color=False))

    # 限额受限的基金汇总
    limited = [r for r in results if r["purchase_status"] == "限制大额申购"]
    suspended = [r for r in results if r["purchase_status"] == "暂停申购"]
    if limited or suspended:
        lines.append("[受限基金汇总]")
        lines.append("")
        if suspended:
            lines.append(f"暂停申购 ({len(suspended)} 只):")
            for r in suspended:
                lines.append(f"  {r['code']} {r['name']}")
            lines.append("")
        if limited:
            lines.append(f"限制大额申购 ({len(limited)} 只):")
            for r in limited:
                limit_str = f" ¥{r['purchase_limit']:,.0f}" if r.get("purchase_limit") else ""
                lines.append(f"  {r['code']} {r['name']}{limit_str}")
            lines.append("")

    lines.append("=" * 80)
    lines.append("报告结束")
    lines.append("=" * 80)

    content = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"报告已写入 {path}")


def print_all_status(results: list[dict]):
    """以表格形式输出所有基金的当前申购状态。"""
    if not results:
        logger.info("没有基金数据。")
        return

    use_color = _use_color()

    # 扫描摘要
    print(f"\n{'─'*50}")
    print(f"  扫描完成 — {results[0]['checked_at'][:16].replace('T',' ') if results else ''}")
    for line in _build_summary(results):
        print(line)
    print(f"{'─'*50}")

    for line in _build_status_table(results, with_color=use_color):
        print(line)


def print_changes(changes: list[dict]):
    """格式化输出变更记录。"""
    if not changes:
        print("无申购状态变化。\n")
        return
    use_color = _use_color()
    for line in _build_change_lines(changes, with_color=use_color):
        print(line)


def append_changelog_csv(changes: list[dict], path: str):
    """将变更追加到 CSV 文件。"""
    if not changes:
        return
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "时间", "基金代码", "基金简称", "跟踪指数",
                "旧状态", "新状态", "旧限额", "新限额",
            ])
        for ch in changes:
            writer.writerow([
                ch.get("checked_at", ""),
                ch["code"],
                ch["name"],
                INDEX_LABELS.get(ch.get("index", ""), ch.get("index", "")),
                ch.get("old_status", ""),
                ch.get("new_status", ""),
                ch.get("old_limit", ""),
                ch.get("new_limit", ""),
            ])
    logger.info(f"变更记录已写入 {path}")


# ═══════════════════════════════════════════════════════
#  Webhook 推送
# ═══════════════════════════════════════════════════════

def _escape_markdown(text: str) -> str:
    """转义 Markdown 特殊字符，防止基金名中的 *, _, [, ` 等破坏格式。"""
    for ch in ("\\", "`", "*", "_", "[", "]"):
        text = text.replace(ch, "\\" + ch)
    return text


def _build_markdown_message(changes: list[dict]) -> str:
    """构建变更的 Markdown 摘要。"""
    lines = [f"### 📊 基金申购状态变更 ({len(changes)} 条)\n"]
    for ch in changes:
        name = _escape_markdown(ch["name"])
        code = ch["code"]
        index_label = INDEX_LABELS.get(ch.get("index", ""), ch.get("index", ""))
        old_s = ch.get("old_status", "?")
        new_s = ch["new_status"]
        lines.append(
            f"- **{name}** ({code}) [{index_label}]\n"
            f"  {old_s} → **{new_s}**"
        )
        if ch.get("new_limit"):
            lines.append(f"  限额: ¥{ch['new_limit']:,.0f}")
        lines.append("")
    return "\n".join(lines)


def send_webhook(changes: list[dict], config: dict):
    """通过 Webhook 发送变更通知。"""
    if not changes:
        return

    notify = config.get("notify", {})
    url = notify.get("webhook_url", "")
    if not url:
        return

    wtype = notify.get("webhook_type", "dingtalk")
    markdown = _build_markdown_message(changes)

    try:
        if wtype == "dingtalk":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": "基金申购状态变更", "text": markdown},
            }
        elif wtype == "feishu":
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": "基金申购状态变更"},
                        "template": "blue",
                    },
                    "elements": [{"tag": "markdown", "content": markdown}],
                },
            }
        elif wtype == "serverchan":
            # Server酱: 简单 POST title + desp
            payload = {
                "title": "基金申购状态变更",
                "desp": markdown,
            }
        else:
            payload = {"text": markdown}

        resp = requests.post(
            url, json=payload, headers={"Content-Type": "application/json"}, timeout=10
        )
        if resp.status_code < 400:
            logger.info(f"Webhook ({wtype}) 发送成功")
        else:
            logger.warning(f"Webhook ({wtype}) 发送失败: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Webhook 发送异常: {e}")
