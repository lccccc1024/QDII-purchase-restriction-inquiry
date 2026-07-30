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
)


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
