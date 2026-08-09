from __future__ import annotations

import math
from typing import Any

import pandas as pd
import ta

from strategy_contract import FEATURE_VERSION


MODEL_FEATURE_NAMES = (
    "distance_to_ma20",
    "distance_to_ma60",
    "distance_to_ma120",
    "pct_5d",
    "pct_20d",
    "rs_20d",
    "rsi14",
    "macd_hist_pct",
    "vol_ratio",
    "volatility20",
    "avg_turnover_million",
    "revenue_yoy_pct",
)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    current = _finite(series.iloc[-1])
    base = _finite(series.iloc[-periods - 1])
    if current is None or base in {None, 0.0}:
        return None
    return (current / base - 1.0) * 100.0


def _distance(value: float | None, reference: float | None) -> float | None:
    if value is None or reference in {None, 0.0}:
        return None
    return (value / reference - 1.0) * 100.0


def _below(value: Any, threshold: float) -> bool:
    number = _finite(value)
    return number is not None and number < threshold


def extract_market_features(
    history: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """Return the canonical, dimensionally consistent feature schema."""
    if history is None or len(history) < 80 or "Close" not in history:
        return None

    frame = history.dropna(subset=["Close"]).copy()
    if len(frame) < 80:
        return None
    close = frame["Close"].astype("float64")
    high = frame.get("High", close).astype("float64")
    low = frame.get("Low", close).astype("float64")
    volume = frame.get("Volume", pd.Series(0.0, index=frame.index)).fillna(0).astype("float64")

    price = _finite(close.iloc[-1])
    previous = _finite(close.iloc[-2])
    ma20_series = ta.trend.sma_indicator(close, 20)
    ma60_series = ta.trend.sma_indicator(close, 60)
    ma120_series = ta.trend.sma_indicator(close, 120) if len(close) >= 120 else None
    rsi_series = ta.momentum.RSIIndicator(close, 14).rsi()
    macd_hist_series = ta.trend.MACD(close, 26, 12, 9).macd_diff()

    ma20 = _finite(ma20_series.iloc[-1])
    ma60 = _finite(ma60_series.iloc[-1])
    ma120 = _finite(ma120_series.iloc[-1]) if ma120_series is not None else None
    rsi14 = _finite(rsi_series.iloc[-1])
    macd_hist = _finite(macd_hist_series.iloc[-1])
    atr14 = _finite(
        ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range().iloc[-1]
    )
    avg_volume20 = _finite(volume.tail(20).mean()) or 0.0
    latest_volume = _finite(volume.iloc[-1]) or 0.0

    pct_1d = None
    if price is not None and previous not in {None, 0.0}:
        pct_1d = (price / previous - 1.0) * 100.0
    pct_5d = _pct_change(close, 5)
    pct_20d = _pct_change(close, 20)
    pct_60d = _pct_change(close, 60)

    benchmark_20d = None
    benchmark_60d = None
    benchmark_5d = None
    if benchmark is not None and not benchmark.empty and "Close" in benchmark:
        benchmark_close = benchmark.dropna(subset=["Close"])["Close"].astype("float64")
        benchmark_5d = _pct_change(benchmark_close, 5)
        benchmark_20d = _pct_change(benchmark_close, 20)
        benchmark_60d = _pct_change(benchmark_close, 60)

    volatility20 = _finite(close.pct_change().tail(20).std() * 100.0)
    avg_turnover_million = None
    if price is not None:
        avg_turnover_million = price * avg_volume20 / 1_000_000.0

    recent_high_20 = _finite(close.iloc[-21:-1].max()) if len(close) > 21 else price
    recent_low_20 = _finite(close.iloc[-21:-1].min()) if len(close) > 21 else price
    recent_high_60 = _finite(close.iloc[-61:-1].max()) if len(close) > 61 else price
    rs_5d = None if pct_5d is None or benchmark_5d is None else pct_5d - benchmark_5d
    rs_20d = None if pct_20d is None or benchmark_20d is None else pct_20d - benchmark_20d
    rs_60d = None if pct_60d is None or benchmark_60d is None else pct_60d - benchmark_60d

    ma20_slope_5d_pct = None
    if len(ma20_series) > 5:
        ma20_slope_5d_pct = _distance(
            _finite(ma20_series.iloc[-1]),
            _finite(ma20_series.iloc[-6]),
        )

    prior_close = close.iloc[-4:-1]
    prior_ma20 = ma20_series.iloc[-4:-1]
    prior_rsi = rsi_series.iloc[-4:-1]
    prior_macd = macd_hist_series.iloc[-4:-1]
    ma20_reclaimed_3d = bool(
        price is not None
        and ma20 is not None
        and price >= ma20
        and any(
            _finite(value) is not None
            and _finite(reference) is not None
            and float(value) <= float(reference)
            for value, reference in zip(prior_close, prior_ma20, strict=False)
        )
    )
    rsi_crossed_50_3d = bool(
        rsi14 is not None
        and rsi14 >= 50.0
        and any(_below(value, 50.0) for value in prior_rsi)
    )
    macd_crossed_positive_3d = bool(
        macd_hist is not None
        and macd_hist >= 0.0
        and any(_below(value, 0.0) for value in prior_macd)
    )
    macd_hist_delta_3d_pct = None
    if len(macd_hist_series) > 3:
        old_hist = _finite(macd_hist_series.iloc[-4])
        old_price = _finite(close.iloc[-4])
        current_hist_pct = (
            None
            if price in {None, 0.0} or macd_hist is None
            else macd_hist / price * 100.0
        )
        old_hist_pct = (
            None
            if old_price in {None, 0.0} or old_hist is None
            else old_hist / old_price * 100.0
        )
        if current_hist_pct is not None and old_hist_pct is not None:
            macd_hist_delta_3d_pct = current_hist_pct - old_hist_pct
    rs_acceleration = (
        None if rs_5d is None or rs_20d is None else rs_5d - rs_20d * 0.25
    )

    return {
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "rsi14": rsi14,
        "rsi": rsi14,
        "macd_hist": macd_hist,
        "macd_hist_pct": None if price in {None, 0.0} or macd_hist is None else macd_hist / price * 100.0,
        "atr14": atr14,
        "atr_pct": None if price in {None, 0.0} or atr14 is None else atr14 / price * 100.0,
        "pct_1d": pct_1d,
        "pct_5d": pct_5d,
        "pct_20d": pct_20d,
        "pct_60d": pct_60d,
        "benchmark_5d": benchmark_5d,
        "benchmark_20d": benchmark_20d,
        "benchmark_60d": benchmark_60d,
        "rs_5d": rs_5d,
        "rs_20d": rs_20d,
        "rs_60d": rs_60d,
        "rs_acceleration": rs_acceleration,
        "distance_to_ma20": _distance(price, ma20),
        "distance_to_ma60": _distance(price, ma60),
        "distance_to_ma120": _distance(price, ma120),
        "ma20_slope_5d_pct": ma20_slope_5d_pct,
        "ma20_reclaimed_3d": ma20_reclaimed_3d,
        "rsi_crossed_50_3d": rsi_crossed_50_3d,
        "macd_crossed_positive_3d": macd_crossed_positive_3d,
        "macd_hist_delta_3d_pct": macd_hist_delta_3d_pct,
        "breakout_gap_20": _distance(price, recent_high_20),
        "recent_high_20": recent_high_20,
        "recent_low_20": recent_low_20,
        "recent_high_60": recent_high_60,
        "vol_ratio": latest_volume / avg_volume20 if avg_volume20 else 1.0,
        "avg_turnover_million": avg_turnover_million,
        "volatility20": volatility20,
    }


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(value, upper))


