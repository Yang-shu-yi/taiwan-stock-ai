from message_formatter import format_intraday_alert, format_market_report
from notifier import _with_dashboard_link


def _snapshot() -> dict:
    candidates = [
        {
            "code": "2330",
            "name": "台積電",
            "price": 1050,
            "score": 90,
            "entry_score": 72,
            "entry_status": "scale_in",
            "entry_status_label": "可分批布局",
            "entry_action": "風險報酬仍可控，可依規劃停損小量分批。",
            "pct_1d": 1.5,
            "theme": "半導體",
            "reasons": ["站上 MA20", "量能放大"],
            "invalidations": ["跌破 MA20 1000.0"],
            "confidence": "高",
            "data_quality": "正常",
            "company_assessment": {
                "company_quality_score": 86,
                "valuation_attractiveness_score": 74,
                "entry_timing_score": 38,
                "event_risk_level": "中",
                "opportunity_label": "優質回檔觀察",
                "fundamental_summary": "最新月營收年增 +18.0%、累計年增 +12.0%；營收成長仍有延續。",
                "plain_language_advice": "公司與估值條件較佳，但價格尚未止跌；先等股價站回 MA20，且下次月營收年增未轉負，再考慮小量分批。",
            },
        }
    ]
    candidates.extend(
        {
            "code": str(2300 + index),
            "name": f"測試股{index}",
            "price": 100 + index,
            "score": 85 - index,
            "entry_score": 45 - index,
            "entry_status": "wait_pullback",
            "entry_status_label": "等待回測",
            "pct_1d": index / 10,
            "theme": "電子",
            "reasons": ["近 20 日強於大盤"],
            "invalidations": [f"跌破 MA20 {90 + index}.0"],
        }
        for index in range(1, 5)
    )
    return {
        "updated_at": "2026-06-03 13:45:00",
        "report_date": "2026-06-03",
        "market_data_date": "2026-06-02",
        "mode": "PRE",
        "market": {
            "tw_index": {"price": "20000", "pct": "+0.50", "turnover": "3000億"},
            "forex": {"rate": "31.500"},
        },
        "us_context": [{"symbol": "SOXX", "pct_1d": 1.2}],
        "tw_candidates": candidates,
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
        "performance_summary": {
            "count": 10,
            "avg_return_pct": 1.2,
            "win_rate": 0.6,
            "top5_hit_rate": 0.7,
        },
        "strategy_optimization": {
            "posture": "defensive",
            "headline": "短線有效但延長持有轉弱",
            "primary_action": "降低追價與隔日續抱比例",
        },
    }


def test_market_report_contains_mobile_sections_and_utf8_text() -> None:
    text = format_market_report(_snapshot())
    assert text.startswith("🌅 台股盤前策略｜06/03")
    assert "📊 台股｜06/02 收盤\n20,000｜+0.50%｜震盪偏中性\n成交 3,000 億" in text
    assert "🧭 專業判讀" in text
    assert "🔥 族群排序\n1. 半導體｜強度 88.0｜2330 台積電" in text
    assert "🎯 今日行動分層" in text
    assert "1. 2330 台積電｜半導體｜1,050" in text
    assert "綜合 90.0 🟢｜可分批布局" in text
    assert "品質 86｜估值 74｜時機 38" in text
    assert "事件風險 中｜優質回檔觀察" in text
    assert "基本面：最新月營收年增" in text
    assert "建議：公司與估值條件較佳" in text
    assert "風控：跌破MA20 1000.0" in text
    assert "5. 2304 測試股4" in text
    assert "中小型觀察" not in text
    assert "🎯 今日執行計畫｜防守" in text
    assert "• 開高：反彈不追；先確認大盤止穩" in text
    assert "⚠️ 僅供資料參考，非投資建議。" in text
    assert "⚠️ 資料提醒" not in text
    assert "\n\n" in text
    assert " / " not in text
    assert max(len(line) for line in text.splitlines()) <= 36

    for removed_detail in [
        "信心",
        "失效",
        "分數",
        "市值",
        "均值",
        "新聞提示",
        "近期訊號",
        "開盤劇本",
        "策略自檢",
        "USDTWD",
    ]:
        assert removed_detail not in text


def test_market_report_always_lists_top_five_stocks() -> None:
    snapshot = _snapshot()
    snapshot["tw_candidates"] = [
        {"code": str(1000 + index), "name": f"測試股{index}", "pct_1d": index}
        for index in range(1, 7)
    ]

    text = format_market_report(snapshot)

    assert "1001 測試股1" in text
    assert "1005 測試股5" in text
    assert "1006 測試股6" not in text


def test_post_market_report_uses_next_day_labels() -> None:
    snapshot = _snapshot()
    snapshot["mode"] = "POST"

    text = format_market_report(snapshot)

    assert text.startswith("🌙 台股盤後策略｜06/03")
    assert "🎯 今日行動分層" in text
    assert "🎯 明日執行計畫｜防守" in text


def test_market_report_discloses_last_valid_snapshot_fallback() -> None:
    snapshot = _snapshot()
    snapshot["candidate_provenance"] = {
        "mode": "last_valid_snapshot",
        "as_of": "2026-06-02",
    }

    text = format_market_report(snapshot)

    assert "名單：沿用 06/02 最近有效快照" in text
    assert "尚未形成明確主軸" not in text
    assert "今日沒有明確焦點股" not in text


def test_dashboard_link_is_appended_once() -> None:
    message = "測試訊息"
    once = _with_dashboard_link(message)
    twice = _with_dashboard_link(once)
    assert once == twice
    assert "🔗 完整分析\n" in once
    assert once.count("https://taiwan-stock-ai-pi.vercel.app/") == 1


def test_market_report_flags_fallback_and_stale_data_without_internal_cache_keys() -> None:
    snapshot = _snapshot()
    snapshot["market_data_date"] = "2026-06-03"
    snapshot["data_status"] = {
        "twse_institutional": {
            "ok": True,
            "cached": False,
            "fallback_used": True,
            "trading_date": "2026-06-02",
            "stale_reason": "primary_openapi_failed",
        },
        "twse_institutional_bfi82u_20260602": {
            "ok": True,
            "cached": True,
            "fallback_used": True,
            "trading_date": "2026-06-02",
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

    assert "⚠️ 資料提醒" in text
    assert "法人使用 06/02 備援資料" in text
    assert "融資券暫時無法更新" in text
    assert "source_failed_no_cache" not in text
    assert "bfi82u" not in text


def test_market_report_does_not_call_current_fresh_cache_a_fallback() -> None:
    snapshot = _snapshot()
    snapshot["market_data_date"] = "2026-06-03"
    snapshot["data_status"] = {
        "yahoo_^TWII_1d_2d": {
            "ok": True,
            "cached": True,
            "fallback_used": False,
            "trading_date": "2026-06-03",
            "stale_reason": None,
        }
    }

    text = format_market_report(snapshot)

    assert "⚠️ 資料提醒" not in text
    assert "大盤指數使用備援資料" not in text


def test_intraday_alert_preserves_daily_entry_context() -> None:
    text = format_intraday_alert(
        {
            "code": "1301",
            "name": "台塑",
            "status": "UP",
            "price": 47.95,
            "pct": 2.5,
            "rsi": 55.0,
            "vol_ratio": 2.1,
            "entry_status": "early_watch",
            "entry_status_label": "提前觀察",
            "entry_score": 56.8,
        }
    )

    assert "提前雷達轉強確認" in text
    assert "日線: 提前觀察 / 進場 56.8" in text
    assert "尚非正式進場訊號" in text
