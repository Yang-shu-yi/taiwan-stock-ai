import json

from signal_tracker import append_signal_history, summarize_performance


def test_append_signal_history_writes_jsonl(tmp_path) -> None:
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
    }
    assert append_signal_history(snapshot, path) == 1
    assert append_signal_history(snapshot, path) == 0
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["code"] == "2330"
    assert row["theme"] == "半導體"


def test_summarize_performance(tmp_path) -> None:
    path = tmp_path / "perf.jsonl"
    rows = [
        {"rank": 1, "theme": "半導體", "horizon": 1, "return_pct": 2.0, "excess_return_pct": 1.0},
        {"rank": 5, "theme": "半導體", "horizon": 1, "return_pct": -1.0, "excess_return_pct": -2.0},
        {"rank": 8, "theme": "金融", "horizon": 3, "return_pct": 3.0, "excess_return_pct": 2.0},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    summary = summarize_performance(path)
    assert summary["count"] == 3
    assert summary["avg_return_pct"] == 1.33
    assert summary["win_rate"] == 0.6667
    assert summary["avg_excess_return_pct"] == 0.33
    assert summary["top5_hit_rate"] == 0.5
    assert summary["theme_hit_rate"]["半導體"] == 0.5
