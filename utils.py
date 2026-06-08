"""工具函数：状态枚举、日志、JSON 读写、配置加载。"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


# ---- 申购状态枚举 ----
class PurchaseStatus(Enum):
    OPEN = "开放申购"
    SUSPENDED = "暂停申购"
    LIMITED = "限制大额申购"
    TERMINATED = "已清盘/终止"
    UNKNOWN = "未知"

    def __str__(self):
        return self.value


# 中文关键词 → 枚举映射
STATUS_KEYWORDS = {
    PurchaseStatus.OPEN: [
        "开放申购", "正常申购", "可申购", "开放",
    ],
    PurchaseStatus.SUSPENDED: [
        "暂停申购", "暂停", "停止申购", "关闭申购",
    ],
    PurchaseStatus.LIMITED: [
        "限制大额申购", "大额申购限制", "暂停大额申购", "限制申购",
        "限大额", "单日限额", "累计限额",
    ],
    PurchaseStatus.TERMINATED: [
        "清盘", "终止", "退市", "到期",
    ],
}


def normalize_status(raw: str) -> PurchaseStatus:
    """将抓取到的原始申购状态文本映射为标准化枚举值。"""
    if not raw:
        return PurchaseStatus.UNKNOWN
    raw_lower = raw.strip().lower()
    # 先检查限制大额申购 — 某些页面把"限制大额申购"也称作"暂停"而容易误分类
    for kw in STATUS_KEYWORDS[PurchaseStatus.LIMITED]:
        if kw in raw:
            return PurchaseStatus.LIMITED
    for kw in STATUS_KEYWORDS[PurchaseStatus.SUSPENDED]:
        if kw in raw:
            return PurchaseStatus.SUSPENDED
    for kw in STATUS_KEYWORDS[PurchaseStatus.TERMINATED]:
        if kw in raw:
            return PurchaseStatus.TERMINATED
    for kw in STATUS_KEYWORDS[PurchaseStatus.OPEN]:
        if kw in raw:
            return PurchaseStatus.OPEN
    # 对某些缩写做模糊匹配
    if "开放" in raw and "不" not in raw and "暂停" not in raw:
        return PurchaseStatus.OPEN
    if "暂停" in raw:
        return PurchaseStatus.SUSPENDED
    return PurchaseStatus.UNKNOWN


def parse_limit_amount(raw: str) -> Optional[float]:
    """从字符串中提取申购限额金额（元）。支持"1000元""1,000.00""100万"等。"""
    if not raw:
        return None
    raw = raw.strip().replace(",", "").replace("，", "")
    # 处理"XX万"格式
    wan_match = re.search(r"([\d.]+)\s*万", raw)
    if wan_match:
        return float(wan_match.group(1)) * 10000
    # 处理"XX亿"格式
    yi_match = re.search(r"([\d.]+)\s*亿", raw)
    if yi_match:
        return float(yi_match.group(1)) * 100000000
    # 普通数字
    num_match = re.search(r"([\d.]+)", raw)
    if num_match:
        return float(num_match.group(1))
    return None


# ---- 日志 ----
def setup_logging(log_file: Optional[str] = None, level: int = logging.INFO):
    """配置同时输出到控制台和文件的日志。"""
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


# ---- JSON 读写 ----
def load_json(path: str, default=None):
    """读取 JSON 文件，不存在时返回 default。"""
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    """将数据写入 JSON 文件，自动创建父目录。"""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 配置 ----
def load_config(path: str = "config.yaml") -> dict:
    """加载 YAML 配置文件。"""
    if not os.path.exists(path):
        # 返回默认值
        return {
            "scan": {
                "interval": 1800,
                "delay_between_requests": 1.5,
                "timeout": 15,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            "data": {
                "fund_list_path": "fund_list.json",
                "status_log_path": "status_log.json",
                "changelog_path": "changelog.csv",
                "report_path": "report.txt",
                "chart_path": "chart.png",
                "log_file": "monitor.log",
            },
            "notify": {"webhook_url": "", "webhook_type": "dingtalk"},
            "proxy": {"http": "", "https": ""},
        }
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_iso() -> str:
    """返回当前北京时间 ISO8601 字符串。"""
    # 使用 UTC+8
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
