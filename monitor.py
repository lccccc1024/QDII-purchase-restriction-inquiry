#!/usr/bin/env python3
"""场外纳指100 / 标普500基金申购限额监控 — 主程序。

用法:
  python monitor.py --init              # 仅重建基金列表
  python monitor.py --once              # 单次检查所有基金申购状态
  python monitor.py --once --init       # 重建列表 + 单次检查
  python monitor.py --daemon --interval 1800  # 常驻监控，每1800秒扫描一次
"""

import argparse
import logging
import os
import sys
import time

# 在 Windows 上强制使用 UTF-8 输出，避免 emoji 等字符编码错误
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import chart as chart_maker
import fetcher
import notifier
from utils import (
    load_config,
    load_json,
    save_json,
    setup_logging,
    now_iso,
)

logger = logging.getLogger(__name__)


def _load_fund_list(config: dict) -> list[dict]:
    """加载基金列表，优先读取本地 JSON 文件。"""
    path = config["data"].get("fund_list_path", "fund_list.json")
    if os.path.exists(path):
        data = load_json(path)
        if data:
            logger.info(f"从 {path} 加载了 {len(data)} 只基金")
            return data
    return []


def init_fund_list(config: dict, session, interactive: bool = True) -> list[dict]:
    """自动发现并保存目标基金列表。"""
    print("\n🔍 正在从天天基金网发现场外纳斯达克100 / 标普500 基金...\n")
    funds = fetcher.discover_target_funds(session, config)

    if not funds:
        logger.warning("未发现任何匹配基金，请检查网络或关键词配置。")
        return []

    # 按指数类型分组展示
    nasdaq = [f for f in funds if f["index"] == "nasdaq100"]
    sp500 = [f for f in funds if f["index"] == "sp500"]

    print(f"\n发现 纳斯达克100 相关场外基金 {len(nasdaq)} 只:")
    for f in nasdaq:
        print(f"  {f['code']}  {f['name']:<30s}  类型: {f['type']}")

    print(f"\n发现 标普500 相关场外基金 {len(sp500)} 只:")
    for f in sp500:
        print(f"  {f['code']}  {f['name']:<30s}  类型: {f['type']}")

    if interactive and sys.stdin.isatty():
        print("\n" + "-" * 60)
        try:
            choice = input("是否保存此列表？[Y/n]: ").strip().lower()
            if choice and choice != "y" and choice != "yes":
                print("已取消，不保存。")
                return []
        except EOFError:
            pass  # 非交互式环境，自动保存

    path = config["data"].get("fund_list_path", "fund_list.json")
    save_json(path, funds)
    print(f"\n✅ 已保存 {len(funds)} 只基金到 {path}")
    return funds


def compare_status(
    old_records: list[dict], new_records: list[dict]
) -> list[dict]:
    """对比新旧状态，返回变更列表。"""
    old_map = {r["code"]: r for r in old_records}
    changes = []
    for new_r in new_records:
        code = new_r["code"]
        # 状态为"未知"说明本次请求失败，不触发变更通知
        if new_r["purchase_status"] == "未知":
            continue
        old_r = old_map.get(code)
        if old_r is None:
            # 新增基金（基金列表中手动添加的）
            changes.append({
                **new_r,
                "new_status": new_r.get("purchase_status", "?"),
                "new_limit": new_r.get("purchase_limit"),
                "old_status": "(新增)",
                "old_limit": None,
            })
            continue
        status_changed = new_r["purchase_status"] != old_r.get("purchase_status")
        limit_changed = new_r.get("purchase_limit") != old_r.get("purchase_limit")
        if status_changed or limit_changed:
            changes.append({
                **new_r,
                "new_status": new_r.get("purchase_status", "?"),
                "new_limit": new_r.get("purchase_limit"),
                "old_status": old_r.get("purchase_status", "?"),
                "old_limit": old_r.get("purchase_limit"),
            })
    return changes


