"""数据抓取与解析：天天基金网公开接口。"""

import ast
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from utils import (
    PurchaseStatus,
    normalize_status,
    parse_limit_amount,
    now_iso,
)

logger = logging.getLogger(__name__)

# 搜索关键词（大小写不敏感）
NASDAQ_KEYWORDS = [
    "纳斯达克100", "纳指100", "纳斯达克 100", "nasdaq100", "nasdaq 100",
    "nasdaq-100",
]
SP500_KEYWORDS = [
    "标普500", "标普 500", "s&p500", "s&p 500", "sp500", "标普500指数",
]
EXCLUDE_TYPES = {"ETF-场内", "场内ETF"}  # 排除场内ETF

FUND_LIST_URL = "http://fund.eastmoney.com/js/fundcode_search.js"
FUND_STATUS_PAGE = "http://fund.eastmoney.com/f10/jjjz_{code}.html"
FUND_DETAIL_PAGE = "http://fund.eastmoney.com/{code}.html"
# 手机端API，返回JSON，优先使用
FUND_MOBILE_API = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNBasicInformation?FCODE={code}&deviceid=ios_efund&plat=iOS&product=EFund&version=7.0.0"
# 备用手机端 API v2
FUND_MOBILE_API_V2 = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFundBaseInfoNew?FCODE={code}&deviceid=android&plat=Android&product=EFund&version=7.3.8"


def create_session(config: dict) -> requests.Session:
    """创建带 UA 和代理配置的 requests Session。"""
    s = requests.Session()
    s.headers["User-Agent"] = config.get("scan", {}).get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    s._timeout = config.get("scan", {}).get("timeout", 15)
    proxy = config.get("proxy", {})
    if proxy.get("http") or proxy.get("https"):
        s.proxies = {k: v for k, v in proxy.items() if v}
    return s


# ═══════════════════════════════════════════════════════
#  基金列表发现
# ═══════════════════════════════════════════════════════

def get_all_funds(session: requests.Session) -> list[dict]:
    """从 fundcode_search.js 获取全市场基金列表。"""
    logger.info("正在获取全市场基金列表...")
    resp = session.get(FUND_LIST_URL, timeout=getattr(session, "_timeout", 15))
    resp.raise_for_status()
    text = resp.text

    # 格式: var r = [["000001","HXCXJJ","华夏成长基金","混合型",""], ...]
    # 正则依赖非贪婪 .*? 匹配整个双层 JSON 数组；失败时降级到无变量名的二次匹配。
    # 若天天基金网调整 JS 变量名或格式，需同步更新此处。
    match = re.search(r"var\s+r\s*=\s*(\[\[.*?\]\]);", text, re.DOTALL)
    if not match:
        match = re.search(r"(\[\[.*?\]\])", text, re.DOTALL)
    if not match:
        raise ValueError("无法解析基金列表数据")

    raw = match.group(1)
    # 用 json 解析前先处理 JS 中的特殊字符
    # 替换 JS 中的单引号转义
    raw = raw.replace("\\'", "'")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 降级: ast.literal_eval 安全解析
        data = ast.literal_eval(raw)

    funds = []
    for item in data:
        funds.append({
            "code": item[0],
            "pinyin": item[1],
            "name": item[2],
            "type": item[3],
        })
    logger.info(f"获取到 {len(funds)} 只基金")
    return funds


def classify_index(name: str) -> str | None:
    """根据基金名称判断跟踪指数类型。复用模块级关键词列表以保证与 _match_any_keyword 同步。"""
    name_lower = name.lower()
    for kw in NASDAQ_KEYWORDS:
        if kw in name_lower:
            return "nasdaq100"
    for kw in SP500_KEYWORDS:
        if kw in name_lower:
            return "sp500"
    return None


def _match_any_keyword(name: str) -> bool:
    """检查基金名称是否匹配任一目标关键词。"""
    name_lower = name.lower()
    for kw in NASDAQ_KEYWORDS + SP500_KEYWORDS:
        if kw in name_lower:
            return True
    return False


def _is_etf_listed(name: str, fund_type: str) -> bool:
    """判断是否为场内 ETF（需排除）。"""
    for et in EXCLUDE_TYPES:
        if et in fund_type:
            return True
    name_has_etf = "ETF" in name.upper()
    name_has_lianjie = "联接" in name or "连接" in name
    if name_has_etf and not name_has_lianjie:
        return True
    return False


def _is_foreign_currency(name: str) -> bool:
    """判断是否为美元/非人民币份额。排除「美元现汇」「美元现钞」「美汇」「美钞」等。"""
    forex_keywords = ["美元", "美汇", "美钞"]
    for kw in forex_keywords:
        if kw in name:
            return True
    return False


