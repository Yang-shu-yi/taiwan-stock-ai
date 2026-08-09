import json
from pathlib import Path

import pandas as pd

import signal_tracker
from signal_tracker import (
    append_early_watch_history,
    append_signal_history,
    evaluate_signal_performance,
    summarize_performance,
)
from strategy_contract import (
    EARLY_WATCH_CHANNEL,
    FEATURE_VERSION,
    LIVE_ENVIRONMENT,
    PERFORMANCE_SCHEMA_VERSION,
    PRIMARY_CHANNEL,
    SHADOW_CHANNEL,
    SIGNAL_SCHEMA_VERSION,
    STRATEGY_VERSION,
    CostAssumptions,
)


def _live_snapshot() -> dict:
    return {
        "updated_at": "2026-05-04 08:30:00",
        "mode": "PRE",
        "run_context": {
            "execution_environment": "live",
            "run_type": "scheduled",
            "strategy_version": STRATEGY_VERSION,
            "feature_version": FEATURE_VERSION,
        },
        "tw_candidates": [
            {
                "code": "2330",
                "name": "台積電",
                "rank": 1,
                "score": 90,
                "theme": "半導體",
                "price": 900,
                "pct_1d": 1.2,
                "feature_version": FEATURE_VERSION,
                "feature_vector": {"pct_20d": 8.0},
                "reasons": ["站上 MA20"],
            }
        ],
        "small_mid_candidates": [
            {
                "code": "6274",
                "name": "台燿",
                "small_mid_rank": 1,
                "score": 82,
                "small_mid_score": 82,
                "theme": "PCB",
                "price": 120,
                "pct_1d": 2.1,
                "reasons": ["估值合理"],
            }
        ],
    }


def test_append_signal_history_separates_primary_and_shadow_ledgers(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    snapshot = _live_snapshot()

    assert append_signal_history(snapshot, path) == 2
    assert append_signal_history(snapshot, path) == 0

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {(row["code"], row["candidate_channel"]) for row in rows} == {
        ("2330", PRIMARY_CHANNEL),
        ("6274", SHADOW_CHANNEL),
    }
    assert all(row["schema_version"] == SIGNAL_SCHEMA_VERSION for row in rows)
    assert all(row["execution_environment"] == LIVE_ENVIRONMENT for row in rows)
    assert all(row["signal_id"] for row in rows)
    assert rows[1]["small_mid_score"] == 82


def test_primary_history_uses_only_actionable_candidates_when_available(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    snapshot = _live_snapshot()
    snapshot["tw_candidates"].append(
        {
            "code": "1301",
            "name": "台塑",
            "score": 85,
            "entry_score": 25,
            "entry_status": "wait_pullback",
        }
    )
    snapshot["actionable_candidates"] = [
        {
            **snapshot["tw_candidates"][0],
            "entry_score": 74,
            "entry_status": "scale_in",
        }
    ]
    snapshot["small_mid_candidates"] = []

    assert append_signal_history(snapshot, path) == 1

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["code"] for row in rows] == ["2330"]
    assert rows[0]["entry_status"] == "scale_in"
    assert rows[0]["entry_score"] == 74


def test_early_watch_uses_independent_history_file_and_channel(tmp_path) -> None:
    formal_path = tmp_path / "formal.jsonl"
    early_path = tmp_path / "early.jsonl"
    snapshot = _live_snapshot()
    snapshot["actionable_candidates"] = []
    snapshot["small_mid_candidates"] = []
    snapshot["early_watch_candidates"] = [
        {
            "code": "1301",
            "name": "台塑",
            "early_watch_rank": 1,
            "score": 54,
            "entry_score": 52,
            "entry_status": "early_watch",
            "early_watch_score": 78,
            "price": 47.25,
        }
    ]

    assert append_signal_history(snapshot, formal_path) == 0
    assert append_early_watch_history(snapshot, early_path) == 1
    assert not formal_path.exists()

    row = json.loads(early_path.read_text(encoding="utf-8").strip())
    assert row["candidate_channel"] == EARLY_WATCH_CHANNEL
    assert row["source"] == "early_watch"
    assert row["early_watch_score"] == 78


def test_dry_run_and_research_never_append_formal_history(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    snapshot = _live_snapshot()
    snapshot["run_context"].update(
        {"execution_environment": "research", "run_type": "dry_run"}
    )

    assert append_signal_history(snapshot, path) == 0
    assert not path.exists()


def test_fallback_display_candidates_never_enter_formal_history(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    snapshot = _live_snapshot()
    for item in snapshot["tw_candidates"]:
        item["eligible_for_performance"] = False
    snapshot["small_mid_candidates"] = []

    assert append_signal_history(snapshot, path) == 0
    assert not path.exists()


def test_post_signal_enters_at_next_trading_session_open(monkeypatch) -> None:
    dates = pd.to_datetime(["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07"])
    stock = pd.DataFrame(
        {
            "Open": [100.0, 110.0, 120.0, 125.0],
            "Close": [105.0, 115.0, 123.0, 130.0],
        },
        index=dates,
    )
    benchmark = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0],
            "Close": [100.5, 101.5, 102.5, 103.5],
        },
        index=dates,
    )
    monkeypatch.setattr(signal_tracker, "_history_for_code", lambda code: stock)
    monkeypatch.setattr(signal_tracker, "_history_for_symbol", lambda symbol: benchmark)
    signal = {
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "signal_id": "signal-1",
        "run_id": "run-1",
        "date": "2026-05-04",
        "decision_at": "2026-05-04T14:00:00",
        "mode": "POST",
        "entry_rule": "next_session_open",
        "execution_environment": "live",
        "run_type": "scheduled",
        "strategy_version": STRATEGY_VERSION,
        "feature_version": FEATURE_VERSION,
        "candidate_channel": PRIMARY_CHANNEL,
        "source": "core",
        "code": "2330",
    }
    zero_cost = CostAssumptions(0, 0, 0, 0, 0)

    rows = signal_tracker._performance_rows_for_signal(signal, zero_cost)

    assert rows[0]["entry_date"] == "2026-05-05"
    assert rows[0]["entry_price"] == 110.0
    assert rows[0]["entry_price_field"] == "Open"
    assert rows[0]["exit_date"] == "2026-05-06"
    assert rows[0]["exit_price"] == 123.0


