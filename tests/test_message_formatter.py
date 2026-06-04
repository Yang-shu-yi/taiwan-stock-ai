from message_formatter import format_market_report
from notifier import _with_dashboard_link


def _snapshot() -> dict:
    return {
        "updated_at": "2026-06-03 13:45:00",
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
                "invalidations": ["跌破 MA20 1000.0"],
                "confidence": "高",
                "data_quality": "正常",
            }
        ],
        "small_mid_candidates": [
            {
                "code": "6274",
                "name": "台燿",
                "small_mid_score": 82,
                "score": 82,
                "market_cap_billion": 45.5,
                "avg_turnover_million": 220.0,
                "reasons": ["市值合理", "站上 MA20/MA60"],
            }
        ],
        "theme_summary": [{"theme": "半導體", "score": 88.0, "leaders": ["2330 台積電"]}],
        "news_summary": {"tw_top_titles": ["台積電先進製程受關注 - news.cnyes.com"]},
        "data_status": {"news": {"ok": True, "cached": False, "trading_date": "2026-06-03"}},
        "performance_summary": {"count": 10, "avg_return_pct": 1.2, "win_rate": 0.6, "top5_hit_rate": 0.7},
    }


def test_market_report_contains_mobile_sections_and_utf8_text() -> None:
    text = format_market_report(_snapshot())
    assert "盤前可執行摘要" in text
    assert "🧭 開盤劇本" in text
    assert "🧪 資料狀態" in text
    assert "📈 近期訊號" in text
    assert "💎 中小型優質股雷達" in text
    assert "不是保證獲利" in text
    assert "news.cnyes.com" not in text


def test_dashboard_link_is_appended_once() -> None:
    message = "測試訊息"
    once = _with_dashboard_link(message)
    twice = _with_dashboard_link(once)
    assert once == twice
    assert once.count("https://taiwan-stock-ai-cmignppyqbx3qyslpthtnz.streamlit.app/") == 1


def test_market_report_flags_fallback_and_stale_data() -> None:
    snapshot = _snapshot()
    snapshot["data_status"] = {
        "twse_institutional": {
            "ok": True,
            "cached": False,
            "fallback_used": True,
            "trading_date": "2026-06-02",
            "stale_reason": "primary_openapi_failed",
        },
        "twse_margin": {
            "ok": False,
            "cached": False,
            "fallback_used": False,
            "trading_date": "2026-06-03",
            "stale_reason": "source_failed_no_cache",
        },
    }

    text = format_market_report(snapshot)

    assert "法人(備援/2026-06-02資料)" in text
    assert "融資券(來源失敗" in text
