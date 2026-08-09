from entry_opportunity import (
    EARLY_WATCH_STATUS,
    OVEREXTENDED_STATUS,
    SCALE_IN_STATUS,
    WAIT_PULLBACK_STATUS,
    evaluate_entry_opportunity,
)


def _base_features() -> dict:
    return {
        "price": 100.0,
        "ma20": 98.0,
        "ma60": 95.0,
        "atr14": 2.0,
        "distance_to_ma20": 2.04,
        "pct_5d": 3.0,
        "pct_20d": 8.0,
        "rsi14": 56.0,
        "vol_ratio": 1.2,
        "recent_low_20": 94.0,
        "recent_high_20": 110.0,
        "recent_high_60": 115.0,
        "ma20_slope_5d_pct": 1.0,
        "ma20_reclaimed_3d": False,
        "rsi_crossed_50_3d": False,
        "macd_crossed_positive_3d": False,
        "macd_hist_delta_3d_pct": 0.1,
        "rs_5d": 2.0,
        "rs_20d": 5.0,
        "rs_acceleration": 0.75,
    }


def test_actionable_setup_requires_good_stop_and_reward_risk() -> None:
    result = evaluate_entry_opportunity(_base_features(), 78)

    assert result["entry_status"] == SCALE_IN_STATUS
    assert result["entry_score"] >= 65
    assert result["entry_plan"]["stop_distance_pct"] <= 8
    assert result["entry_plan"]["reward_risk_ratio"] >= 1.5


def test_formosa_plastics_late_snapshot_is_wait_pullback_not_high_confidence() -> None:
    features = {
        **_base_features(),
        "price": 63.0,
        "ma20": 58.75,
        "ma60": 51.57,
        "atr14": 3.0,
        "distance_to_ma20": 7.23,
        "pct_5d": -0.94,
        "pct_20d": 27.14,
        "rsi14": 60.05,
        "vol_ratio": 0.77,
        "recent_low_20": 54.8,
        "recent_high_20": 65.7,
        "recent_high_60": 65.7,
        "ma20_reclaimed_3d": False,
        "rsi_crossed_50_3d": False,
        "macd_crossed_positive_3d": False,
    }

    result = evaluate_entry_opportunity(features, 85)

    assert result["entry_status"] == WAIT_PULLBACK_STATUS
    assert result["entry_score"] <= 35
    assert "不宜追價" in result["entry_action"]


def test_extreme_short_term_extension_is_explicitly_no_chase() -> None:
    features = {
        **_base_features(),
        "price": 58.0,
        "ma20": 48.9,
        "ma60": 48.85,
        "atr14": 2.4,
        "distance_to_ma20": 18.6,
        "pct_5d": 20.96,
        "pct_20d": 27.61,
        "rsi14": 69.27,
        "vol_ratio": 2.84,
        "recent_high_20": 54.5,
        "recent_high_60": 54.5,
    }

    result = evaluate_entry_opportunity(features, 88)

    assert result["entry_status"] == OVEREXTENDED_STATUS
    assert result["entry_score"] < 30


def test_turning_point_enters_early_radar_before_full_trend_confirmation() -> None:
    features = {
        **_base_features(),
        "price": 47.25,
        "ma20": 46.73,
        "ma60": 48.27,
        "atr14": 1.5,
        "distance_to_ma20": 1.12,
        "pct_5d": 3.05,
        "pct_20d": 2.94,
        "rsi14": 50.07,
        "vol_ratio": 1.19,
        "recent_low_20": 43.8,
        "recent_high_20": 52.0,
        "recent_high_60": 52.0,
        "ma20_reclaimed_3d": True,
        "rsi_crossed_50_3d": True,
        "macd_crossed_positive_3d": False,
        "macd_hist_delta_3d_pct": 0.35,
        "rs_5d": 1.5,
        "rs_20d": -8.0,
        "rs_acceleration": 3.5,
    }

    result = evaluate_entry_opportunity(features, 54)

    assert result["early_watch_qualified"] is True
    assert result["early_watch_score"] >= 60
    assert result["entry_status"] == EARLY_WATCH_STATUS
    assert any("MA20" in reason for reason in result["early_watch_reasons"])
