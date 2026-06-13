from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PERFORMANCE_FILE = "signal_performance.jsonl"


def build_strategy_optimization(
    performance_path: str | Path = DEFAULT_PERFORMANCE_FILE,
    *,
    lookback: int = 240,
    min_group_count: int = 8,
) -> dict[str, Any]:
    rows = _read_jsonl(performance_path)[-lookback:]
    usable = [row for row in rows if row.get("return_pct") is not None]
    if not usable:
        return {
            "generated_at": _now(),
            "posture": "normal",
            "headline": "尚未累積足夠訊號績效",
            "primary_action": "先維持目前策略，等待更多樣本",
            "recommendations": [],
            "parameter_hints": {},
            "groups": {},
        }

    overall = _stats(usable)
    by_source = _group_stats(usable, "source", min_group_count)
    by_theme = _group_stats(usable, "theme", min_group_count)
    by_horizon = _group_stats(usable, "horizon", min_group_count)
    recommendations = _recommendations(overall, by_source, by_theme, by_horizon)
    posture = "defensive" if _should_use_defensive_posture(overall, by_horizon) else "normal"

    return {
        "generated_at": _now(),
        "posture": posture,
        "headline": _headline(overall, by_horizon),
        "primary_action": recommendations[0] if recommendations else "維持現有策略，持續觀察",
        "recommendations": recommendations,
        "parameter_hints": _parameter_hints(posture, by_source, by_horizon),
        "groups": {
            "overall": overall,
            "by_source": by_source,
            "by_theme": by_theme,
            "by_horizon": by_horizon,
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
    returns = [float(row["return_pct"]) for row in rows if row.get("return_pct") is not None]
    excess = [float(row["excess_return_pct"]) for row in rows if row.get("excess_return_pct") is not None]
    if not returns:
        return {"count": 0}
    return {
        "count": len(returns),
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "avg_excess_return_pct": _avg(excess),
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns), 4),
        "excess_win_rate": None if not excess else round(sum(1 for value in excess if value > 0) / len(excess), 4),
        "worst_return_pct": round(min(returns), 2),
    }


def _group_stats(rows: list[dict[str, Any]], key: str, min_count: int) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = str(row.get(key, "未分類"))
        grouped[value].append(row)
    result = {
        value: _stats(items)
        for value, items in grouped.items()
        if len(items) >= min_count
    }
    return dict(sorted(result.items(), key=lambda item: item[1].get("avg_excess_return_pct") or -999, reverse=True))


def _recommendations(
    overall: dict[str, Any],
    by_source: dict[str, dict[str, Any]],
    by_theme: dict[str, dict[str, Any]],
    by_horizon: dict[str, dict[str, Any]],
) -> list[str]:
    recommendations: list[str] = []
    if (overall.get("avg_return_pct") or 0) < 0 or (overall.get("win_rate") or 0) < 0.45:
        recommendations.append("近期訊號偏弱，先降低追價與隔日續抱比例")

    h1 = by_horizon.get("1")
    h5 = by_horizon.get("5")
    if h1 and h5 and (h1.get("avg_return_pct") or 0) > 0 and (h5.get("avg_return_pct") or 0) < 0:
        recommendations.append("1日效果優於5日，候選股先改成短線觀察並加強失效條件")

    small_mid = by_source.get("small_mid_radar")
    core = by_source.get("core")
    if small_mid and core:
        if (small_mid.get("avg_excess_return_pct") or 0) > (core.get("avg_excess_return_pct") or 0):
            recommendations.append("中小雷達相對核心候選較佳，可保留少量推進名額")
        elif (small_mid.get("win_rate") or 0) < 0.42:
            recommendations.append("中小雷達勝率不足，暫時提高分數與成交值門檻")

    weak_themes = [
        theme
        for theme, stats in by_theme.items()
        if stats.get("count", 0) >= 8 and (stats.get("win_rate") or 0) < 0.35
    ][:3]
    if weak_themes:
        recommendations.append("弱勢主題暫降權重: " + "、".join(weak_themes))

    return recommendations[:4]


def _parameter_hints(
    posture: str,
    by_source: dict[str, dict[str, Any]],
    by_horizon: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    if posture == "defensive":
        hints["TW_CANDIDATE_LIMIT"] = "維持 8 或更低，避免名單過長"
        hints["MIN_CONFIDENCE"] = "優先高信心，低信心不推進主候選"

    small_mid = by_source.get("small_mid_radar")
    if small_mid:
        if (small_mid.get("avg_excess_return_pct") or 0) < 0 or (small_mid.get("win_rate") or 0) < 0.42:
            hints["SMALL_MID_PROMOTE_LIMIT"] = 1
            hints["SMALL_MID_MIN_TURNOVER_MILLION"] = "提高到 60 或 80"
        else:
            hints["SMALL_MID_PROMOTE_LIMIT"] = 2

    h5 = by_horizon.get("5")
    if h5 and (h5.get("avg_return_pct") or 0) < 0:
        hints["HOLDING_REVIEW"] = "5日表現偏弱，報告中強化 MA20/量能失效條件"
    return hints


def _should_use_defensive_posture(overall: dict[str, Any], by_horizon: dict[str, dict[str, Any]]) -> bool:
    if (overall.get("avg_return_pct") or 0) < 0 and (overall.get("win_rate") or 0) < 0.45:
        return True
    h5 = by_horizon.get("5")
    return bool(h5 and (h5.get("avg_return_pct") or 0) < -3 and (h5.get("win_rate") or 0) < 0.35)


def _headline(overall: dict[str, Any], by_horizon: dict[str, dict[str, Any]]) -> str:
    avg = overall.get("avg_return_pct")
    win = overall.get("win_rate")
    if avg is None or win is None:
        return "訊號樣本不足"
    h1 = by_horizon.get("1", {})
    h5 = by_horizon.get("5", {})
    if (h1.get("avg_return_pct") or 0) > 0 and (h5.get("avg_return_pct") or 0) < 0:
        return "短線有效但延長持有轉弱"
    if avg < 0:
        return "近期整體訊號偏弱"
    return "近期訊號維持可觀察"


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
