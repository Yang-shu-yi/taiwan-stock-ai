from __future__ import annotations

import math
from typing import Any


EARLY_WATCH_STATUS = "early_watch"
SCALE_IN_STATUS = "scale_in"
WAIT_PULLBACK_STATUS = "wait_pullback"
OVEREXTENDED_STATUS = "overextended"

ENTRY_STATUS_LABELS = {
    EARLY_WATCH_STATUS: "提前觀察",
    SCALE_IN_STATUS: "可分批布局",
    WAIT_PULLBACK_STATUS: "等待回測",
    OVEREXTENDED_STATUS: "過度延伸、不追",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(value, upper))


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    number = _number(value)
    return bool(number) if number is not None else False


def _distance_score(distance: float | None) -> float:
    if distance is None:
        return 50.0
    if distance < -5.0:
        return 10.0
    if distance < -1.0:
        return 35.0
    if distance < 0.0:
        return 70.0
    if distance <= 2.5:
        return 100.0
    if distance <= 5.0:
        return 80.0
    if distance <= 8.0:
        return 55.0
    if distance <= 12.0:
        return 25.0
    return 0.0


def _atr_extension_score(extension_atr: float | None) -> float:
    if extension_atr is None:
        return 50.0
    if extension_atr < -2.0:
        return 15.0
    if extension_atr < 0.0:
        return 60.0
    if extension_atr <= 1.5:
        return 100.0
    if extension_atr <= 2.5:
        return 70.0
    if extension_atr <= 3.5:
        return 35.0
    return 0.0


def _short_momentum_score(pct_5d: float | None) -> float:
    if pct_5d is None:
        return 50.0
    if pct_5d < -8.0:
        return 10.0
    if pct_5d < -3.0:
        return 35.0
    if pct_5d < 2.0:
        return 80.0
    if pct_5d <= 8.0:
        return 100.0
    if pct_5d <= 12.0:
        return 65.0
    if pct_5d <= 18.0:
        return 30.0
    return 0.0


def _medium_momentum_score(pct_20d: float | None) -> float:
    if pct_20d is None:
        return 50.0
    if pct_20d < -15.0:
        return 10.0
    if pct_20d < -3.0:
        return 35.0
    if pct_20d < 5.0:
        return 75.0
    if pct_20d <= 15.0:
        return 100.0
    if pct_20d <= 22.0:
        return 65.0
    if pct_20d <= 30.0:
        return 30.0
    return 0.0


def _rsi_score(rsi: float | None) -> float:
    if rsi is None:
        return 50.0
    if rsi < 35.0:
        return 20.0
    if rsi < 45.0:
        return 50.0
    if rsi <= 62.0:
        return 100.0
    if rsi <= 68.0:
        return 80.0
    if rsi <= 75.0:
        return 50.0
    if rsi <= 80.0:
        return 20.0
    return 0.0


def _volume_score(vol_ratio: float | None) -> float:
    if vol_ratio is None:
        return 50.0
    if vol_ratio < 0.5:
        return 20.0
    if vol_ratio < 0.8:
        return 55.0
    if vol_ratio <= 1.8:
        return 100.0
    if vol_ratio <= 2.5:
        return 75.0
    if vol_ratio <= 3.5:
        return 45.0
    return 25.0


def _stop_distance_score(stop_distance_pct: float | None) -> float:
    if stop_distance_pct is None:
        return 50.0
    if stop_distance_pct <= 4.0:
        return 100.0
    if stop_distance_pct <= 6.0:
        return 80.0
    if stop_distance_pct <= 8.0:
        return 60.0
    if stop_distance_pct <= 10.0:
        return 35.0
    return 0.0


def _reward_risk_score(reward_risk_ratio: float | None) -> float:
    if reward_risk_ratio is None:
        return 50.0
    if reward_risk_ratio >= 2.2:
        return 100.0
    if reward_risk_ratio >= 1.5:
        return 75.0
    if reward_risk_ratio >= 1.0:
        return 45.0
    return 15.0


