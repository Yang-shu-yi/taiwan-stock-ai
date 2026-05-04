from message_formatter import format_market_report
from notifier import _with_dashboard_link


def _snapshot() -> dict:
    return {
        "mode": "PRE",
        "market": {
            "tw_index": {"price": "20000", "pct": "+0.50", "turnover": "3000億"},
            "forex": {"rate": "31.500"},
        },
        "us_context": [{"symbol": "SOXX", "pct_1d": 1.2}],
        "tw_candidates": [
            {
                "code": "2330",
                "name": "台積電",
                "pct_1d": 1.5,
                "theme": "半導體",
                "reasons": ["站上 MA20", "量能放大"],
            }
        ],
        "theme_summary": [{"theme": "半導體", "score": 88.0, "leaders": ["2330 台積電"]}],
        "news_summary": {"tw_top_titles": ["台積電先進製程受關注 - news.cnyes.com"]},
        "data_status": {"news": {"ok": True, "cached": False}},
        "performance_summary": {"count": 10, "avg_return_pct": 1.2, "win_rate": 0.6, "top5_hit_rate": 0.7},
    }


def test_market_report_contains_mobile_sections_and_utf8_text() -> None:
    text = format_market_report(_snapshot())
    assert "盤前可執行摘要" in text
    assert "🧭 開盤劇本" in text
    assert "🧪 資料狀態" in text
    assert "📈 近期訊號" in text
    assert "不是保證獲利" in text
    assert "news.cnyes.com" not in text


def test_dashboard_link_is_appended_once() -> None:
    message = "測試訊息"
    once = _with_dashboard_link(message)
    twice = _with_dashboard_link(once)
    assert once == twice
    assert once.count("https://taiwan-stock-ai-cmignppyqbx3qyslpthtnz.streamlit.app/") == 1
