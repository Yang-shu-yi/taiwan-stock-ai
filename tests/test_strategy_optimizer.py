import json

from strategy_optimizer import build_strategy_optimization


def test_strategy_optimizer_enters_defensive_posture_for_weak_recent_signals(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    rows = []
    for index in range(12):
        rows.append(
            {
                "source": "core",
                "theme": "半導體",
                "horizon": 5,
                "return_pct": -4.0 if index < 9 else 1.0,
                "excess_return_pct": -1.5,
            }
        )
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = build_strategy_optimization(path, min_group_count=4)

    assert result["posture"] == "defensive"
    assert result["recommendations"]
    assert "HOLDING_REVIEW" in result["parameter_hints"]


def test_strategy_optimizer_compares_small_mid_source(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    rows = []
    for _ in range(8):
        rows.append({"source": "core", "theme": "金融", "horizon": 1, "return_pct": -1.0, "excess_return_pct": -1.0})
        rows.append({"source": "small_mid_radar", "theme": "PCB", "horizon": 1, "return_pct": 2.0, "excess_return_pct": 1.5})
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = build_strategy_optimization(path, min_group_count=4)

    assert result["groups"]["by_source"]["small_mid_radar"]["win_rate"] == 1.0
    assert result["parameter_hints"]["SMALL_MID_PROMOTE_LIMIT"] == 2