def _early_watch_assessment(
    features: dict[str, Any],
    trend_score: float,
) -> tuple[float, bool, list[str]]:
    distance = _number(features.get("distance_to_ma20"))
    rsi = _number(features.get("rsi14") or features.get("rsi"))
    macd_delta = _number(features.get("macd_hist_delta_3d_pct"))
    rs_5d = _number(features.get("rs_5d"))
    rs_acceleration = _number(features.get("rs_acceleration"))
    vol_ratio = _number(features.get("vol_ratio"))
    pct_5d = _number(features.get("pct_5d"))
    ma20_slope = _number(features.get("ma20_slope_5d_pct"))

    reclaimed_ma20 = _flag(features.get("ma20_reclaimed_3d"))
    rsi_crossed_50 = _flag(features.get("rsi_crossed_50_3d"))
    macd_crossed_positive = _flag(features.get("macd_crossed_positive_3d"))

    score = 0.0
    reasons: list[str] = []
    transitions = 0

    if distance is not None and -1.0 <= distance <= 4.0:
        score += 25.0
        reasons.append(f"價格貼近 MA20（{distance:+.1f}%）")
    elif distance is not None and 4.0 < distance <= 6.0:
        score += 10.0

    if reclaimed_ma20:
        score += 20.0
        transitions += 1
        reasons.append("近 3 日剛站回 MA20")
    elif distance is not None and distance >= 0 and (ma20_slope or 0.0) > 0:
        score += 10.0
        reasons.append("MA20 斜率轉正")

    if rsi_crossed_50:
        score += 15.0
        transitions += 1
        reasons.append("RSI 近 3 日穿越 50")
    elif rsi is not None and 48.0 <= rsi <= 62.0:
        score += 10.0

    if macd_crossed_positive:
        score += 15.0
        transitions += 1
        reasons.append("MACD 柱體翻正")
    elif macd_delta is not None and macd_delta > 0:
        score += 10.0
        transitions += 1
        reasons.append("MACD 柱體連續改善")

    if rs_5d is not None and rs_5d > 0:
        score += 10.0
        reasons.append("近 5 日開始強於大盤")
    if rs_acceleration is not None and rs_acceleration > 0:
        score += 5.0
        reasons.append("相對強弱正在加速")

    if vol_ratio is not None and 0.7 <= vol_ratio <= 1.8:
        score += 10.0
    elif vol_ratio is not None and 1.8 < vol_ratio <= 2.5:
        score += 5.0
    if pct_5d is not None and -2.0 <= pct_5d <= 8.0:
        score += 5.0
    if 45.0 <= trend_score <= 75.0:
        score += 5.0

    score = _clamp(score)
    qualified = bool(
        score >= 60.0
        and transitions >= 1
        and distance is not None
        and -1.0 <= distance <= 6.0
        and (rsi is None or rsi <= 68.0)
        and (pct_5d is None or pct_5d <= 10.0)
    )
    return round(score, 2), qualified, reasons[:4]


