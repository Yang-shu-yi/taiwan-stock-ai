import numpy as np
import pandas as pd

import candidate_selector
import stock_analyzer
from strategy_contract import FEATURE_VERSION
from strategy_features import (
    build_model_feature_vector,
    extract_market_features,
    score_canonical_features,
)


def test_selector_and_analyzer_use_same_canonical_scorer() -> None:
    assert candidate_selector.score_canonical_features is score_canonical_features
    assert stock_analyzer.score_canonical_features is score_canonical_features


def test_canonical_features_and_score_have_versioned_bounded_contract() -> None:
    dates = pd.date_range("2025-01-01", periods=140, freq="B")
    close = np.linspace(100.0, 135.0, len(dates))
    history = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, len(dates)),
        },
        index=dates,
    )
    benchmark = history.assign(Close=np.linspace(100.0, 110.0, len(dates)))

    features = extract_market_features(history, benchmark)
    assert features is not None
    result = score_canonical_features(features, {"yoy_pct": 10.0})
    vector = build_model_feature_vector(features, {"yoy_pct": 10.0})

    assert result["feature_version"] == FEATURE_VERSION
    assert 0 <= result["score"] <= 100
    assert set(result["components"]) == {
        "trend",
        "momentum",
        "relative_strength",
        "liquidity",
        "fundamental",
    }
    assert vector["revenue_yoy_pct"] == 10.0
    assert features["rs_20d"] > 0
    assert features["rs_5d"] > 0
    assert features["ma20_slope_5d_pct"] > 0
    assert isinstance(features["ma20_reclaimed_3d"], bool)
    assert isinstance(features["rsi_crossed_50_3d"], bool)
    assert isinstance(features["macd_crossed_positive_3d"], bool)
