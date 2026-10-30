"""抓取模块单元测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fetcher import (
    classify_index,
    _match_any_keyword,
    _is_etf_listed,
    _is_foreign_currency,
    _is_non_ac_share,
    _fetch_mobile_api,
    _try_detail_page,
)
from utils import PurchaseStatus


class _FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def json(self):
        if self._payload is None:
            raise ValueError("response is not JSON")
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.timeout = 5
        self.api_mobile_url = "https://example.invalid/{code}"
        self.api_mobile_v2_url = "https://example.invalid/v2/{code}"
        self.api_detail_page_url = "https://example.invalid/{code}.html"
        self.api_status_page_url = "https://example.invalid/status/{code}"

    def get(self, url, **kwargs):
        return self._response


class TestMobileApiParsing:
    def test_accepts_string_error_code(self):
        """ErrCode 为字符串 "0" 时不应被判为失败（否则整条主数据源被跳过）。"""
        payload = {"ErrCode": "0", "Data": {"SGZT": "开放申购"}}
        session = _FakeSession(_FakeResponse(payload=payload))
        result = _fetch_mobile_api(
            session, "000001", session.api_mobile_url, "mobile",
            ["SGZT"], ["SGDM"], "SGZQ",
        )
        assert result is not None
        assert result["purchase_status"] == PurchaseStatus.OPEN

    def test_rejects_nonzero_error_code(self):
        payload = {"ErrCode": 1, "Data": {"SGZT": "开放申购"}}
        session = _FakeSession(_FakeResponse(payload=payload))
        assert _fetch_mobile_api(
            session, "000001", session.api_mobile_url, "mobile",
            ["SGZT"], ["SGDM"], "SGZQ",
        ) is None


class TestDetailPageParsing:
    def test_ignores_keyword_outside_status_block(self):
        """页面别处的"暂停申购"不得盖过"交易状态"里的真实状态。"""
        html = """
        <html><body>
          <p>常见问题：基金暂停申购后还能赎回吗？</p>
          <p>交易状态：限大额（单日累计购买上限1000元）</p>
        </body></html>
        """
        session = _FakeSession(_FakeResponse(text=html))
        result = _try_detail_page(session, "000001")
        assert result is not None
        assert result["purchase_status"] == PurchaseStatus.LIMITED
        assert result["purchase_limit"] == 1000.0

    def test_falls_back_to_whole_text_without_anchor(self):
        html = "<html><body><p>当前开放申购</p></body></html>"
        session = _FakeSession(_FakeResponse(text=html))
        result = _try_detail_page(session, "000001")
        assert result is not None
        assert result["purchase_status"] == PurchaseStatus.OPEN


class TestClassifyIndex:
    def test_nasdaq100(self):
        assert classify_index("华安纳斯达克100联接A") == "nasdaq100"
        assert classify_index("Nasdaq100") == "nasdaq100"

    def test_sp500(self):
        assert classify_index("博时标普500联接A") == "sp500"
        assert classify_index("S&P500") == "sp500"

    def test_unknown(self):
        assert classify_index("沪深300") is None
        assert classify_index("") is None


class TestMatchAnyKeyword:
    def test_matches_nasdaq(self):
        assert _match_any_keyword("纳斯达克100") is True

    def test_matches_sp500(self):
        assert _match_any_keyword("标普500") is True

    def test_no_match(self):
        assert _match_any_keyword("沪深300") is False


class TestIsETFListed:
    def test_etf_listed(self):
        assert _is_etf_listed("纳指ETF", "ETF-场内") is True
        assert _is_etf_listed("标普500ETF", "ETF-场内") is True

    def test_etf_connected(self):
        """ETF联接基金应被视为场外基金，不被排除。"""
        assert _is_etf_listed("纳指ETF联接A", "ETF联接") is False

    def test_non_etf(self):
        assert _is_etf_listed("普通基金A", "股票型") is False


class TestIsForeignCurrency:
    def test_forex(self):
        assert _is_foreign_currency("美元现汇") is True
        assert _is_foreign_currency("美汇") is True

    def test_rmb(self):
        assert _is_foreign_currency("人民币A") is False


class TestIsNonACShare:
    def test_non_ac(self):
        assert _is_non_ac_share("联接D") is True
        assert _is_non_ac_share("联接E") is True
        assert _is_non_ac_share("联接F") is True

    def test_ac_valid(self):
        assert _is_non_ac_share("联接A") is False
        assert _is_non_ac_share("联接C") is False