def _linear(value: float | None, low: float, high: float, *, neutral: float = 50.0) -> float:
    if value is None:
        return neutral
    if high == low:
        return neutral
    return _clamp((value - low) / (high - low) * 100.0)


def score_canonical_features(
    features: dict[str, float | None],
    revenue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared selector/analyzer score. News is logged but never added to this score."""
    revenue = revenue or {}
    price = features.get("price")
    ma20 = features.get("ma20")
    ma60 = features.get("ma60")
    ma120 = features.get("ma120")

    trend_checks = [
        1.0 if price is not None and ma20 is not None and price > ma20 else 0.0,
        1.0 if price is not None and ma60 is not None and price > ma60 else 0.0,
        1.0 if ma20 is not None and ma60 is not None and ma20 > ma60 else 0.0,
    ]
    if ma120 is not None:
        trend_checks.extend(
            [
                1.0 if price is not None and price > ma120 else 0.0,
                1.0 if ma60 is not None and ma60 > ma120 else 0.0,
            ]
        )
    trend_score = sum(trend_checks) / len(trend_checks) * 100.0
    macd_hist_pct = features.get("macd_hist_pct")
    if macd_hist_pct is not None:
        trend_score = trend_score * 0.85 + _linear(macd_hist_pct, -0.6, 0.6) * 0.15

    pct_5d_score = _linear(features.get("pct_5d"), -8.0, 8.0)
    pct_20d_score = _linear(features.get("pct_20d"), -15.0, 20.0)
    rsi = features.get("rsi14")
    if rsi is None:
        rsi_score = 50.0
    elif 50.0 <= rsi <= 70.0:
        rsi_score = 80.0 + (rsi - 50.0)
    elif 40.0 <= rsi < 50.0:
        rsi_score = 50.0 + (rsi - 40.0) * 3.0
    elif 70.0 < rsi <= 78.0:
        rsi_score = 100.0 - (rsi - 70.0) * 6.25
    else:
        rsi_score = _clamp(50.0 - abs(rsi - 55.0) * 2.0)
    momentum_score = pct_5d_score * 0.30 + pct_20d_score * 0.45 + rsi_score * 0.25

    rs20 = features.get("rs_20d")
    rs60 = features.get("rs_60d")
    relative_score = (
        _linear(rs20, -12.0, 12.0) * 0.65
        + _linear(rs60, -20.0, 20.0) * 0.35
    )

    turnover = features.get("avg_turnover_million")
    if turnover is None:
        liquidity_score = 50.0
    elif turnover >= 500.0:
        liquidity_score = 100.0
    elif turnover >= 150.0:
        liquidity_score = 80.0 + (turnover - 150.0) / 350.0 * 20.0
    elif turnover >= 30.0:
        liquidity_score = 45.0 + (turnover - 30.0) / 120.0 * 35.0
    else:
        liquidity_score = _linear(turnover, 0.0, 30.0, neutral=0.0) * 0.45
    volatility = features.get("volatility20")
    if volatility is not None and volatility > 5.0:
        liquidity_score -= min((volatility - 5.0) * 5.0, 25.0)
    liquidity_score = _clamp(liquidity_score)

    revenue_yoy = _finite(revenue.get("yoy_pct"))
    revenue_mom = _finite(revenue.get("mom_pct"))
    cumulative_yoy = _finite(revenue.get("cumulative_yoy_pct"))
    fundamental_score = (
        _linear(revenue_yoy, -25.0, 35.0) * 0.55
        + _linear(cumulative_yoy, -20.0, 30.0) * 0.30
        + _linear(revenue_mom, -20.0, 20.0) * 0.15
    )

    components = {
        "trend": round(_clamp(trend_score), 2),
        "momentum": round(_clamp(momentum_score), 2),
        "relative_strength": round(_clamp(relative_score), 2),
        "liquidity": round(liquidity_score, 2),
        "fundamental": round(_clamp(fundamental_score), 2),
    }
    total = (
        components["trend"] * 0.30
        + components["momentum"] * 0.25
        + components["relative_strength"] * 0.20
        + components["liquidity"] * 0.15
        + components["fundamental"] * 0.10
    )
    return {
        "feature_version": FEATURE_VERSION,
        "score": round(_clamp(total), 2),
        "components": components,
    }


def build_model_feature_vector(
    features: dict[str, float | None],
    revenue: dict[str, Any] | None = None,
) -> dict[str, float | None]:
    revenue = revenue or {}
    merged: dict[str, float | None] = dict(features)
    merged["revenue_yoy_pct"] = _finite(revenue.get("yoy_pct"))
    return {name: _finite(merged.get(name)) for name in MODEL_FEATURE_NAMES}


def canonical_reasons(features: dict[str, float | None]) -> list[str]:
    reasons: list[str] = []
    price = features.get("price")
    ma20 = features.get("ma20")
    ma60 = features.get("ma60")
    if price is not None and ma20 is not None and ma60 is not None and price > ma20 and price > ma60:
        reasons.append("站上 MA20/MA60")
    if ma20 is not None and ma60 is not None and ma20 > ma60:
        reasons.append("均線結構偏多")
    if (features.get("rs_20d") or 0.0) > 0:
        reasons.append("近 20 日強於大盤")
    if (features.get("vol_ratio") or 0.0) >= 1.2:
        reasons.append("量能高於 20 日均量")
    if (features.get("pct_20d") or 0.0) > 0:
        reasons.append("近 20 日動能為正")
    return reasons[:4] or ["綜合特徵接近中性"]