def _is_non_ac_share(name: str) -> bool:
    """判断是否为非 A/C 类份额（D/E/F/I 等）。只保留最常见的 A 类和 C 类。"""
    # )D )E )F )I  或结尾为 D/E/F/I（如"人民币E""人民币F"）
    if re.search(r"[)）]([DEFI])(?:[（(]|人民币|$)", name):
        return True
    # E(  如 "联接E(人民币)"
    if re.search(r"[DEFI][（(]", name):
        return True
    # 以 D/E/F/I 结尾（如 "人民币E"、"人民币F"）
    if re.search(r"[DEFI]$", name):
        return True
    return False


def discover_target_funds(session: requests.Session, config: dict) -> list[dict]:
    """获取全量列表，过滤出场外纳指100/标普500基金。"""
    all_funds = get_all_funds(session)
    results = []
    excluded_etf = 0
    excluded_forex = 0
    excluded_share = 0
    for f in all_funds:
        if not _match_any_keyword(f["name"]):
            continue
        if _is_etf_listed(f["name"], f["type"]):
            excluded_etf += 1
            logger.debug(f"排除场内ETF: {f['code']} {f['name']} (类型: {f['type']})")
            continue
        if _is_foreign_currency(f["name"]):
            excluded_forex += 1
            logger.debug(f"排除外币份额: {f['code']} {f['name']}")
            continue
        if _is_non_ac_share(f["name"]):
            excluded_share += 1
            logger.debug(f"排除非A/C份额: {f['code']} {f['name']}")
            continue
        index_type = classify_index(f["name"])
        if index_type is None:
            continue
        results.append({
            "code": f["code"],
            "name": f["name"],
            "type": f["type"],
            "index": index_type,
            "added": now_iso(),
        })
    logger.info(
        f"排除 {excluded_etf} 只场内ETF、{excluded_forex} 只外币份额、"
        f"{excluded_share} 只非A/C份额，筛选得到 {len(results)} 只目标基金"
    )
    return results


# ═══════════════════════════════════════════════════════
#  申购状态查询
# ═══════════════════════════════════════════════════════

def _try_mobile_api(session: requests.Session, code: str) -> dict | None:
    """尝试手机端 JSON API 获取基金基本信息。"""
    return _fetch_mobile_api(session, code, FUND_MOBILE_API, "mobile_api",
                             status_keys=("SGSTATUS", "sgStatus"),
                             limit_keys=("SGLIMIT", "sgLimit"),
                             date_key="JJJL")


def _try_mobile_api_v2(session: requests.Session, code: str) -> dict | None:
    """尝试手机端 JSON API v2 获取基金基本信息。"""
    return _fetch_mobile_api(session, code, FUND_MOBILE_API_V2, "mobile_api_v2",
                             status_keys=("sgStatus", "SGSTATUS"),
                             limit_keys=("sgLimit", "SGLIMIT"),
                             date_key="effectiveDate")


def _fetch_mobile_api(session, code, url_template, source_name,
                      status_keys, limit_keys, date_key) -> dict | None:
    """手机端 JSON API 通用请求逻辑。"""
    url = url_template.format(code=code)
    try:
        resp = session.get(url, timeout=getattr(session, "_timeout", 15))
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("ErrCode") != 0:
            return None
        info = data.get("Data", {})
        if not info:
            return None
        sg_status_raw = ""
        for k in status_keys:
            v = info.get(k, "")
            if v:
                sg_status_raw = v
                break
        sg_limit_raw = ""
        for k in limit_keys:
            v = info.get(k, "")
            if v:
                sg_limit_raw = v
                break
        return {
            "purchase_status": normalize_status(sg_status_raw),
            "purchase_limit": parse_limit_amount(sg_limit_raw),
            "effective_date": info.get(date_key, ""),
            "announcement": "",
            "raw_status_text": sg_status_raw,
            "source": source_name,
        }
    except Exception as e:
        logger.debug(f"{source_name}获取失败 {code}: {e}")
        return None


def _try_status_page(session: requests.Session, code: str) -> dict | None:
    """解析基金申购状态页面 HTML。"""
    url = FUND_STATUS_PAGE.format(code=code)
    try:
        resp = session.get(url, timeout=getattr(session, "_timeout", 15))
        if resp.status_code != 200:
            return None
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        tables = soup.find_all("table")
        if not tables:
            return None
        status_text = ""
        limit_text = ""
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    val = cells[1].get_text(strip=True)
                    if "申购状态" in key:
                        status_text = val
                    elif "申购上限" in key or "累计申购" in key:
                        limit_text = val

        if not status_text:
            return None

        return {
            "purchase_status": normalize_status(status_text),
            "purchase_limit": parse_limit_amount(limit_text) if limit_text else None,
            "effective_date": "",
            "announcement": "",
            "raw_status_text": status_text,
            "source": "status_page",
        }
    except Exception as e:
        logger.debug(f"状态页面获取失败 {code}: {e}")
        return None


