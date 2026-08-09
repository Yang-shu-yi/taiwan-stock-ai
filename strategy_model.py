from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from strategy_contract import (
    FEATURE_VERSION,
    LIVE_ENVIRONMENT,
    MODEL_VERSION,
    PERFORMANCE_SCHEMA_VERSION,
    PRIMARY_CHANNEL,
    SIGNAL_SCHEMA_VERSION,
    STRATEGY_VERSION,
)
from strategy_features import MODEL_FEATURE_NAMES


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


def build_research_model_report(
    history_path: str | Path = "signal_history.jsonl",
    performance_path: str | Path = "signal_performance.jsonl",
    *,
    horizon: int | None = None,
    current_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    horizon = horizon or int(os.getenv("MODEL_OUTCOME_HORIZON", "5"))
    signals = {
        row.get("signal_id"): row
        for row in _read_jsonl(history_path)
        if row.get("schema_version") == SIGNAL_SCHEMA_VERSION
        and row.get("execution_environment") == LIVE_ENVIRONMENT
        and row.get("candidate_channel") == PRIMARY_CHANNEL
        and row.get("strategy_version") == STRATEGY_VERSION
        and row.get("feature_version") == FEATURE_VERSION
        and row.get("signal_id")
    }
    records: list[dict[str, Any]] = []
    for performance in _read_jsonl(performance_path):
        if performance.get("schema_version") != PERFORMANCE_SCHEMA_VERSION:
            continue
        if performance.get("signal_id") not in signals:
            continue
        if int(performance.get("horizon") or -1) != horizon:
            continue
        outcome = performance.get("net_excess_return_pct")
        if outcome is None:
            continue
        signal = signals[performance["signal_id"]]
        vector = signal.get("feature_vector") or performance.get("feature_vector") or {}
        records.append(
            {
                "signal_id": performance["signal_id"],
                "date": performance.get("entry_date") or performance.get("date"),
                "exit_date": performance.get("exit_date"),
                "feature_vector": vector,
                "net_excess_return_pct": float(outcome),
            }
        )

    report = run_walk_forward_baseline(records)
    report.update(
        {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "outcome_horizon": horizon,
            "outcome": "net_excess_return_pct > 0",
            "deployment_mode": "shadow_only",
        }
    )
    report["shadow_ranking"] = score_shadow_candidates(
        report,
        current_candidates or [],
    )
    return report


def run_walk_forward_baseline(
    records: list[dict[str, Any]],
    *,
    min_train_dates: int | None = None,
    test_dates: int | None = None,
    gap_dates: int | None = None,
    min_observations: int | None = None,
) -> dict[str, Any]:
    min_train_dates = min_train_dates or int(os.getenv("MODEL_MIN_TRAIN_DATES", "40"))
    test_dates = test_dates or int(os.getenv("MODEL_TEST_DATES", "10"))
    gap_dates = gap_dates if gap_dates is not None else int(os.getenv("MODEL_GAP_DATES", "5"))
    min_observations = min_observations or int(os.getenv("MODEL_MIN_OBSERVATIONS", "120"))
    minimum_folds = int(os.getenv("MODEL_MIN_FOLDS", "3"))

    usable = [
        record
        for record in records
        if record.get("date")
        and record.get("feature_vector")
        and record.get("net_excess_return_pct") is not None
    ]
    usable.sort(key=lambda record: (str(record["date"]), str(record.get("signal_id") or "")))
    dates = sorted({str(record["date"]) for record in usable})
    class_counts = {
        "positive": sum(float(record["net_excess_return_pct"]) > 0 for record in usable),
        "non_positive": sum(float(record["net_excess_return_pct"]) <= 0 for record in usable),
    }
    gates = {
        "minimum_observations": min_observations,
        "minimum_signal_dates": min_train_dates + test_dates,
        "minimum_folds": minimum_folds,
        "chronological_split": True,
        "gap_dates": gap_dates,
        "fixed_feature_set": list(MODEL_FEATURE_NAMES),
        "hyperparameter_search": False,
    }
    if (
        len(usable) < min_observations
        or len(dates) < min_train_dates + test_dates
        or not class_counts["positive"]
        or not class_counts["non_positive"]
    ):
        return {
            "status": "insufficient_data",
            "ready_for_selection": False,
            "observations": len(usable),
            "signal_dates": len(dates),
            "class_counts": class_counts,
            "folds": 0,
            "metrics": {},
            "calibration_bins": [],
            "guardrails": gates,
            "reason": "尚未通過最小樣本、日期跨度與雙類別門檻",
        }

    predictions: list[dict[str, Any]] = []
    fold_reports: list[dict[str, Any]] = []
    prior_oof_probabilities: list[float] = []
    prior_oof_labels: list[int] = []

    test_start = min_train_dates + gap_dates
    fold = 0
    while test_start < len(dates):
        test_date_slice = dates[test_start : test_start + test_dates]
        if not test_date_slice:
            break
        first_test_date = test_date_slice[0]
        train_date_limit = test_start - gap_dates
        allowed_train_dates = set(dates[:train_date_limit])
        test_date_set = set(test_date_slice)
        train_records = [
            record
            for record in usable
            if str(record["date"]) in allowed_train_dates
            and (
                not record.get("exit_date")
                or str(record["exit_date"]) < first_test_date
            )
        ]
        test_records = [record for record in usable if str(record["date"]) in test_date_set]
        train_labels = np.asarray(
            [float(record["net_excess_return_pct"]) > 0 for record in train_records],
            dtype=float,
        )
        if not test_records or len(set(train_labels.tolist())) < 2:
            test_start += test_dates
            continue

        train_matrix, medians, means, scales = _fit_transform(train_records)
        test_matrix = _transform(test_records, medians, means, scales)
        weights, bias = _fit_logistic(train_matrix, train_labels)
        raw_probabilities = _sigmoid(test_matrix @ weights + bias)

        calibrator: tuple[np.ndarray, float] | None = None
        if len(prior_oof_labels) >= 40 and len(set(prior_oof_labels)) == 2:
            logits = _logit(np.asarray(prior_oof_probabilities, dtype=float)).reshape(-1, 1)
            calibrator = _fit_logistic(logits, np.asarray(prior_oof_labels, dtype=float), l2=0.02)
        calibrated = _apply_calibrator(raw_probabilities, calibrator)
        labels = [int(float(record["net_excess_return_pct"]) > 0) for record in test_records]

        for record, raw_probability, probability, label in zip(
            test_records,
            raw_probabilities.tolist(),
            calibrated.tolist(),
            labels,
        ):
            predictions.append(
                {
                    "signal_id": record.get("signal_id"),
                    "date": record["date"],
                    "probability": float(probability),
                    "raw_probability": float(raw_probability),
                    "label": label,
                    "net_excess_return_pct": float(record["net_excess_return_pct"]),
                    "fold": fold,
                }
            )
        prior_oof_probabilities.extend(raw_probabilities.tolist())
        prior_oof_labels.extend(labels)
        fold_reports.append(
            {
                "fold": fold,
                "train_start": min(str(record["date"]) for record in train_records),
                "train_end": max(str(record["date"]) for record in train_records),
                "test_start": test_date_slice[0],
                "test_end": test_date_slice[-1],
                "train_observations": len(train_records),
                "test_observations": len(test_records),
                "calibrated_with_prior_oof": calibrator is not None,
            }
        )
        fold += 1
        test_start += test_dates

    if len(fold_reports) < minimum_folds or not predictions:
        return {
            "status": "insufficient_walk_forward_folds",
            "ready_for_selection": False,
            "observations": len(usable),
            "signal_dates": len(dates),
            "class_counts": class_counts,
            "folds": len(fold_reports),
            "fold_details": fold_reports,
            "metrics": {},
            "calibration_bins": [],
            "guardrails": gates,
            "reason": "可用的無洩漏 walk-forward folds 不足",
        }

    labels = np.asarray([item["label"] for item in predictions], dtype=float)
    probabilities = np.asarray([item["probability"] for item in predictions], dtype=float)
    raw_probabilities = np.asarray([item["raw_probability"] for item in predictions], dtype=float)
    outcomes = np.asarray([item["net_excess_return_pct"] for item in predictions], dtype=float)
    order = np.argsort(probabilities)[::-1]
    top_count = max(1, len(order) // 4)
    top_indices = order[:top_count]
    metrics = {
        "oof_observations": len(predictions),
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 6),
        "raw_brier_score": round(float(np.mean((raw_probabilities - labels) ** 2)), 6),
        "log_loss": round(_log_loss(labels, probabilities), 6),
        "roc_auc": _roc_auc(labels, probabilities),
        "top_quartile_net_excess_pct": round(float(np.mean(outcomes[top_indices])), 4),
        "all_oof_net_excess_pct": round(float(np.mean(outcomes)), 4),
    }
    full_matrix, medians, means, scales = _fit_transform(usable)
    full_labels = np.asarray(
        [float(record["net_excess_return_pct"]) > 0 for record in usable],
        dtype=float,
    )
    final_weights, final_bias = _fit_logistic(full_matrix, full_labels)
    final_calibrator: tuple[np.ndarray, float] | None = None
    if len(set(labels.tolist())) == 2:
        final_calibrator = _fit_logistic(
            _logit(raw_probabilities).reshape(-1, 1),
            labels,
            l2=0.02,
        )
    model_artifact = {
        "feature_names": list(MODEL_FEATURE_NAMES),
        "medians": medians.tolist(),
        "means": means.tolist(),
        "scales": scales.tolist(),
        "coefficients": final_weights.tolist(),
        "intercept": float(final_bias),
        "calibration": None
        if final_calibrator is None
        else {
            "method": "platt_on_out_of_fold_predictions",
            "coefficient": float(final_calibrator[0][0]),
            "intercept": float(final_calibrator[1]),
        },
    }
    # This is a research baseline. A human/versioned promotion step is required even after gates pass.
    return {
        "status": "research_ready",
        "ready_for_selection": False,
        "observations": len(usable),
        "signal_dates": len(dates),
        "class_counts": class_counts,
        "folds": len(fold_reports),
        "fold_details": fold_reports,
        "metrics": metrics,
        "calibration_bins": _calibration_bins(labels, probabilities),
        "model_artifact": model_artifact,
        "guardrails": {
            **gates,
            "promotion_requires_new_strategy_version": True,
            "pbo_status": "not_estimated_single_fixed_baseline",
        },
        "reason": "基線僅供 shadow ranking 研究，不直接影響正式名單",
    }


def score_shadow_candidates(
    model_report: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if model_report.get("status") != "research_ready":
        return []
    artifact = model_report.get("model_artifact") or {}
    feature_names = artifact.get("feature_names")
    if feature_names != list(MODEL_FEATURE_NAMES):
        return []
    usable = [item for item in candidates if item.get("code") and item.get("feature_vector")]
    if not usable:
        return []

    raw = _raw_matrix([{"feature_vector": item["feature_vector"]} for item in usable])
    medians = np.asarray(artifact["medians"], dtype=float)
    means = np.asarray(artifact["means"], dtype=float)
    scales = np.asarray(artifact["scales"], dtype=float)
    matrix = (np.where(np.isnan(raw), medians, raw) - means) / scales
    weights = np.asarray(artifact["coefficients"], dtype=float)
    raw_probabilities = _sigmoid(matrix @ weights + float(artifact["intercept"]))
    calibration = artifact.get("calibration")
    if calibration:
        probabilities = _sigmoid(
            _logit(raw_probabilities) * float(calibration["coefficient"])
            + float(calibration["intercept"])
        )
    else:
        probabilities = raw_probabilities
    ranking = [
        {
            "code": item.get("code"),
            "name": item.get("name"),
            "primary_rank": item.get("rank"),
            "probability_positive_net_excess": round(float(probability), 4),
            "model_version": MODEL_VERSION,
            "mode": "shadow_only",
        }
        for item, probability in zip(usable, probabilities.tolist())
    ]
    ranking.sort(
        key=lambda item: item["probability_positive_net_excess"],
        reverse=True,
    )
    for rank, item in enumerate(ranking, start=1):
        item["shadow_rank"] = rank
    return ranking


def _fit_transform(
    records: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = _raw_matrix(records)
    medians = np.asarray(
        [
            float(np.median(column[np.isfinite(column)]))
            if np.any(np.isfinite(column))
            else 0.0
            for column in raw.T
        ],
        dtype=float,
    )
    filled = np.where(np.isnan(raw), medians, raw)
    means = filled.mean(axis=0)
    scales = filled.std(axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    return (filled - means) / scales, medians, means, scales


def _transform(
    records: list[dict[str, Any]],
    medians: np.ndarray,
    means: np.ndarray,
    scales: np.ndarray,
) -> np.ndarray:
    raw = _raw_matrix(records)
    filled = np.where(np.isnan(raw), medians, raw)
    return (filled - means) / scales


def _raw_matrix(records: list[dict[str, Any]]) -> np.ndarray:
    rows: list[list[float]] = []
    for record in records:
        vector = record.get("feature_vector") or {}
        row: list[float] = []
        for name in MODEL_FEATURE_NAMES:
            try:
                value = float(vector.get(name))
            except (TypeError, ValueError):
                value = math.nan
            row.append(value if math.isfinite(value) else math.nan)
        rows.append(row)
    return np.asarray(rows, dtype=float)


def _fit_logistic(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    l2: float = 0.10,
    learning_rate: float = 0.05,
    iterations: int = 800,
) -> tuple[np.ndarray, float]:
    weights = np.zeros(matrix.shape[1], dtype=float)
    positive_rate = float(np.clip(labels.mean(), 1e-4, 1 - 1e-4))
    bias = math.log(positive_rate / (1.0 - positive_rate))
    for _ in range(iterations):
        probabilities = _sigmoid(matrix @ weights + bias)
        errors = probabilities - labels
        gradient = matrix.T @ errors / len(labels) + l2 * weights
        bias_gradient = float(errors.mean())
        weights -= learning_rate * gradient
        bias -= learning_rate * bias_gradient
    return weights, bias


def _apply_calibrator(
    raw_probabilities: np.ndarray,
    calibrator: tuple[np.ndarray, float] | None,
) -> np.ndarray:
    if calibrator is None:
        return raw_probabilities
    weights, bias = calibrator
    logits = _logit(raw_probabilities).reshape(-1, 1)
    return _sigmoid(logits @ weights + bias)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped))


def _log_loss(labels: np.ndarray, probabilities: np.ndarray) -> float:
    clipped = np.clip(probabilities, 1e-9, 1.0 - 1e-9)
    return float(-np.mean(labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped)))


def _roc_auc(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    positives = probabilities[labels == 1]
    negatives = probabilities[labels == 0]
    if not len(positives) or not len(negatives):
        return None
    wins = 0.0
    for positive in positives:
        wins += float(np.sum(positive > negatives))
        wins += float(np.sum(positive == negatives)) * 0.5
    return round(wins / (len(positives) * len(negatives)), 6)


def _calibration_bins(labels: np.ndarray, probabilities: np.ndarray) -> list[dict[str, Any]]:
    bins: list[dict[str, Any]] = []
    for lower in np.linspace(0.0, 0.8, 5):
        upper = lower + 0.2
        mask = (probabilities >= lower) & (
            probabilities <= upper if upper >= 1.0 else probabilities < upper
        )
        if not np.any(mask):
            continue
        bins.append(
            {
                "range": f"{lower:.1f}-{upper:.1f}",
                "count": int(mask.sum()),
                "mean_probability": round(float(probabilities[mask].mean()), 4),
                "observed_rate": round(float(labels[mask].mean()), 4),
            }
        )
    return bins
