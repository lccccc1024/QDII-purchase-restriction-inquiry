"""工具函数单元测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    PurchaseStatus,
    normalize_status,
    parse_limit_amount,
)


class TestNormalizeStatus:
    """测试 normalize_status 的关键词→枚举映射。"""

    def test_open_variants(self):
        assert normalize_status("开放申购") == PurchaseStatus.OPEN
        assert normalize_status("正常申购") == PurchaseStatus.OPEN
        assert normalize_status("可申购") == PurchaseStatus.OPEN
        assert normalize_status("开放") == PurchaseStatus.OPEN

    def test_suspended_variants(self):
        assert normalize_status("暂停申购") == PurchaseStatus.SUSPENDED
        assert normalize_status("暂停") == PurchaseStatus.SUSPENDED
        assert normalize_status("停止申购") == PurchaseStatus.SUSPENDED

    def test_limited_variants(self):
        assert normalize_status("限制大额申购") == PurchaseStatus.LIMITED
        assert normalize_status("限大额") == PurchaseStatus.LIMITED
        assert normalize_status("暂停大额申购") == PurchaseStatus.LIMITED
        assert normalize_status("单日限额") == PurchaseStatus.LIMITED

    def test_terminated_variants(self):
        assert normalize_status("清盘") == PurchaseStatus.TERMINATED
        assert normalize_status("终止") == PurchaseStatus.TERMINATED

    def test_empty_and_unknown(self):
        assert normalize_status("") == PurchaseStatus.UNKNOWN
        assert normalize_status(None) == PurchaseStatus.UNKNOWN
        assert normalize_status("无关文字") == PurchaseStatus.UNKNOWN

    def test_limited_priority_over_suspended(self):
        """'限制大额申购'含'暂停'关键字，需确保 LIMITED 优先级高于 SUSPENDED。"""
        assert normalize_status("暂停大额申购") == PurchaseStatus.LIMITED
        assert normalize_status("限制大额申购") == PurchaseStatus.LIMITED


class TestParseLimitAmount:
    """测试 parse_limit_amount 的金额提取逻辑。"""

    def test_numeric(self):
        assert parse_limit_amount("1000") == 1000.0
        assert parse_limit_amount("500.00") == 500.0

    def test_with_unit_yuan(self):
        assert parse_limit_amount("1000元") == 1000.0
        assert parse_limit_amount("500.00元") == 500.0

    def test_with_wan(self):
        assert parse_limit_amount("100万") == 1000000.0
        assert parse_limit_amount("100.5万") == 1005000.0

    def test_with_yi(self):
        assert parse_limit_amount("1亿") == 100000000.0
        assert parse_limit_amount("1.5亿") == 150000000.0

    def test_wan_precedence(self):
        """"100万"应被万匹配捕获，不会被普通数字误匹配为 100。"""
        result = parse_limit_amount("100万")
        assert result == 1000000.0, f"Expected 1000000, got {result}"

    def test_with_comma(self):
        assert parse_limit_amount("1,000.00") == 1000.0

    def test_empty_and_none(self):
        assert parse_limit_amount("") is None
        assert parse_limit_amount(None) is None

    def test_no_number(self):
        assert parse_limit_amount("无限制") is None
        assert parse_limit_amount("开放申购") is None