def test_performance_uses_net_returns_after_configurable_costs(monkeypatch) -> None:
    dates = pd.to_datetime(["2026-05-04", "2026-05-05", "2026-05-06"])
    history = pd.DataFrame(
        {"Open": [100.0, 100.0, 100.0], "Close": [100.0, 100.0, 100.0]},
        index=dates,
    )
    monkeypatch.setattr(signal_tracker, "_history_for_code", lambda code: history)
    monkeypatch.setattr(signal_tracker, "_history_for_symbol", lambda symbol: history)
    signal = {
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "signal_id": "signal-cost",
        "date": "2026-05-04",
        "mode": "PRE",
        "execution_environment": "live",
        "run_type": "scheduled",
        "strategy_version": STRATEGY_VERSION,
        "candidate_channel": PRIMARY_CHANNEL,
        "code": "2330",
    }
    assumptions = CostAssumptions(0.001425, 0.001425, 0.003, 0.0005, 0.0005)

    row = signal_tracker._performance_rows_for_signal(signal, assumptions)[0]

    assert row["gross_return_pct"] == 0.0
    assert row["transaction_cost_pct"] > 0.6
    assert row["net_return_pct"] < -0.6
    assert row["return_pct"] == row["net_return_pct"]


def test_summarize_performance_filters_contract_and_builds_real_equity_curve(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    rows = [
        _performance_row("a", "2026-05-04", "2026-05-05", 2.0, 1.0),
        _performance_row("b", "2026-05-06", "2026-05-07", -1.0, -2.0),
        {
            **_performance_row("shadow", "2026-05-08", "2026-05-09", 20.0, 20.0),
            "candidate_channel": SHADOW_CHANNEL,
        },
        {"return_pct": 99.0, "excess_return_pct": 99.0},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    summary = summarize_performance(path, primary_horizon=1)

    assert summary["count"] == 2
    assert summary["signal_dates"] == 2
    assert summary["net_avg_return_pct"] == 0.5
    assert summary["net_excess_expectancy_pct"] == -0.5
    assert summary["win_rate"] == 0.5
    assert summary["max_drawdown_pct"] < 0
    assert summary["capital_curve_method"] == "non_overlapping_equal_weight_cohorts"
    assert summary["capital_curve_cohorts"] == 2
    assert summary["legacy_rows_excluded"] == 1


def test_history_fetch_failure_returns_empty_dataframe(monkeypatch) -> None:
    class BrokenTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, **kwargs):
            raise TypeError("'NoneType' object is not subscriptable")

    monkeypatch.setattr(signal_tracker.yf, "Ticker", BrokenTicker)
    signal_tracker._history_for_symbol.cache_clear()

    assert signal_tracker._history_for_symbol("2330.TW").empty


def test_history_fetch_is_cached_per_symbol(monkeypatch) -> None:
    calls = []

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            calls.append(symbol)

        def history(self, **kwargs):
            return pd.DataFrame(
                {"Close": [100.0, 101.0]},
                index=pd.to_datetime(["2026-05-04", "2026-05-05"]),
            )

    monkeypatch.setattr(signal_tracker.yf, "Ticker", FakeTicker)
    signal_tracker._history_for_symbol.cache_clear()

    signal_tracker._history_for_symbol("2330.TW")
    signal_tracker._history_for_symbol("2330.TW")

    assert calls == ["2330.TW"]


def test_evaluate_signal_performance_skips_broken_signal(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "signals.jsonl"
    performance_path = tmp_path / "performance.jsonl"
    signal = {
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "signal_id": "signal-1",
        "execution_environment": LIVE_ENVIRONMENT,
        "run_type": "scheduled",
        "strategy_version": STRATEGY_VERSION,
        "candidate_channel": PRIMARY_CHANNEL,
        "code": "2330",
    }
    history_path.write_text(json.dumps(signal, ensure_ascii=False) + "\n", encoding="utf-8")

    def broken_rows(signal: dict) -> list[dict]:
        raise RuntimeError("history source failed")

    monkeypatch.setattr(signal_tracker, "_performance_rows_for_signal", broken_rows)

    assert evaluate_signal_performance(history_path, performance_path) == 0
    assert not performance_path.exists()


def _performance_row(
    signal_id: str,
    entry_date: str,
    exit_date: str,
    net_return: float,
    net_excess: float,
) -> dict:
    return {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "signal_id": signal_id,
        "execution_environment": LIVE_ENVIRONMENT,
        "candidate_channel": PRIMARY_CHANNEL,
        "strategy_version": STRATEGY_VERSION,
        "source": "core",
        "theme": "半導體",
        "horizon": 1,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "gross_return_pct": net_return + 0.6,
        "net_return_pct": net_return,
        "net_excess_return_pct": net_excess,
    }
