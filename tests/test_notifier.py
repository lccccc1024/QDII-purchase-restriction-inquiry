"""通知模块单元测试（变更记录裁剪）。"""

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notifier
from notifier import append_changelog_csv


def _change(i: int) -> dict:
    return {
        "checked_at": f"2026-10-{i + 1:02d}T18:00:00+08:00",
        "code": f"0000{i:02d}",
        "name": f"测试基金{i}",
        "index": "nasdaq100" if i % 2 == 0 else "sp500",
        "old_status": "暂停申购",
        "new_status": "开放申购",
        "old_limit": None,
        "new_limit": 1000.0,
    }


def _read(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_creates_header_and_rows(tmp_path):
    path = str(tmp_path / "changelog.csv")
    append_changelog_csv([_change(1), _change(2)], path)

    rows = _read(path)
    assert rows[0][0] == "时间"
    assert len(rows) == 3


def test_trims_to_recent_rows(tmp_path, monkeypatch):
    """超过上限时保留最近 N 条，表头不变。"""
    monkeypatch.setattr(notifier, "CHANGELOG_MAX_ROWS", 5)
    path = str(tmp_path / "changelog.csv")

    for i in range(8):
        append_changelog_csv([_change(i)], path)

    rows = _read(path)
    assert len(rows) == 6, rows
    assert rows[0][0] == "时间"
    # 最近一条必须保留
    assert rows[-1][1] == "000007"


def test_no_trim_below_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(notifier, "CHANGELOG_MAX_ROWS", 5)
    path = str(tmp_path / "changelog.csv")

    for i in range(3):
        append_changelog_csv([_change(i)], path)

    assert len(_read(path)) == 4


def test_empty_changes_is_noop(tmp_path):
    path = str(tmp_path / "changelog.csv")
    append_changelog_csv([], path)
    assert not os.path.exists(path)