def _try_detail_page(session: requests.Session, code: str) -> dict | None:
    """解析基金详情页 HTML，提取申购状态信息。

    HTML 结构 (2024+):
      <span class="itemTit">交易状态：</span>
      <span class="staticCell">限大额  (<span>单日累计购买上限500.00元</span>)</span>
      <span class="staticCell">开放赎回</span>
    """
    url = FUND_DETAIL_PAGE.format(code=code)
    try:
        resp = session.get(url, timeout=getattr(session, "_timeout", 15))
        if resp.status_code != 200:
            return None
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        text = resp.text

        status_text = ""
        limit_text = ""

        # 方法1: 通过 BS4 定位 "交易状态" 的 span，取下一个 staticCell
        for span in soup.find_all("span", class_="itemTit"):
            if "交易状态" in span.get_text():
                # 下一个 class="staticCell" 的 span
                parent_div = span.find_parent("div")
                if parent_div:
                    cell = parent_div.find("span", class_="staticCell")
                    if cell:
                        raw = cell.get_text(strip=True)
                        # raw 格式: "限大额  (单日累计购买上限500.00元)"
                        # 或: "暂停申购  (单日累计购买上限100.00元)"
                        # 或: "开放申购"
                        # 提取状态部分（括号前的内容）
                        status_part = raw.split("(")[0].strip()
                        if "限大额" in status_part or "限制大额" in status_part:
                            status_text = "限制大额申购"
                        elif "暂停" in status_part:
                            status_text = "暂停申购"
                        elif "开放" in status_part:
                            status_text = "开放申购"
                        else:
                            status_text = status_part
                break

        # 从原始 HTML 提取限额: 单日累计购买上限XXX元
        limit_m = re.search(
            r"单日累计购买上限\s*([\d,.]+)\s*元",
            text,
        )
        if limit_m:
            limit_text = limit_m.group(1).strip()

        # 方法2（兜底）: 在整页文本中搜索已知状态关键词
        if not status_text:
            all_text = soup.get_text()
            for kw, mapped in [
                ("暂停申购", "暂停申购"),
                ("限制大额申购", "限制大额申购"),
                ("暂停大额申购", "限制大额申购"),
                ("限大额", "限制大额申购"),
                ("开放申购", "开放申购"),
            ]:
                if kw in all_text:
                    status_text = mapped
                    break

        if not status_text:
            return None

        result = normalize_status(status_text)
        return {
            "purchase_status": result,
            "purchase_limit": parse_limit_amount(limit_text) if limit_text else None,
            "effective_date": "",
            "announcement": "",
            "raw_status_text": status_text,
            "source": "detail_page",
        }
    except Exception as e:
        logger.debug(f"详情页获取失败 {code}: {e}")
        return None


def get_fund_purchase_status(session: requests.Session, code: str) -> dict:
    """获取单只基金的申购状态，按优先级尝试多个数据源。"""
    for fetcher in (_try_mobile_api, _try_mobile_api_v2, _try_status_page, _try_detail_page):
        result = fetcher(session, code)
        if result and result.get("purchase_status") != PurchaseStatus.UNKNOWN:
            return result
    # 所有方式均失败
    return {
        "purchase_status": PurchaseStatus.UNKNOWN,
        "purchase_limit": None,
        "effective_date": "",
        "announcement": "",
        "raw_status_text": "获取失败",
        "source": "none",
    }


def scan_all_funds(
    session: requests.Session,
    fund_list: list[dict],
    config: dict,
) -> list[dict]:
    """遍历基金列表获取最新申购状态。遇到网络异常时自动重试一次。"""
    delay = config.get("scan", {}).get("delay_between_requests", 1.5)
    results = []
    total = len(fund_list)
    for i, fund in enumerate(fund_list):
        code = fund["code"]
        name = fund["name"]
        logger.info(f"[{i+1}/{total}] 查询 {code} {name}...")
        status_info = get_fund_purchase_status(session, code)

        # 首次失败 → 等待后重试一次（防网络抖动）
        if status_info["purchase_status"] == PurchaseStatus.UNKNOWN:
            logger.info(f"  ⤴ 首次无结果，等待后重试 {code}...")
            time.sleep(delay * 2)
            status_info = get_fund_purchase_status(session, code)

        record = {
            "code": code,
            "name": name,
            "index": fund.get("index", ""),
            "purchase_status": status_info["purchase_status"].value,
            "purchase_limit": status_info.get("purchase_limit"),
            "effective_date": status_info.get("effective_date", ""),
            "announcement": status_info.get("announcement", ""),
            "raw_status_text": status_info.get("raw_status_text", ""),
            "source": status_info.get("source", "unknown"),
            "checked_at": now_iso(),
        }
        results.append(record)
        if i < total - 1:
            time.sleep(delay)
    return results
