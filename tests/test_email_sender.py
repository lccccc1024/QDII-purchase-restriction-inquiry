"""邮件发送模块单元测试：发送结果状态、凭证校验与心跳正文。"""

import sys
import os
from email import message_from_string
from email.header import decode_header

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import email_sender

RESULTS = [{
    "code": "000001",
    "name": "测试基金A",
    "index": "nasdaq100",
    "purchase_status": "暂停申购",
    "purchase_limit": 100.0,
    "checked_at": "2026-11-06T18:00:00+08:00",
    "source": "danjuan_api",
}]

CHANGES = [{
    "code": "000001",
    "name": "测试基金A",
    "index": "nasdaq100",
    "old_status": "限制大额申购",
    "new_status": "暂停申购",
    "old_limit": 10.0,
    "new_limit": 100.0,
    "checked_at": "2026-11-06T18:00:00+08:00",
}]


def _config():
    return {
        "email": {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "sender": "sender@example.com",
            "recipient": "a@example.com, b@example.com",
            "heartbeat_interval_days": 7,
        }
    }


class _FakeSMTP:
    """记录被发送的邮件，模拟投递成功。"""

    instances = []

    def __init__(self, host, port, timeout=30):
        self.host = host
        self.port = port
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user
        self.password = password

    def sendmail(self, sender, recipients, message):
        self.sent.append((sender, recipients, message))


class _BrokenSMTP:
    def __init__(self, *args, **kwargs):
        raise OSError("smtp down")


def _subject(raw_message: str) -> str:
    msg = message_from_string(raw_message)
    parts = decode_header(msg["Subject"])
    return "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in parts
    )


def _set_credentials(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "sender@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def _clear_credentials(monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)


class TestSendMonitorEmail:
    def test_no_changes_is_skipped(self, monkeypatch):
        _set_credentials(monkeypatch)
        assert email_sender.send_monitor_email(_config(), [], RESULTS) == email_sender.SEND_SKIPPED

    def test_missing_credentials_local_is_skipped(self, monkeypatch):
        _clear_credentials(monkeypatch)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        assert email_sender.send_monitor_email(_config(), CHANGES, RESULTS) == email_sender.SEND_SKIPPED

    def test_missing_credentials_in_ci_is_failure(self, monkeypatch):
        """CI 里缺 Secret 必须按失败处理，否则会永久静默。"""
        _clear_credentials(monkeypatch)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert email_sender.send_monitor_email(_config(), CHANGES, RESULTS) == email_sender.SEND_FAILED

    def test_sent(self, monkeypatch):
        _FakeSMTP.instances = []
        _set_credentials(monkeypatch)
        monkeypatch.setattr(email_sender.smtplib, "SMTP", _FakeSMTP)

        assert email_sender.send_monitor_email(_config(), CHANGES, RESULTS) == email_sender.SEND_SENT

        sender, recipients, raw = _FakeSMTP.instances[0].sent[0]
        assert sender == "sender@example.com"
        assert recipients == ["a@example.com", "b@example.com"]
        assert "1 只基金申购状态变化" in _subject(raw)
        assert "补发" not in _subject(raw)

    def test_retry_subject_is_marked(self, monkeypatch):
        _FakeSMTP.instances = []
        _set_credentials(monkeypatch)
        monkeypatch.setattr(email_sender.smtplib, "SMTP", _FakeSMTP)

        assert email_sender.send_monitor_email(
            _config(), CHANGES, RESULTS, retry=True
        ) == email_sender.SEND_SENT
        assert "补发" in _subject(_FakeSMTP.instances[0].sent[0][2])

    def test_smtp_error_is_failure(self, monkeypatch):
        _set_credentials(monkeypatch)
        monkeypatch.setattr(email_sender.smtplib, "SMTP", _BrokenSMTP)
        assert email_sender.send_monitor_email(_config(), CHANGES, RESULTS) == email_sender.SEND_FAILED


class TestHeartbeatEmail:
    def test_body_lists_status_and_last_change(self):
        body = email_sender._build_heartbeat_body(
            RESULTS, "2026-10-20T22:51:17+08:00", 4
        )
        assert "暂停申购" in body
        assert "2026-10-20 22:51" in body
        assert "4 条" in body
        assert "定期心跳" in body

    def test_body_without_history(self):
        body = email_sender._build_heartbeat_body(RESULTS)
        assert "暂无记录" in body

    def test_sent(self, monkeypatch):
        _FakeSMTP.instances = []
        _set_credentials(monkeypatch)
        monkeypatch.setattr(email_sender.smtplib, "SMTP", _FakeSMTP)

        status = email_sender.send_heartbeat_email(
            _config(), RESULTS, last_change_at="2026-10-20T22:51:17+08:00",
            last_change_count=4,
        )
        assert status == email_sender.SEND_SENT
        assert "周报" in _subject(_FakeSMTP.instances[0].sent[0][2])

    def test_empty_results_is_skipped(self, monkeypatch):
        _set_credentials(monkeypatch)
        assert email_sender.send_heartbeat_email(_config(), []) == email_sender.SEND_SKIPPED

    def test_missing_credentials_in_ci_is_failure(self, monkeypatch):
        _clear_credentials(monkeypatch)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert email_sender.send_heartbeat_email(_config(), RESULTS) == email_sender.SEND_FAILED
