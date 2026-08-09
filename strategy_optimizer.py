from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from strategy_contract import (
    LIVE_ENVIRONMENT,
    PERFORMANCE_SCHEMA_VERSION,
    PRIMARY_CHANNEL,
    STRATEGY_VERSION,
)


DEFAULT_PERFORMANCE_FILE = "signal_performance.jsonl"


def build_strategy_optimization(
    performance_path: str | Path = DEFAULT_PERFORMANCE_FILE,
    *,
    lookback: int = 240,
    min_group_count: int = 8,
    min_signal_dates: int | None = None,
) -> dict[str, Any]:
    min_signal_dates = min_signal_dates or int(os.getenv("OPTIMIZER_MIN_SIGNAL_DATES", "20"))
    primary_horizon = int(os.getenv("PERFORMANCE_PRIMARY_HORIZON", "5"))
    rows = [
        row
        for row in _read_jsonl(performance_path)
        if row.get("schema_version") == PERFORMANCE_SCHEMA_VERSION
        and row.get("execution_environment") == LIVE_ENVIRONMENT
        and row.get("candidate_channel") == PRIMARY_CHANNEL
        and row.get("strategy_version") == STRATEGY_VERSION
        and int(row.get("horizon") or -1) == primary_horizon
        and row.get("net_return_pct") is not None
    ]
    rows.sort(key=lambda row: (str(row.get("entry_date") or row.get("date") or ""), str(row.get("signal_id") or "")))
    usable = rows[-lookback:]
    signal_dates = len({str(row.get("entry_date") or row.get("date")) for row in usable})
    base = {
        "generated_at": _now(),
        "strategy_version": STRATEGY_VERSION,
        "candidate_channel": PRIMARY_CHANNEL,
        "primary_horizon": primary_horizon,
        "signal_dates": signal_dates,
        "minimum_signal_dates": min_signal_dates,
        "shadow_radar_affects_primary": False,
        "automatic_parameter_changes": False,
    }
    if not usable or signal_dates < min_signal_dates:
        return {
            **base,
            "status": "collecting",
            "posture": "normal",
            "headline": f"正式樣本仍在累積（{signal_dates}/{min_signal_dates} 個訊號日）",
            "primary_action": "維持固定版本與 shadow 記錄，不依小樣本調參",
            "recommendations": [],
            "parameter_hints": {"SMALL_MID_SHADOW_MODE": True},
            "groups": {},
        }

    overall = _stats(usable)
    by_theme = _group_stats(usable, "theme", min_group_count)
    recommendations = _recommendations(overall, by_theme)
    posture = "defensive" if _should_use_defensive_posture(overall) else "normal"

    return {
        **base,
        "status": "evidence_available",
        "posture": posture,
        "headline": _headline(overall),
        "primary_action": recommendations[0] if recommendations else "維持現有版本，繼續累積樣本",
        "recommendations": recommendations,
        "parameter_hints": {
            "SMALL_MID_SHADOW_MODE": True,
            "REQUIRES_NEW_STRATEGY_VERSION": True,
        },
        "groups": {
            "overall": overall,
            "by_theme": by_theme,
        },
    }


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    net_returns = [float(row["net_return_pct"]) for row in rows if row.get("net_return_pct") is not None]
    net_excess = [
        float(row["net_excess_return_pct"])
        for row in rows
        if row.get("net_excess_return_pct") is not None
    ]
    if not net_returns:
        return {"count": 0}
    return {
        "count": len(net_returns),
        "signal_dates": len({str(row.get("entry_date") or row.get("date")) for row in rows}),
        "net_avg_return_pct": _avg(net_returns),
        "net_excess_expectancy_pct": _avg(net_excess),
        "win_rate": round(sum(value > 0 for value in net_returns) / len(net_returns), 4),
        "excess_win_rate": None
        if not net_excess
        else round(sum(value > 0 for value in net_excess) / len(net_excess), 4),
        "worst_net_return_pct": round(min(net_returns), 2),
    }


def _group_stats(rows: list[dict[str, Any]], key: str, min_count: int) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "未分類")].append(row)
    result = {
        value: _stats(items)
        for value, items in grouped.items()
        if len(
            {str(item.get("entry_date") or item.get("date")) for item in items}
        )
        >= min_count
    }
    return dict(
        sorted(
            result.items(),
            key=lambda item: item[1].get("net_excess_expectancy_pct")
            if item[1].get("net_excess_expectancy_pct") is not None
            else -999.0,
            reverse=True,
        )
    )


def _recommendations(
    overall: dict[str, Any],
    by_theme: dict[str, dict[str, Any]],
) -> list[str]:
    recommendations: list[str] = []
    expectancy = overall.get("net_excess_expectancy_pct")
    if expectancy is not None and expectancy < 0:
        recommendations.append("扣成本後超額期望報酬為負，先降低總曝險並凍結擴張名單")
    if (overall.get("worst_net_return_pct") or 0) < -8:
        recommendations.append("尾端虧損偏大，下一版本應加入單股與投組停損/曝險限制")

    weak_themes = [
        theme
        for theme, stats in by_theme.items()
        if stats.get("count", 0) >= 8
        and (stats.get("net_excess_expectancy_pct") or 0) < 0
    ][:3]
    if weak_themes:
        recommendations.append("下版研究候選的弱勢主題: " + "、".join(weak_themes))
    return recommendations[:3]


def _should_use_defensive_posture(overall: dict[str, Any]) -> bool:
    return bool(
        (overall.get("net_excess_expectancy_pct") or 0) < 0
        and (overall.get("excess_win_rate") or 0) < 0.45
    )


def _headline(overall: dict[str, Any]) -> str:
    expectancy = overall.get("net_excess_expectancy_pct")
    if expectancy is None:
        return "扣成本後超額績效資料不足"
    if expectancy < 0:
        return "扣成本後超額期望報酬偏弱"
    return "扣成本後超額期望報酬為正，仍需持續驗證"


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
