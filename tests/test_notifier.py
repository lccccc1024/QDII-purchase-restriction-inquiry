"""通知模块单元测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notifier import (
    _build_summary,
    _build_change_lines,
    _escape_markdown,
)


class TestBuildSummary:
    def test_empty(self):
        assert _build_summary([]) == []

    def test_with_data(self):
        data = [
            {"index": "nasdaq100", "purchase_status": "开放申购"},
            {"index": "nasdaq100", "purchase_status": "暂停申购"},
        ]
        lines = _build_summary(data)
        assert len(lines) == 1
        assert "纳指100" in lines[0]


class TestBuildChangeLines:
    def test_no_changes(self):
        lines = _build_change_lines([], with_color=False)
        assert any("未检测到" in l for l in lines)

    def test_with_changes(self):
        changes = [{
            "code": "000001",
            "name": "测试基金A",
            "index": "nasdaq100",
            "old_status": "暂停申购",
            "new_status": "开放申购",
            "old_limit": None,
            "new_limit": None,
            "checked_at": "2024-01-01T00:00:00",
        }]
        lines = _build_change_lines(changes, with_color=False)
        combined = "\n".join(lines)
        assert "暂停申购" in combined
        assert "开放申购" in combined


class TestEscapeMarkdown:
    def test_escape_special_chars(self):
        assert _escape_markdown("a*b_c[d]e") == r"a\*b\_c\[d\]e"
