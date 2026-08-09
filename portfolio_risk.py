from __future__ import annotations

import os
from collections import defaultdict
from typing import Any


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def build_portfolio_risk(
    snapshot: dict[str, Any],
    *,
    previous_snapshot: dict[str, Any] | None = None,
    performance_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_items = (
        snapshot.get("actionable_candidates", [])
        if "actionable_candidates" in snapshot
        else snapshot.get("tw_candidates", [])
    )
    candidates = [
        item
        for item in candidate_items
        if item.get("code") and item.get("candidate_channel", "primary") == "primary"
    ]
    limits = {
        "max_name_weight": _env_float("RISK_MAX_NAME_WEIGHT", 0.20),
        "max_theme_weight": _env_float("RISK_MAX_THEME_WEIGHT", 0.35),
        "max_industry_weight": _env_float("RISK_MAX_INDUSTRY_WEIGHT", 0.35),
        "max_turnover": _env_float("RISK_MAX_ONE_WAY_TURNOVER", 0.60),
        "max_adv_participation": _env_float("RISK_MAX_ADV_PARTICIPATION", 0.02),
        "max_drawdown_pct": _env_float("RISK_MAX_DRAWDOWN_PCT", -15.0),
    }
    portfolio_value = max(0.0, _env_float("RISK_ASSUMED_PORTFOLIO_TWD", 1_000_000.0))
    if not candidates:
        return {
            "status": "no_candidates",
            "portfolio_value_twd": portfolio_value,
            "allocation_method": "equal_weight_primary_candidates",
            "limits": limits,
            "breaches": [],
        }

    weight = 1.0 / len(candidates)
    weights = {str(item["code"]): weight for item in candidates}
    theme_weights: dict[str, float] = defaultdict(float)
    industry_weights: dict[str, float] = defaultdict(float)
    liquidity: list[dict[str, Any]] = []
    breaches: list[str] = []

    for item in candidates:
        code = str(item["code"])
        theme = str(item.get("theme") or "未分類")
        industry = str(item.get("industry") or item.get("industry_group") or theme)
        theme_weights[theme] += weight
        industry_weights[industry] += weight
        turnover_million = _as_float(item.get("avg_turnover_million"))
        position_value = portfolio_value * weight
        participation = None
        if turnover_million and turnover_million > 0:
            participation = position_value / (turnover_million * 1_000_000.0)
            if participation > limits["max_adv_participation"]:
                breaches.append(f"{code} 預估部位超過日均成交值參與上限")
        else:
            breaches.append(f"{code} 缺少 20 日均成交值")
        liquidity.append(
            {
                "code": code,
                "weight": round(weight, 4),
                "position_value_twd": round(position_value),
                "avg_turnover_million": turnover_million,
                "adv_participation": None if participation is None else round(participation, 6),
            }
        )

    max_name_weight = max(weights.values())
    max_theme = max(theme_weights.items(), key=lambda item: item[1])
    max_industry = max(industry_weights.items(), key=lambda item: item[1])
    if max_name_weight > limits["max_name_weight"]:
        breaches.append("單一個股權重超過上限")
    if max_theme[1] > limits["max_theme_weight"]:
        breaches.append(f"主題集中度過高: {max_theme[0]}")
    if max_industry[1] > limits["max_industry_weight"]:
        breaches.append(f"產業集中度過高: {max_industry[0]}")

    turnover = _one_way_turnover(weights, previous_snapshot)
    if turnover is not None and turnover > limits["max_turnover"]:
        breaches.append("名單單向換手率超過上限")

    performance_summary = performance_summary or {}
    max_drawdown = _as_float(performance_summary.get("max_drawdown_pct"))
    if max_drawdown is not None and max_drawdown < limits["max_drawdown_pct"]:
        breaches.append("正式資金曲線最大回撤超過限制")

    return {
        "status": "breach" if breaches else "within_limits",
        "portfolio_value_twd": portfolio_value,
        "allocation_method": "equal_weight_primary_candidates",
        "candidate_count": len(candidates),
        "max_name_weight": round(max_name_weight, 4),
        "theme_weights": {key: round(value, 4) for key, value in sorted(theme_weights.items())},
        "industry_weights": {key: round(value, 4) for key, value in sorted(industry_weights.items())},
        "max_theme": {"name": max_theme[0], "weight": round(max_theme[1], 4)},
        "max_industry": {"name": max_industry[0], "weight": round(max_industry[1], 4)},
        "one_way_turnover": None if turnover is None else round(turnover, 4),
        "liquidity": liquidity,
        "historical_max_drawdown_pct": max_drawdown,
        "limits": limits,
        "breaches": list(dict.fromkeys(breaches)),
    }


def build_research_governance(
    model_report: dict[str, Any],
    performance_summary: dict[str, Any],
) -> dict[str, Any]:
    minimum_dates = int(os.getenv("RESEARCH_MIN_SIGNAL_DATES", "60"))
    signal_dates = int(performance_summary.get("signal_dates") or 0)
    blockers: list[str] = []
    if signal_dates < minimum_dates:
        blockers.append(f"正式訊號日期 {signal_dates}/{minimum_dates}")
    if model_report.get("status") != "research_ready":
        blockers.append("walk-forward 模型尚未達研究門檻")
    if model_report.get("ready_for_selection"):
        blockers.append("模型不得自動切換正式選股")
    return {
        "status": "blocked_from_promotion" if blockers else "human_review_required",
        "strategy_version_required_for_change": True,
        "single_fixed_baseline": True,
        "automatic_hyperparameter_search": False,
        "pbo_estimate": None,
        "pbo_note": "單一固定基線不宣稱 PBO；累積多策略試驗登錄後才能估計",
        "blockers": blockers,
    }


def _one_way_turnover(
    current_weights: dict[str, float],
    previous_snapshot: dict[str, Any] | None,
) -> float | None:
    if not previous_snapshot:
        return None
    previous_items = (
        previous_snapshot.get("actionable_candidates", [])
        if "actionable_candidates" in previous_snapshot
        else previous_snapshot.get("tw_candidates", [])
    )
    previous_candidates = [
        item
        for item in previous_items
        if item.get("code") and item.get("candidate_channel", "primary") == "primary"
    ]
    if not previous_candidates:
        return None
    previous_weight = 1.0 / len(previous_candidates)
    previous_weights = {str(item["code"]): previous_weight for item in previous_candidates}
    codes = set(current_weights) | set(previous_weights)
    return 0.5 * sum(
        abs(current_weights.get(code, 0.0) - previous_weights.get(code, 0.0))
        for code in codes
    )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
