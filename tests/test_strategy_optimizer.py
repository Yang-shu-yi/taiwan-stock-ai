import json
from datetime import date, timedelta

from strategy_contract import (
    LIVE_ENVIRONMENT,
    PERFORMANCE_SCHEMA_VERSION,
    PRIMARY_CHANNEL,
    SHADOW_CHANNEL,
    STRATEGY_VERSION,
)
from strategy_optimizer import build_strategy_optimization


def test_strategy_optimizer_uses_net_excess_only_after_sample_gate(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    rows = [
        _row(index, net_return=-4.0 if index < 9 else 1.0, net_excess=-1.5)
        for index in range(12)
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = build_strategy_optimization(path, min_group_count=4, min_signal_dates=8)

    assert result["status"] == "evidence_available"
    assert result["posture"] == "defensive"
    assert result["groups"]["overall"]["net_excess_expectancy_pct"] == -1.5
    assert result["automatic_parameter_changes"] is False
    assert result["parameter_hints"]["REQUIRES_NEW_STRATEGY_VERSION"] is True


def test_strategy_optimizer_does_not_use_shadow_radar_to_change_primary(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    rows = []
    for index in range(8):
        rows.append(_row(index, net_return=-1.0, net_excess=-1.0))
        rows.append(
            {
                **_row(index, net_return=10.0, net_excess=9.0),
                "signal_id": f"shadow-{index}",
                "candidate_channel": SHADOW_CHANNEL,
                "source": "small_mid_radar",
            }
        )
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = build_strategy_optimization(path, min_group_count=4, min_signal_dates=4)

    assert result["groups"]["overall"]["count"] == 8
    assert result["groups"]["overall"]["net_excess_expectancy_pct"] == -1.0
    assert result["shadow_radar_affects_primary"] is False
    assert result["parameter_hints"]["SMALL_MID_SHADOW_MODE"] is True


def test_strategy_optimizer_refuses_small_sample_tuning(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    rows = [_row(index, net_return=5.0, net_excess=4.0) for index in range(3)]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = build_strategy_optimization(path, min_signal_dates=10)

    assert result["status"] == "collecting"
    assert result["posture"] == "normal"
    assert result["recommendations"] == []


def _row(index: int, *, net_return: float, net_excess: float) -> dict:
    entry = date(2026, 1, 1) + timedelta(days=index)
    return {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "signal_id": f"primary-{index}",
        "execution_environment": LIVE_ENVIRONMENT,
        "candidate_channel": PRIMARY_CHANNEL,
        "strategy_version": STRATEGY_VERSION,
        "source": "core",
        "theme": "半導體",
        "horizon": 5,
        "entry_date": entry.isoformat(),
        "gross_return_pct": net_return + 0.7,
        "net_return_pct": net_return,
        "net_excess_return_pct": net_excess,
    }
