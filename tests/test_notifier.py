import pytest

import notifier


def test_notify_report_keeps_successful_channel_when_line_fails(monkeypatch) -> None:
    sent = []

    def fake_telegram(message: str) -> bool:
        sent.append(("telegram", message))
        return True

    def fake_line(message: str) -> bool:
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(notifier, "send_report_message", fake_telegram)
    monkeypatch.setattr(notifier, "send_line_message", fake_line)

    notifier.notify_report("盤後報告")

    assert sent == [("telegram", notifier._with_dashboard_link("盤後報告"))]


def test_notify_report_raises_only_when_all_enabled_channels_fail(monkeypatch) -> None:
    monkeypatch.setattr(notifier, "ENABLE_REPORT_TELEGRAM", True)
    monkeypatch.setattr(notifier, "ENABLE_LINE", True)
    monkeypatch.setattr(notifier, "send_report_message", lambda message: (_ for _ in ()).throw(RuntimeError("telegram failed")))
    monkeypatch.setattr(notifier, "send_line_message", lambda message: (_ for _ in ()).throw(RuntimeError("line failed")))

    with pytest.raises(RuntimeError, match="all enabled notification channels failed"):
        notifier.notify_report("盤前報告")
