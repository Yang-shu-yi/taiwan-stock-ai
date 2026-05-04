from data_layer import get_data_status, record_news_status, record_status, reset_data_status


def test_records_source_status() -> None:
    reset_data_status()
    record_status("yahoo_test", True, "unit", 15)
    status = get_data_status()
    assert status["yahoo_test"]["ok"] is True
    assert status["yahoo_test"]["source"] == "unit"
    assert status["yahoo_test"]["ttl_minutes"] == 15
    assert status["yahoo_test"]["trading_date"]
    assert status["yahoo_test"]["as_of"]
    assert status["yahoo_test"]["fallback_used"] is False


def test_news_status_marks_empty_feed_as_failed() -> None:
    reset_data_status()
    record_news_status(0, 0)
    status = get_data_status()
    assert status["news"]["ok"] is False
    assert "no news" in status["news"]["error"]
