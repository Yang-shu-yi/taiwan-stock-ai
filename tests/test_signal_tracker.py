import json
import tempfile
from pathlib import Path

import signal_tracker
from signal_tracker import append_signal_history, evaluate_signal_performance, summarize_performance


def test_append_signal_history_writes_core_and_small_mid_jsonl(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    snapshot = {
        "updated_at": "2026-05-04 08:30:00",
        "mode": "PRE",
        "tw_candidates": [
            {
                "code": "2330",
                "name": "台積電",
                "rank": 1,
                "score": 90,
                "theme": "半導體",
                "price": 900,
                "pct_1d": 1.2,
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

    assert append_signal_history(snapshot, path) == 2
    assert append_signal_history(snapshot, path) == 0

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {(row["code"], row["source"]) for row in rows} == {
        ("2330", "core"),
        ("6274", "small_mid_radar"),
    }
    assert rows[1]["small_mid_score"] == 82


def test_summarize_performance() -> None:
    rows = [
        {"rank": 1, "theme": "半導體", "source": "core", "horizon": 1, "return_pct": 2.0, "excess_return_pct": 1.0},
        {"rank": 5, "theme": "半導體", "source": "core", "horizon": 1, "return_pct": -1.0, "excess_return_pct": -2.0},
        {"rank": 1, "theme": "PCB", "source": "small_mid_radar", "horizon": 3, "return_pct": 3.0, "excess_return_pct": 2.0},
    ]
    summary = summarize_performance_from_rows(rows)

    assert summary["count"] == 3
    assert summary["avg_return_pct"] == 1.33
    assert summary["win_rate"] == 0.6667
    assert summary["avg_excess_return_pct"] == 0.33
    assert summary["top5_hit_rate"] == 0.6667
    assert summary["theme_hit_rate"]["半導體"] == 0.5
    assert summary["source_hit_rate"]["small_mid_radar"] == 1.0


def test_history_fetch_failure_returns_empty_dataframe(monkeypatch) -> None:
    class BrokenTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, **kwargs):
            raise TypeError("'NoneType' object is not subscriptable")

    monkeypatch.setattr(signal_tracker.yf, "Ticker", BrokenTicker)

    assert signal_tracker._history_for_symbol("2330.TW").empty


def test_evaluate_signal_performance_skips_broken_signal(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "signals.jsonl"
    performance_path = tmp_path / "performance.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "run_id": "2026-05-04:PRE:test",
                "date": "2026-05-04",
                "mode": "PRE",
                "source": "core",
                "code": "2330",
                "rank": 1,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def broken_rows(signal: dict) -> list[dict]:
        raise RuntimeError("history source failed")

    monkeypatch.setattr(signal_tracker, "_performance_rows_for_signal", broken_rows)

    assert evaluate_signal_performance(history_path, performance_path) == 0
    assert not performance_path.exists()


def summarize_performance_from_rows(rows: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "perf.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
        return summarize_performance(path)
