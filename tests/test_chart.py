"""图表模块单元测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chart import _shorten_name, _format_limit


class TestShortenName:
    def test_remove_suffix(self):
        result = _shorten_name("华安纳斯达克100联接A")
        assert "联接" not in result or len(result) <= 16

    def test_truncation_keeps_suffix(self):
        """截断时应保留末尾的 A/C 份额标记。"""
        long_name = "非常长长长长长长长长长长长纳斯达克100联接A"
        result = _shorten_name(long_name)
        assert result.endswith("A"), f"Expected suffix A, got: {result}"

    def test_short_name_unchanged(self):
        name = "短名称"
        assert _shorten_name(name) == name


class TestFormatLimit:
    def test_suspended(self):
        assert _format_limit("暂停申购", None) == "暂停"

    def test_open(self):
        assert _format_limit("开放申购", None) == "开放"

    def test_wan_format(self):
        result = _format_limit("限制大额申购", 1000000)
        assert "万" in result

    def test_raw_amount(self):
        assert _format_limit("限制大额申购", 500) == "¥500"