def _entry_plan(features: dict[str, Any]) -> dict[str, Any]:
    price = _number(features.get("price"))
    ma20 = _number(features.get("ma20"))
    ma60 = _number(features.get("ma60"))
    recent_low_20 = _number(features.get("recent_low_20"))
    recent_high_20 = _number(features.get("recent_high_20"))
    recent_high_60 = _number(features.get("recent_high_60"))
    atr = _number(features.get("atr14"))

    if price is None or price <= 0:
        return {
            "support_price": None,
            "stop_price": None,
            "stop_distance_pct": None,
            "target_price": None,
            "target_method": "資料不足",
            "reward_risk_ratio": None,
        }

    supports = [
        value
        for value in (ma20, ma60, recent_low_20)
        if value is not None and 0 < value < price
    ]
    support = max(supports) if supports else None
    stop = None
    if support is not None:
        stop = support - (atr or 0.0) * 0.35
        if stop <= 0 or stop >= price:
            stop = support * 0.99
    stop_distance_pct = (
        None if stop is None else max(0.0, (price - stop) / price * 100.0)
    )

    minimum_target_gap = (atr or price * 0.02) * 0.5
    resistances = sorted(
        {
            value
            for value in (recent_high_20, recent_high_60)
            if value is not None and value > price + minimum_target_gap
        }
    )
    if resistances:
        target = resistances[0]
        target_method = "前波壓力"
    elif atr is not None and atr > 0:
        target = price + atr * 2.0
        target_method = "2ATR 風險評估目標"
    else:
        target = None
        target_method = "缺少可量化壓力"

    reward_risk_ratio = None
    if target is not None and stop is not None and price > stop:
        reward_risk_ratio = max(0.0, (target - price) / (price - stop))

    return {
        "support_price": None if support is None else round(support, 2),
        "stop_price": None if stop is None else round(stop, 2),
        "stop_distance_pct": (
            None if stop_distance_pct is None else round(stop_distance_pct, 2)
        ),
        "target_price": None if target is None else round(target, 2),
        "target_method": target_method,
        "reward_risk_ratio": (
            None if reward_risk_ratio is None else round(reward_risk_ratio, 2)
        ),
    }


