"""金融市场仪表盘 — 场外纳指100 / 标普500 QDII 申购限额图表。

杂志编辑风格：暖白纸张底色、Georgia 衬线标题、珊瑚色点缀、
精致排版，输出为高分辨率 PNG。
"""

import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch

from utils import load_json

logger = logging.getLogger(__name__)

# ── 杂志风调色板 ─────────────────────────────────
BG_COLOR = "#F6F3EF"          # 暖白纸张
CARD_COLOR = "#FFFFFF"         # 白色卡片
RULE_COLOR = "#D8D2C8"        # 细分隔线
TEXT_PRIMARY = "#1C1C1C"      # 深炭色正文
TEXT_SECONDARY = "#6B6258"    # 暖灰二级
TEXT_MUTED = "#9A9388"        # 浅灰辅助
ACCENT = "#D4513E"             # 珊瑚色签名色
ACCENT_DARK = "#B03A2C"        # 深珊瑚

STATUS_COLORS = {
    "开放申购": "#2E7D5B",
    "限制大额申购": "#C8913A",
    "暂停申购": "#C43A31",
    "已清盘/终止": "#8A8A8A",
    "未知": "#BEBEBE",
}
STATUS_SORT = {
    "暂停申购": 0, "限制大额申购": 1, "开放申购": 2,
    "已清盘/终止": 3, "未知": 4,
}

INDEX_LABELS = {"nasdaq100": "NASDAQ 100", "sp500": "S&P 500"}
INDEX_CN = {"nasdaq100": "纳斯达克100", "sp500": "标普500"}


# ── 字体检测 ─────────────────────────────────────

def _get_serif_font() -> FontProperties | None:
    """返回最佳衬线字体（用于英文标题）。"""
    available = {f.name for f in fm.fontManager.ttflist}
    for name in ["Georgia", "Palatino Linotype", "Times New Roman"]:
        if name in available:
            return FontProperties(family=name, weight="bold")
    return None


def _setup_cjk():
    """配置 matplotlib 使其能正确显示中文。"""
    available = {f.name for f in fm.fontManager.ttflist}
    for name in ["Microsoft YaHei", "SimHei", "PingFang SC",
                  "STHeiti", "Noto Sans SC"]:
        if name in available:
            plt.rcParams["font.family"] = "sans-serif"
            fallbacks = (
                plt.rcParams.get("font.sans-serif", [])
                or ["DejaVu Sans"]
            )
            plt.rcParams["font.sans-serif"] = [name] + fallbacks
            break
    plt.rcParams["axes.unicode_minus"] = False


# ── 辅助函数 ─────────────────────────────────────

def _shorten_name(name: str, max_len: int = 16) -> str:
    for cut in ["发起式联接", "ETF发起式联接", "ETF联接", "发起联接",
                "指数发起式", "指数发起", "联接"]:
        name = name.replace(cut, "")
    if len(name) > max_len:
        name = name[: max_len - 1] + "…"
    return name


def _format_limit(status: str, limit: float | None) -> str:
    if limit is None:
        if status == "暂停申购":
            return "暂停"
        if status == "开放申购":
            return "开放"
        return status
    if limit >= 10000:
        return f"¥{limit / 10000:.0f}万"
    if limit >= 1000:
        return f"¥{limit / 10000:.1f}万"
    return f"¥{limit:.0f}"


