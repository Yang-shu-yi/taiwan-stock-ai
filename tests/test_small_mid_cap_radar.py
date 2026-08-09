from small_mid_cap_radar import promote_small_mid_candidates, score_small_mid_candidate


def test_score_small_mid_candidate_prefers_liquid_reasonable_valuation() -> None:
    metrics = {
        "price": 120.0,
        "ma20": 110.0,
        "ma60": 100.0,
        "rsi": 62.0,
        "pct_20d": 8.0,
        "vol_ratio": 1.4,
        "avg_turnover_million": 180.0,
        "volatility20": 2.5,
    }
    fundamentals = {
        "market_cap_billion": 45.0,
        "trailing_pe": 16.0,
        "price_to_book": 2.1,
        "dividend_yield_pct": 3.0,
        "missing": False,
    }

    result = score_small_mid_candidate(metrics, fundamentals, news_hits=1)

    assert result["excluded"] is False
    assert result["score"] >= 70
    assert result["quality_score"] >= 70
    assert result["valuation_score"] >= 70


def test_score_small_mid_candidate_excludes_illiquid_stock() -> None:
    metrics = {
        "price": 80.0,
        "ma20": 78.0,
        "ma60": 75.0,
        "rsi": 55.0,
        "pct_20d": 4.0,
        "vol_ratio": 1.1,
        "avg_turnover_million": 8.0,
        "volatility20": 2.0,
    }
    fundamentals = {
        "market_cap_billion": 12.0,
        "trailing_pe": 14.0,
        "price_to_book": 1.8,
        "dividend_yield_pct": 4.0,
        "missing": False,
    }

    result = score_small_mid_candidate(metrics, fundamentals)

    assert result["excluded"] is True
    assert "成交值不足" in result["excluded_reasons"]


def test_shadow_mode_never_promotes_small_mid_candidates(monkeypatch) -> None:
    monkeypatch.setenv("SMALL_MID_SHADOW_MODE", "true")
    current = [{"code": "2330", "score": 90}]
    radar = [
        {"code": "6274", "score": 82, "small_mid_score": 82},
        {"code": "2330", "score": 80, "small_mid_score": 80},
        {"code": "4906", "score": 60, "small_mid_score": 60},
    ]

    result = promote_small_mid_candidates(current, radar)

    assert [item["code"] for item in result] == ["2330"]
