"""主程序模块单元测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from monitor import compare_status


def _rec(code="000001", status="限制大额申购", limit=None, source="detail_page"):
    return {
        "code": code,
        "name": "测试基金A",
        "index": "nasdaq100",
        "purchase_status": status,
        "purchase_limit": limit,
        "checked_at": "2026-08-19T18:00:00+08:00",
        "source": source,
    }


class TestCompareStatus:
    def test_no_changes(self):
        old = [_rec(limit=5.0)]
        new = [_rec(limit=5.0)]
        assert compare_status(old, new) == []

    def test_status_change(self):
        old = [_rec(status="暂停申购", limit=None)]
        new = [_rec(status="开放申购", limit=None)]
        changes = compare_status(old, new)
        assert len(changes) == 1
        assert changes[0]["old_status"] == "暂停申购"
        assert changes[0]["new_status"] == "开放申购"

    def test_limit_change_both_present(self):
        old = [_rec(limit=5.0)]
        new = [_rec(limit=10.0)]
        assert len(compare_status(old, new)) == 1

    def test_limit_change_cross_source_ignored(self):
        """蛋卷备用源不提供限额(None)，跨源切换时不得误报限额变化。"""
        old = [_rec(limit=5.0, source="detail_page")]
        new = [_rec(limit=None, source="danjuan_api")]
        assert compare_status(old, new) == []

    def test_limit_change_from_none_ignored(self):
        """旧限额为 None（如蛋卷基线）时，恢复真实限额不得误报。"""
        old = [_rec(limit=None, source="danjuan_api")]
        new = [_rec(limit=5.0, source="detail_page")]
        assert compare_status(old, new) == []

    def test_new_fund_reported(self):
        new = [_rec(code="000002")]
        changes = compare_status([], new)
        assert len(changes) == 1
        assert changes[0]["old_status"] == "(新增)"

    def test_unknown_status_skipped(self):
        new = [_rec(status="未知")]
        assert compare_status([], new) == []