def evaluate_entry_opportunity(
    features: dict[str, Any],
    trend_score: float | int | None,
) -> dict[str, Any]:
    """Separate trend confirmation from whether a new entry is still executable."""
    trend = _number(trend_score) or 0.0
    price = _number(features.get("price"))
    ma20 = _number(features.get("ma20"))
    ma60 = _number(features.get("ma60"))
    distance = _number(features.get("distance_to_ma20"))
    atr = _number(features.get("atr14"))
    pct_5d = _number(features.get("pct_5d"))
    pct_20d = _number(features.get("pct_20d"))
    rsi = _number(features.get("rsi14") or features.get("rsi"))
    vol_ratio = _number(features.get("vol_ratio"))

    extension_atr = None
    if price is not None and ma20 is not None and atr is not None and atr > 0:
        extension_atr = (price - ma20) / atr

    extension_score = (
        _distance_score(distance) * 0.55
        + _atr_extension_score(extension_atr) * 0.45
    )
    freshness_score = (
        _short_momentum_score(pct_5d) * 0.40
        + _medium_momentum_score(pct_20d) * 0.35
        + _rsi_score(rsi) * 0.25
    )

    structure_score = 0.0
    if price is not None and ma20 is not None and price >= ma20:
        structure_score += 40.0
    if price is not None and ma60 is not None and price >= ma60:
        structure_score += 25.0
    if ma20 is not None and ma60 is not None and ma20 >= ma60:
        structure_score += 20.0
    if trend >= 60.0:
        structure_score += 15.0

    plan = _entry_plan(features)
    stop_distance = _number(plan.get("stop_distance_pct"))
    reward_risk = _number(plan.get("reward_risk_ratio"))
    risk_reward_score = (
        _stop_distance_score(stop_distance) * 0.35
        + _reward_risk_score(reward_risk) * 0.65
    )
    volume_score = _volume_score(vol_ratio)

    raw_score = (
        extension_score * 0.25
        + freshness_score * 0.20
        + risk_reward_score * 0.25
        + volume_score * 0.10
        + structure_score * 0.20
    )

    penalty = 1.0
    if pct_20d is not None and pct_20d >= 25.0:
        penalty *= 0.55
    elif pct_20d is not None and pct_20d >= 20.0:
        penalty *= 0.75
    if pct_5d is not None and pct_5d >= 18.0:
        penalty *= 0.45
    elif pct_5d is not None and pct_5d >= 12.0:
        penalty *= 0.70
    if distance is not None and distance >= 12.0:
        penalty *= 0.55
    elif distance is not None and distance > 6.0:
        penalty *= 0.90
    if reward_risk is not None and reward_risk < 1.0:
        penalty *= 0.80
    elif reward_risk is not None and reward_risk < 1.5:
        penalty *= 0.90
    if price is not None and ma60 is not None and price < ma60:
        penalty *= 0.80
    if trend < 60.0:
        penalty *= 0.85

    entry_score = round(_clamp(raw_score * penalty), 2)
    early_score, early_qualified, early_reasons = _early_watch_assessment(
        features,
        trend,
    )

    extremely_extended = bool(
        (distance is not None and distance >= 12.0)
        or (extension_atr is not None and extension_atr >= 4.0)
        or (pct_5d is not None and pct_5d >= 18.0)
        or (pct_20d is not None and pct_20d >= 35.0)
        or (rsi is not None and rsi >= 80.0)
    )
    actionable = bool(
        entry_score >= 65.0
        and trend >= 62.0
        and price is not None
        and ma20 is not None
        and price >= ma20
        and (
            ma60 is None
            or price >= ma60
            or (ma20 is not None and ma20 >= ma60)
        )
        and (distance is None or distance <= 6.0)
        and (pct_5d is None or pct_5d <= 10.0)
        and (pct_20d is None or pct_20d <= 20.0)
        and (rsi is None or rsi <= 72.0)
        and (stop_distance is None or stop_distance <= 8.0)
        and (reward_risk is None or reward_risk >= 1.5)
    )

    if extremely_extended:
        status = OVEREXTENDED_STATUS
        action = "漲幅與均線乖離過大，不追價，等待風險重新收斂。"
    elif actionable:
        status = SCALE_IN_STATUS
        action = "風險報酬仍可控，可依規劃停損小量分批，不一次押滿。"
    elif early_qualified and trend < 68.0:
        status = EARLY_WATCH_STATUS
        action = "轉強條件開始形成，先觀察量價確認，尚未列為正式進場訊號。"
    else:
        status = WAIT_PULLBACK_STATUS
        action = "已發動或條件尚未完整，等待回測支撐，不宜追價。"

    entry_reasons: list[str] = []
    entry_risks: list[str] = []
    if distance is not None:
        entry_reasons.append(f"距 MA20 {distance:+.1f}%")
    if extension_atr is not None:
        entry_reasons.append(f"MA20 乖離 {extension_atr:.1f} ATR")
    if reward_risk is not None:
        entry_reasons.append(f"估算風險報酬 {reward_risk:.1f}")
    if stop_distance is not None:
        entry_reasons.append(f"停損距離 {stop_distance:.1f}%")

    if distance is not None and distance > 6.0:
        entry_risks.append("距 MA20 偏遠，追價緩衝不足")
    if pct_5d is not None and pct_5d > 10.0:
        entry_risks.append("近 5 日漲幅偏大")
    if pct_20d is not None and pct_20d > 20.0:
        entry_risks.append("近 20 日漲幅偏大")
    if reward_risk is not None and reward_risk < 1.5:
        entry_risks.append("上檔空間相對停損風險不足")
    if stop_distance is not None and stop_distance > 8.0:
        entry_risks.append("合理停損距離過遠")

    plan["extension_atr"] = (
        None if extension_atr is None else round(extension_atr, 2)
    )
    plan["distance_to_ma20_pct"] = (
        None if distance is None else round(distance, 2)
    )

    return {
        "entry_score": entry_score,
        "entry_status": status,
        "entry_status_label": ENTRY_STATUS_LABELS[status],
        "entry_action": action,
        "entry_reasons": entry_reasons[:4],
        "entry_risk_flags": entry_risks[:4],
        "entry_plan": plan,
        "entry_components": {
            "extension": round(extension_score, 2),
            "momentum_freshness": round(freshness_score, 2),
            "risk_reward": round(risk_reward_score, 2),
            "volume": round(volume_score, 2),
            "structure": round(structure_score, 2),
        },
        "early_watch_score": early_score,
        "early_watch_qualified": early_qualified,
        "early_watch_reasons": early_reasons,
    }
