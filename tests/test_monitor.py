"""主程序模块单元测试。"""

import json
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import email_sender
from monitor import (
    compare_status,
    dispatch_notifications,
    heartbeat_due,
    merge_pending,
    merge_snapshot,
)


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


def _chg(code="000001", old="暂停申购", new="限制大额申购",
         old_limit=None, new_limit=10.0, checked_at="2026-11-01T18:00:00+08:00"):
    return {
        "code": code,
        "name": "测试基金A",
        "index": "nasdaq100",
        "old_status": old,
        "new_status": new,
        "old_limit": old_limit,
        "new_limit": new_limit,
        "checked_at": checked_at,
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


class TestMergeSnapshot:
    """快照合并：未知状态不得删除既有记录。"""

    def test_unknown_keeps_previous_record(self):
        previous = [_rec(status="暂停申购", limit=None)]
        merged = merge_snapshot(previous, [_rec(status="未知", limit=None)])
        assert len(merged) == 1
        assert merged[0]["purchase_status"] == "暂停申购"

    def test_unknown_without_history_is_dropped(self):
        assert merge_snapshot([], [_rec(status="未知")]) == []

    def test_known_replaces_previous(self):
        previous = [_rec(status="暂停申购")]
        merged = merge_snapshot(previous, [_rec(status="开放申购")])
        assert merged[0]["purchase_status"] == "开放申购"

    def test_total_outage_keeps_snapshot_intact(self):
        """全部未知时快照内容不得变化——否则恢复后会刷出一批假"(新增)"。"""
        previous = [_rec(code="000001"), _rec(code="000002", status="开放申购")]
        results = [_rec(code="000001", status="未知"), _rec(code="000002", status="未知")]
        assert merge_snapshot(previous, results) == previous


class TestMergePending:
    """补发队列合并：同一基金只保留一条净变化。"""

    def test_empty_pending_returns_changes(self):
        changes = [_chg()]
        assert merge_pending([], changes) == changes

    def test_pending_only_is_kept(self):
        pending = [_chg()]
        assert merge_pending(pending, []) == pending

    def test_same_fund_merges_to_net_change(self):
        """补发期间同一基金又变了一次：旧状态取最早、新状态取最新。"""
        pending = [_chg(old="限制大额申购", new="开放申购",
                        checked_at="2026-11-01T18:00:00+08:00")]
        changes = [_chg(old="开放申购", new="暂停申购",
                        checked_at="2026-11-02T18:00:00+08:00")]
        merged = merge_pending(pending, changes)
        assert len(merged) == 1
        assert merged[0]["old_status"] == "限制大额申购"
        assert merged[0]["new_status"] == "暂停申购"
        assert merged[0]["checked_at"].startswith("2026-11-02")

    def test_different_funds_are_all_kept(self):
        merged = merge_pending([_chg(code="000001")], [_chg(code="000002")])
        assert {m["code"] for m in merged} == {"000001", "000002"}

    def test_invalid_entries_are_ignored(self):
        merged = merge_pending([{"name": "无代码"}], [None, _chg()])
        assert len(merged) == 1
        assert merged[0]["code"] == "000001"


class TestHeartbeatDue:
    """心跳节奏：距上次成功发信满 N 天。"""

    def test_disabled(self):
        assert heartbeat_due(0, "", date(2026, 11, 7)) is False
        assert heartbeat_due(-1, "", date(2026, 11, 7)) is False

    def test_never_sent_is_due(self):
        assert heartbeat_due(7, "", date(2026, 11, 7)) is True

    def test_not_due_before_interval(self):
        assert heartbeat_due(7, "2026-11-02", date(2026, 11, 7)) is False

    def test_due_on_interval(self):
        assert heartbeat_due(7, "2026-10-31", date(2026, 11, 7)) is True

    def test_invalid_value_treated_as_due(self):
        assert heartbeat_due(7, "not-a-date", date(2026, 11, 7)) is True


class TestDispatchNotifications:
    """通知分发：失败入队补发、成功清空、无变化按周心跳。"""

    def _config(self, tmp_path, interval=7):
        return {
            "data": {"notify_state_path": str(tmp_path / "notify_state.json")},
            "email": {"heartbeat_interval_days": interval},
        }

    def _read_state(self, tmp_path):
        return json.loads((tmp_path / "notify_state.json").read_text(encoding="utf-8"))

    def test_failure_queues_changes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            email_sender, "send_monitor_email",
            lambda *a, **k: email_sender.SEND_FAILED,
        )
        cfg = self._config(tmp_path)
        ok = dispatch_notifications(cfg, [_chg()], [_rec()])
        assert ok is False
        state = self._read_state(tmp_path)
        assert len(state["pending"]) == 1
        assert state["last_change_at"].startswith("2026-11-01")

    def test_success_clears_pending(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path)
        (tmp_path / "notify_state.json").write_text(
            json.dumps({"pending": [_chg()], "last_email_at": ""}), encoding="utf-8"
        )
        sent = {}

        def _fake_send(config, changes, results, retry=False):
            sent["retry"] = retry
            sent["count"] = len(changes)
            return email_sender.SEND_SENT

        monkeypatch.setattr(email_sender, "send_monitor_email", _fake_send)
        ok = dispatch_notifications(cfg, [], [_rec()])
        assert ok is True
        assert sent == {"retry": True, "count": 1}
        assert self._read_state(tmp_path)["pending"] == []

    def test_heartbeat_when_no_changes(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path)
        calls = []
        monkeypatch.setattr(
            email_sender, "send_heartbeat_email",
            lambda *a, **k: calls.append(True) or email_sender.SEND_SENT,
        )
        ok = dispatch_notifications(cfg, [], [_rec()])
        assert ok is True
        assert calls
        state = self._read_state(tmp_path)
        # 发信日期按北京时间记录，这里只校验格式与非空
        date.fromisoformat(state["last_email_at"])
        assert len(state["last_email_at"]) == 10

    def test_heartbeat_skipped_when_recently_sent(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path)
        (tmp_path / "notify_state.json").write_text(
            json.dumps({"last_email_at": date.today().isoformat()}), encoding="utf-8"
        )
        calls = []
        monkeypatch.setattr(
            email_sender, "send_heartbeat_email",
            lambda *a, **k: calls.append(True) or email_sender.SEND_SENT,
        )
        assert dispatch_notifications(cfg, [], [_rec()]) is True
        assert calls == []

    def test_heartbeat_failure_is_reported(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path)
        monkeypatch.setattr(
            email_sender, "send_heartbeat_email",
            lambda *a, **k: email_sender.SEND_FAILED,
        )
        assert dispatch_notifications(cfg, [], [_rec()]) is False
        assert self._read_state(tmp_path)["last_email_at"] == ""