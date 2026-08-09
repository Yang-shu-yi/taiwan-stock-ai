from datetime import date, timedelta

from strategy_features import MODEL_FEATURE_NAMES
from strategy_model import run_walk_forward_baseline, score_shadow_candidates


def test_walk_forward_model_stays_shadow_when_data_is_insufficient() -> None:
    records = [_record(index, 1.0 if index % 2 else -1.0, index) for index in range(10)]

    report = run_walk_forward_baseline(
        records,
        min_train_dates=8,
        test_dates=2,
        gap_dates=1,
        min_observations=20,
    )

    assert report["status"] == "insufficient_data"
    assert report["ready_for_selection"] is False
    assert report["metrics"] == {}


def test_walk_forward_logistic_is_chronological_calibrated_research_only() -> None:
    records = []
    for day_index in range(100):
        records.append(_record(day_index, -1.0, day_index * 2))
        records.append(_record(day_index, 1.0, day_index * 2 + 1))

    report = run_walk_forward_baseline(
        records,
        min_train_dates=30,
        test_dates=10,
        gap_dates=2,
        min_observations=100,
    )

    assert report["status"] == "research_ready"
    assert report["ready_for_selection"] is False
    assert report["folds"] >= 3
    assert report["metrics"]["roc_auc"] > 0.9
    assert report["metrics"]["brier_score"] < 0.25
    assert report["calibration_bins"]
    assert all(fold["train_end"] < fold["test_start"] for fold in report["fold_details"])
    assert report["guardrails"]["hyperparameter_search"] is False
    assert report["model_artifact"]["calibration"]["method"] == "platt_on_out_of_fold_predictions"

    positive_vector = {name: 0.0 for name in MODEL_FEATURE_NAMES}
    positive_vector["pct_20d"] = 10.0
    positive_vector["rs_20d"] = 5.0
    negative_vector = dict(positive_vector, pct_20d=-10.0, rs_20d=-5.0)
    ranking = score_shadow_candidates(
        report,
        [
            {"code": "A", "name": "A", "rank": 1, "feature_vector": negative_vector},
            {"code": "B", "name": "B", "rank": 2, "feature_vector": positive_vector},
        ],
    )
    assert ranking[0]["code"] == "B"
    assert ranking[0]["mode"] == "shadow_only"


def _record(day_index: int, feature_signal: float, identifier: int) -> dict:
    entry = date(2025, 1, 1) + timedelta(days=day_index)
    vector = {name: 0.0 for name in MODEL_FEATURE_NAMES}
    vector["pct_20d"] = feature_signal * 10.0
    vector["rs_20d"] = feature_signal * 5.0
    return {
        "signal_id": f"signal-{identifier}",
        "date": entry.isoformat(),
        "exit_date": entry.isoformat(),
        "feature_vector": vector,
        "net_excess_return_pct": 2.0 if feature_signal > 0 else -2.0,
    }