def _build_counts(funds: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for f in funds:
        s = f["purchase_status"]
        counts[s] = counts.get(s, 0) + 1
    return counts


# ── 绘制函数 ─────────────────────────────────────

def _draw_title(ax, timestamp: str, serif_fp):
    """杂志风格题头：大标题 + 细规则 + 日期。"""
    title_kw = {"fontsize": 26, "color": TEXT_PRIMARY, "va": "top"}
    if serif_fp:
        title_kw["fontproperties"] = serif_fp
    ax.text(0.04, 0.975, "Market Pulse", **title_kw)

    ax.text(0.04, 0.948,
            "场外纳斯达克100 / 标普500 QDII 基金申购限额监控",
            fontsize=9.5, color=TEXT_SECONDARY, va="top")

    if timestamp:
        ax.text(0.96, 0.975, timestamp,
                fontsize=8.5, color=TEXT_MUTED, va="top", ha="right")
    ax.text(0.96, 0.948, "数据来源: 天天基金网",
            fontsize=7.5, color=TEXT_MUTED, va="top", ha="right")

    # 细分隔线
    ax.plot([0.04, 0.96], [0.930, 0.930],
            color=RULE_COLOR, linewidth=0.6)


def _draw_kpi_card(ax, x, y, w, h, label_cn, label_en, funds, serif_fp):
    """杂志风格 KPI 卡片：大字总数 + 状态分布条。"""
    # 卡片背景
    card = FancyBboxPatch(
        (x, y - h), w, h,
        boxstyle="round,pad=0.01", facecolor=CARD_COLOR, edgecolor=RULE_COLOR,
        linewidth=0.5, zorder=0,
    )
    ax.add_patch(card)

    # 标题
    ax.text(x + 0.015, y - 0.013, label_cn,
            fontsize=11, fontweight="bold", color=TEXT_PRIMARY, va="top")
    ax.text(x + 0.015, y - 0.013 - 0.014, label_en,
            fontsize=6.5, color=TEXT_MUTED, va="top")

    total = len(funds)

    # 英雄数字：基金总数
    num_kw = {"fontsize": 32, "fontweight": "bold",
              "color": ACCENT, "va": "baseline"}
    if serif_fp:
        num_kw["fontproperties"] = serif_fp
    ax.text(x + 0.015, y - 0.055, str(total), **num_kw)
    ax.text(x + 0.015 + 0.045, y - 0.055,
            "只基金", fontsize=9, color=TEXT_SECONDARY, va="baseline")

    # 状态分布水平条
    counts = _build_counts(funds)
    bar_y = y - 0.083
    bar_h = 0.014
    pad_x = 0.015
    bar_w = w - pad_x * 2

    segments = []
    for s in ["暂停申购", "限制大额申购", "开放申购"]:
        if s in counts:
            segments.append((s, counts[s]))
    for s in ["已清盘/终止", "未知"]:
        if s in counts:
            segments.append((s, counts[s]))

    cum_x = x + pad_x
    for s_name, s_count in segments:
        seg_w = (s_count / total) * bar_w if total > 0 else 0
        if seg_w < 0.001:
            continue
        rect = plt.Rectangle(
            (cum_x, bar_y), seg_w, bar_h,
            facecolor=STATUS_COLORS.get(s_name, TEXT_MUTED),
            edgecolor="none", zorder=1, linewidth=0,
        )
        ax.add_patch(rect)
        if seg_w > 0.06 and s_count > 0:
            ax.text(cum_x + seg_w / 2, bar_y + bar_h / 2, str(s_count),
                    fontsize=6.5, color="white", va="center", ha="center",
                    fontweight="bold", zorder=2)
        cum_x += seg_w

    # 状态分布文字
    parts = []
    for s in ["暂停申购", "限制大额申购", "开放申购"]:
        if s in counts:
            short = s.replace("申购", "").replace("限制大额", "限大额")
            parts.append(f"{short} {counts[s]}")
    if parts:
        ax.text(x + pad_x, y - 0.100, "  ·  ".join(parts),
                fontsize=6.5, color=TEXT_SECONDARY, va="top")

    # 未知数量提示
    unknown = counts.get("未知", 0)
    if unknown:
        ax.text(x + w - 0.015, y - 0.100, f"? {unknown}",
                fontsize=6.5, color=TEXT_MUTED, va="top", ha="right")


def _draw_fund_rows(ax, x, y, w, funds, idx_type, num_cols=1):
    """杂志表格风格基金列表。"""
    col_gap = 0.018
    col_w = (w - 0.03 - col_gap * (num_cols - 1)) / num_cols
    n_per_col = (len(funds) + num_cols - 1) // num_cols if funds else 0
    row_h = 0.030
    total_h = max(n_per_col, 1) * row_h + 0.055

    # 卡片背景
    card = FancyBboxPatch(
        (x, y - total_h), w, total_h,
        boxstyle="round,pad=0.01", facecolor=CARD_COLOR, edgecolor=RULE_COLOR,
        linewidth=0.5, zorder=0,
    )
    ax.add_patch(card)

    # 分区标题
    counts = _build_counts(funds)
    ax.text(x + 0.015, y - 0.007, INDEX_CN.get(idx_type, idx_type),
            fontsize=12, fontweight="bold", color=TEXT_PRIMARY, va="top")
    ax.text(x + 0.015, y - 0.007,
            f"  {INDEX_LABELS.get(idx_type, idx_type)}",
            fontsize=7, color=TEXT_MUTED, va="top")

    parts = []
    for s in ["暂停申购", "限制大额申购", "开放申购"]:
        if s in counts:
            short = s.replace("申购", "").replace("限制大额", "限大额")
            parts.append(f"{short} {counts[s]}")
    summary = "  ·  ".join(parts)
    ax.text(x + w - 0.015, y - 0.007, f"共 {len(funds)} 只  |  {summary}",
            fontsize=7, color=TEXT_SECONDARY, va="top", ha="right")

    # 分隔线 + 列标题
    sep_y = y - 0.035
    ax.plot([x + 0.015, x + w - 0.015], [sep_y, sep_y],
            color=RULE_COLOR, linewidth=0.4)

    for col_idx in range(num_cols):
        cx = x + 0.015 + col_idx * (col_w + col_gap)
        col_funds = funds[col_idx * n_per_col: (col_idx + 1) * n_per_col]

        # 列表头
        hdr_y = sep_y - 0.004
        ax.text(cx + 0.005, hdr_y, "基金简称",
                fontsize=5.5, color=TEXT_MUTED, va="top")
        ax.text(cx + col_w * 0.55, hdr_y, "代码",
                fontsize=5.5, color=TEXT_MUTED, va="top")
        ax.text(cx + col_w - 0.005, hdr_y, "状态",
                fontsize=5.5, color=TEXT_MUTED, va="top", ha="right")

        for i, fund in enumerate(col_funds):
            ry = sep_y - 0.024 - i * row_h
            status = fund["purchase_status"]
            dot_color = STATUS_COLORS.get(status, TEXT_MUTED)

            # 交替行底色（极淡）
            if i % 2 == 0:
                bg = plt.Rectangle(
                    (cx, ry - row_h * 0.5), col_w, row_h * 0.85,
                    facecolor="#F0ECE4", edgecolor="none",
                    zorder=-1, alpha=0.4,
                )
                ax.add_patch(bg)

            # 状态圆点
            ax.scatter(cx + 0.005, ry, s=12, c=dot_color, zorder=2,
                       clip_on=False, linewidths=0, marker="o")

            # 基金简称
            name = _shorten_name(fund["name"])
            ax.text(cx + 0.018, ry, name,
                    fontsize=6.2, color=TEXT_PRIMARY, va="center")

            # 基金代码（小号、灰色）
            ax.text(cx + col_w * 0.55, ry, fund["code"],
                    fontsize=5.5, color=TEXT_MUTED, va="center")

            # 状态 + 限额
            txt = _format_limit(status, fund.get("purchase_limit"))
            ax.text(cx + col_w - 0.005, ry, txt,
                    fontsize=6.2, fontweight="bold", color=dot_color,
                    va="center", ha="right")


# ── 主入口 ────────────────────────────────────────

def generate(data_path: str = "status_log.json",
             output_path: str = "chart.png"):
    """生成杂志风格仪表盘 PNG。"""
    data = load_json(data_path)

    serif_fp = _get_serif_font()
    _setup_cjk()

    if not data:
        logger.warning("status_log.json 为空，生成空状态图。")
        fig, ax = plt.subplots(figsize=(12, 6))
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.text(0.5, 0.55, "暂无数据", fontsize=22,
                color=TEXT_MUTED, va="center", ha="center")
        ax.text(0.5, 0.48, "请先执行一次扫描（python monitor.py --once）",
                fontsize=11, color=TEXT_MUTED, va="center", ha="center")
        fig.savefig(output_path, dpi=200, bbox_inches="tight",
                    facecolor=BG_COLOR, pad_inches=0.3)
        plt.close(fig)
        return

    nasdaq = [r for r in data if r.get("index") == "nasdaq100"]
    sp500 = [r for r in data if r.get("index") == "sp500"]

    for lst in (nasdaq, sp500):
        lst.sort(key=lambda x: (
            STATUS_SORT.get(x["purchase_status"], 99),
            -(x.get("purchase_limit") or 0),
        ))

    timestamp = ""
    if data:
        raw = data[0].get("checked_at", "")
        if raw:
            timestamp = raw[:16].replace("T", " ")

    # ── 布局计算 ──
    n_nasdaq = len(nasdaq)
    n_sp500 = len(sp500)
    nasdaq_cols = 1 if n_nasdaq <= 12 else 2
    nasdaq_per_col = (
        max((n_nasdaq + nasdaq_cols - 1) // nasdaq_cols, 1) if n_nasdaq else 1
    )
    sp500_per_col = max(n_sp500, 1) if n_sp500 else 1

    row_h = 0.030
    nasdaq_h = max(nasdaq_per_col, 1) * row_h + 0.055
    sp500_h = max(sp500_per_col, 1) * row_h + 0.055
    list_h = max(nasdaq_h, sp500_h) + 0.02  # 底部留白

    fig_h = 3.8 + list_h * 14
    fig_w = 20

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # ── 顶部签名色细线 ──
    ax.plot([0.04, 0.96], [0.995, 0.995], color=ACCENT, linewidth=2, clip_on=False)

    # ── 题头 ──
    _draw_title(ax, timestamp, serif_fp)

    # ── KPI 摘要卡片 ──
    kpi_y = 0.905
    kpi_h = 0.108

    if nasdaq:
        _draw_kpi_card(ax, 0.04, kpi_y, 0.60, kpi_h,
                        "纳斯达克100", "NASDAQ 100", nasdaq, serif_fp)
    if sp500:
        _draw_kpi_card(ax, 0.665, kpi_y, 0.31, kpi_h,
                        "标普500", "S&P 500", sp500, serif_fp)

    # ── 基金列表 ──
    list_top = kpi_y - kpi_h - 0.025

    _draw_fund_rows(ax, 0.04, list_top, 0.60, nasdaq, "nasdaq100",
                     num_cols=nasdaq_cols)
    _draw_fund_rows(ax, 0.665, list_top, 0.31, sp500, "sp500",
                     num_cols=1)

    # ── 底部图例 ──
    legend_y = 0.020
    pairs = [
        ("暂停申购", STATUS_COLORS["暂停申购"]),
        ("限制大额申购", STATUS_COLORS["限制大额申购"]),
        ("开放申购", STATUS_COLORS["开放申购"]),
        ("未知", STATUS_COLORS["未知"]),
    ]
    lx = 0.04
    for label, color in pairs:
        ax.scatter(lx, legend_y + 0.005, s=18, c=color, zorder=2,
                   clip_on=False, linewidths=0, marker="o")
        ax.text(lx + 0.016, legend_y + 0.005, label,
                fontsize=7.5, color=TEXT_SECONDARY, va="center")
        lx += 0.12

    # 脚注
    note_x = 0.04
    notes = [
        "● 限额为单日累计购买上限",
        "● 已暂停申购的基金仍保留上次限额供参考",
        "● 排序: 暂停 → 限大额(按限额降序) → 开放",
    ]
    for note in notes:
        ax.text(note_x, legend_y - 0.028, note,
                fontsize=6, color=TEXT_MUTED, va="top")
        note_x += 0.30

    fig.savefig(output_path, dpi=200, bbox_inches="tight",
                facecolor=BG_COLOR, pad_inches=0.3)
    plt.close(fig)
    logger.info(f"图表已保存至 {output_path} ({fig_w}×{fig_h:.0f} @200dpi)")