def run_once(config: dict, session, do_init: bool = False, do_chart: bool = False, interactive: bool = True):
    """执行一次完整扫描。"""
    if do_init or not _load_fund_list(config):
        init_fund_list(config, session, interactive=interactive)

    fund_list = _load_fund_list(config)
    if not fund_list:
        logger.error("基金列表为空，请先运行 --init。")
        return

    # 扫描
    print(f"\n📡 开始扫描 {len(fund_list)} 只基金...\n")
    results = fetcher.scan_all_funds(session, fund_list, config)

    # 打印全表
    notifier.print_all_status(results)

    # 变更检测
    status_path = config["data"].get("status_log_path", "status_log.json")
    previous = load_json(status_path, default=[])
    changes = compare_status(previous, results)

    if changes:
        notifier.print_changes(changes)
        changelog_path = config["data"].get("changelog_path", "changelog.csv")
        notifier.append_changelog_csv(changes, changelog_path)
        notifier.send_webhook(changes, config)
    else:
        print("✅ 未检测到申购状态变化。\n")

    # 生成报告
    report_path = config["data"].get("report_path", "report.txt")
    notifier.generate_report(results, changes, report_path)

    # 保存本次快照（排除"未知"状态，避免污染下一轮对比）
    valid_results = [r for r in results if r["purchase_status"] != "未知"]
    unknown_count = len(results) - len(valid_results)
    if unknown_count > 0:
        logger.warning(f"{unknown_count} 只基金状态未知，已从快照中排除以保护上一轮数据。")
    save_json(status_path, valid_results)
    logger.info(f"状态快照已保存到 {status_path} ({len(valid_results)}/{len(results)} 只)")

    # 图表（需要在 status_log 保存之后）
    if do_chart:
        chart_path = config["data"].get("chart_path", "chart.png")
        chart_maker.generate(output_path=chart_path)


def run_daemon(config: dict, session, interval: int, do_chart: bool = False):
    """常驻监控模式。"""
    logger.info(f"🔄 常驻监控启动，间隔 {interval} 秒")
    while True:
        try:
            run_once(config, session, do_init=False, do_chart=do_chart, interactive=False)
        except KeyboardInterrupt:
            logger.info("收到中断信号，退出监控。")
            break
        except Exception as e:
            logger.error(f"扫描异常: {e}", exc_info=True)

        logger.info(f"等待 {interval} 秒后下一次扫描...")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="场外纳指100 / 标普500基金申购限额监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python monitor.py --init              # 仅发现并保存基金列表
  python monitor.py --once              # 单次扫描
  python monitor.py --once --init       # 重建列表 + 单次扫描
  python monitor.py --daemon --interval 1800  # 常驻监控（每30分钟）
        """,
    )
    parser.add_argument(
        "--once", action="store_true", help="单次检查模式"
    )
    parser.add_argument(
        "--daemon", action="store_true", help="常驻监控模式"
    )
    parser.add_argument(
        "--interval", type=int, default=None,
        help="常驻模式扫描间隔（秒），默认从 config.yaml 读取"
    )
    parser.add_argument(
        "--init", action="store_true", help="重新发现并保存基金列表"
    )
    parser.add_argument(
        "--chart", action="store_true", help="扫描后生成图表"
    )
    parser.add_argument(
        "--chart-only", action="store_true",
        help="仅用上次 status_log.json 生成图表（不扫描）"
    )
    parser.add_argument(
        "--config", default="config.yaml", help="配置文件路径"
    )

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    setup_logging(log_file=config["data"].get("log_file", "monitor.log"))

    chart_path = config["data"].get("chart_path", "chart.png")

    # --chart-only: 仅生成图表，不扫描
    if getattr(args, "chart_only", False):
        print("\n📊 正在从最近扫描数据生成图表...")
        chart_maker.generate(output_path=chart_path)
        print(f"✅ 图表已保存至 {chart_path}\n")
        return

    if not args.once and not args.daemon and not args.init and not args.chart:
        # 默认：单次扫描
        args.once = True
        if not os.path.exists("fund_list.json"):
            args.init = True

    # 创建 HTTP 会话
    session = fetcher.create_session(config)

    do_chart = getattr(args, "chart", False)

    if args.daemon:
        interval = args.interval or config.get("scan", {}).get("interval", 1800)
        if args.init:
            init_fund_list(config, session, interactive=False)
        run_daemon(config, session, interval, do_chart=do_chart)
    elif args.once:
        run_once(config, session, do_init=args.init, do_chart=do_chart)
    elif args.init:
        init_fund_list(config, session, interactive=True)


if __name__ == "__main__":
    main()
