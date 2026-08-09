"""Build and execute the reproducible system-performance diagnostic notebook."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).with_name("system_performance_diagnostic.ipynb")


def code(source: str):
    return nbf.v4.new_code_cell(source.strip())


def markdown(source: str):
    return nbf.v4.new_markdown_cell(source.strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {"name": "python", "version": "3.12"},
}
nb["cells"] = [
    markdown(
        """
# Taiwan Stock AI — System Performance Diagnostic

## TL;DR

The local evidence is useful for diagnosing the measurement system, but it is not yet a professional backtest. It contains only five distinct signal dates, combines several holding horizons, includes repeated dry/manual runs, and applies an entry price that changes with the run clock and calendar. The core candidate stream is materially stronger than the small/mid-cap radar in this sample, but neither should be treated as proven without a fixed execution rule and a larger out-of-sample live cohort.

This notebook is deliberately read-only. It loads `signal_history.jsonl` and `signal_performance.jsonl`, recomputes all results from source rows, and does not call external market APIs.
"""
    ),
    markdown(
        """
## Context & Methods

- **Question:** Is the perceived mediocre win rate caused by weak signals, weak measurement, or both?
- **Primary analysis grain:** one signal date × code × source × horizon. This removes duplicate runs on the same date while retaining separate horizons.
- **Comparison grain:** raw rows and the application's current “last 200 rows” window are also shown to expose metric sensitivity.
- **Uncertainty:** confidence intervals use a cluster bootstrap by signal date because rows from the same date are not independent.
- **Cost sensitivity:** 0.6 percentage points round trip is an illustrative scenario only, not a statement of the user's broker fee.
"""
    ),
    code(
        """
from pathlib import Path
import json
import numpy as np
import pandas as pd
from IPython.display import display

pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 140)

root = Path.cwd()
if not (root / "signal_history.jsonl").exists():
    root = root.parent

def read_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                rows.append(json.loads(line))
    return pd.DataFrame(rows)

history = read_jsonl(root / "signal_history.jsonl")
performance = read_jsonl(root / "signal_performance.jsonl")

for frame in (history, performance):
    frame["source_norm"] = frame.get("source", pd.Series(index=frame.index, dtype="object")).fillna("core")
    frame["date"] = pd.to_datetime(frame["date"]).dt.date

history["created_at"] = pd.to_datetime(history["created_at"])
performance["evaluated_at"] = pd.to_datetime(performance["evaluated_at"])

print(f"history rows={len(history):,}; performance rows={len(performance):,}")
print(f"signal date range={history['date'].min()} to {history['date'].max()}")
"""
    ),
    markdown("## Data quality and analysis grain"),
    code(
        """
history_run_key = ["run_id", "code", "source_norm"]
history_date_key = ["date", "code", "source_norm"]
performance_run_key = ["run_id", "code", "source_norm", "horizon"]
performance_date_key = ["date", "code", "source_norm", "horizon"]

quality = pd.DataFrame([
    {"check": "History rows", "value": len(history), "interpretation": "Rows written by all runs"},
    {"check": "Distinct run-level signals", "value": len(history.drop_duplicates(history_run_key)), "interpretation": "Exact run duplicates removed"},
    {"check": "Distinct date-level signals", "value": len(history.drop_duplicates(history_date_key)), "interpretation": "Recommended analysis grain"},
    {"check": "Distinct signal dates", "value": history["date"].nunique(), "interpretation": "Independent market-day clusters"},
    {"check": "Performance rows", "value": len(performance), "interpretation": "One row per recorded horizon"},
    {"check": "Missing source labels", "value": int(performance.get("source", pd.Series(index=performance.index)).isna().sum()), "interpretation": "Normalized to core for compatibility"},
    {"check": "POST-mode history share", "value": f"{(history['mode'].eq('POST').mean() * 100):.1f}%", "interpretation": "No local PRE cohort"},
])
display(quality)

run_profile = (history.groupby(["date", "run_id"], as_index=False)
               .agg(signals=("code", "size"), created_at=("created_at", "min")))
display(run_profile.sort_values(["date", "created_at"]))
"""
    ),
    markdown(
        """
## Results: the headline changes with the row-selection rule

The application currently takes the final 200 performance rows in file order. Because each signal normally creates four horizon rows and evaluation writes do not necessarily follow signal chronology, this is not the same thing as the latest 200 independent signals.
"""
    ),
    code(
        """
performance = performance.sort_index().copy()
raw = performance.drop_duplicates(performance_run_key, keep="last")
date_dedup = (performance.sort_values("evaluated_at")
              .drop_duplicates(performance_date_key, keep="last"))
last_200 = performance.tail(200).copy()

def summarize(frame: pd.DataFrame, label: str) -> dict:
    wins = frame["return_pct"] > 0
    positive = frame.loc[wins, "return_pct"].sum()
    negative = -frame.loc[~wins, "return_pct"].sum()
    return {
        "view": label,
        "rows": len(frame),
        "signal_dates": frame["date"].nunique(),
        "mean_return_pct": frame["return_pct"].mean(),
        "median_return_pct": frame["return_pct"].median(),
        "win_rate_pct": wins.mean() * 100,
        "mean_excess_pct": frame["excess_return_pct"].mean(),
        "excess_win_rate_pct": (frame["excess_return_pct"] > 0).mean() * 100,
        "profit_factor": positive / negative if negative else np.nan,
    }

views = pd.DataFrame([
    summarize(last_200, "Application: last 200 file rows"),
    summarize(raw, "Run-level deduplicated rows"),
    summarize(date_dedup, "Date/code/source deduplicated rows"),
]).round(3)
display(views)

def by_horizon(frame: pd.DataFrame, view: str) -> pd.DataFrame:
    rows = []
    for horizon, group in frame.groupby("horizon"):
        row = summarize(group, view)
        row["horizon"] = int(horizon)
        rows.append(row)
    return pd.DataFrame(rows)[[
        "view", "horizon", "rows", "signal_dates", "mean_return_pct",
        "median_return_pct", "win_rate_pct", "mean_excess_pct", "excess_win_rate_pct"
    ]]

horizon_comparison = pd.concat([
    by_horizon(last_200, "last 200"),
    by_horizon(date_dedup, "date-level dedup"),
], ignore_index=True).round(3)
display(horizon_comparison)
"""
    ),
    markdown("## Results: core and small/mid-cap radar are different products"),
    code(
        """
source_rows = []
for (source, horizon), group in date_dedup.groupby(["source_norm", "horizon"]):
    source_rows.append({
        "source": source,
        "horizon": int(horizon),
        "rows": len(group),
        "signal_dates": group["date"].nunique(),
        "mean_return_pct": group["return_pct"].mean(),
        "win_rate_pct": (group["return_pct"] > 0).mean() * 100,
        "mean_excess_pct": group["excess_return_pct"].mean(),
        "excess_win_rate_pct": (group["excess_return_pct"] > 0).mean() * 100,
    })
source_by_horizon = pd.DataFrame(source_rows).round(3)
display(source_by_horizon)

source_overall = []
for source, group in date_dedup.groupby("source_norm"):
    result = summarize(group, source)
    result["unique_signals"] = len(group.drop_duplicates(["date", "code", "source_norm"]))
    source_overall.append(result)
source_overall = pd.DataFrame(source_overall).round(3)
display(source_overall)

recent_source = (last_200.groupby("source_norm", as_index=False)
                 .agg(rows=("return_pct", "size"),
                      mean_return_pct=("return_pct", "mean"),
                      win_rate_pct=("return_pct", lambda s: (s > 0).mean() * 100),
                      return_sum_pct=("return_pct", "sum")))
total_net_loss = -last_200["return_pct"].sum()
small_mid_net_loss = -last_200.loc[last_200["source_norm"] == "small_mid_radar", "return_pct"].sum()
print(f"Small/mid radar share of aggregate net loss in last-200 view: {small_mid_net_loss / total_net_loss * 100:.1f}%")
display(recent_source.round(3))
"""
    ),
    markdown(
        """
## Uncertainty: cluster bootstrap by signal date

Rows from one day share the same market regime and are correlated. Resampling individual rows would therefore overstate confidence. The bootstrap below resamples the five observed signal dates as clusters and reports percentile intervals.
"""
    ),
    code(
        """
rng = np.random.default_rng(20260716)
bootstrap_rows = []

for horizon, horizon_frame in date_dedup.groupby("horizon"):
    daily = (horizon_frame.groupby("date", as_index=False)
             .agg(n=("return_pct", "size"),
                  return_sum=("return_pct", "sum"),
                  excess_sum=("excess_return_pct", "sum"),
                  wins=("return_pct", lambda s: int((s > 0).sum()))))
    draws = rng.integers(0, len(daily), size=(20_000, len(daily)))
    n = daily["n"].to_numpy()[draws].sum(axis=1)
    mean_return = daily["return_sum"].to_numpy()[draws].sum(axis=1) / n
    mean_excess = daily["excess_sum"].to_numpy()[draws].sum(axis=1) / n
    win_rate = daily["wins"].to_numpy()[draws].sum(axis=1) / n * 100
    bootstrap_rows.append({
        "horizon": int(horizon),
        "signal_dates": len(daily),
        "mean_return_pct": horizon_frame["return_pct"].mean(),
        "return_ci_low": np.quantile(mean_return, 0.025),
        "return_ci_high": np.quantile(mean_return, 0.975),
        "win_rate_pct": (horizon_frame["return_pct"] > 0).mean() * 100,
        "win_ci_low": np.quantile(win_rate, 0.025),
        "win_ci_high": np.quantile(win_rate, 0.975),
        "mean_excess_pct": horizon_frame["excess_return_pct"].mean(),
        "excess_ci_low": np.quantile(mean_excess, 0.025),
        "excess_ci_high": np.quantile(mean_excess, 0.975),
    })

bootstrap = pd.DataFrame(bootstrap_rows).round(3)
display(bootstrap)
"""
    ),
    markdown("## Execution consistency: recorded signal price vs evaluated entry close"),
    code(
        """
history_unique = (history.sort_values("created_at")
                  .drop_duplicates(history_run_key, keep="last"))
h1 = raw.loc[raw["horizon"] == 1].drop_duplicates(performance_run_key, keep="last")
entry = history_unique.merge(
    h1[["run_id", "code", "source_norm", "entry_close"]],
    on=["run_id", "code", "source_norm"],
    how="inner",
)
entry["entry_gap_pct"] = (entry["entry_close"] / entry["price"] - 1) * 100
entry["same_close_1bp"] = entry["entry_gap_pct"].abs() <= 0.01
entry["is_weekend"] = pd.to_datetime(entry["date"].astype(str)).dt.dayofweek >= 5

entry_summary = pd.DataFrame([{
    "matched_signals": len(entry),
    "same_close_within_1bp": int(entry["same_close_1bp"].sum()),
    "same_close_share_pct": entry["same_close_1bp"].mean() * 100,
    "mean_entry_gap_pct": entry["entry_gap_pct"].mean(),
    "min_entry_gap_pct": entry["entry_gap_pct"].min(),
    "max_entry_gap_pct": entry["entry_gap_pct"].max(),
    "weekend_signals": int(entry["is_weekend"].sum()),
}]).round(3)
display(entry_summary)

entry_by_run = (entry.groupby("run_id", as_index=False)
                .agg(signals=("code", "size"),
                     mean_entry_gap_pct=("entry_gap_pct", "mean"),
                     same_close_share_pct=("same_close_1bp", lambda s: s.mean() * 100),
                     weekend_signals=("is_weekend", "sum")))
display(entry_by_run.round(3))
"""
    ),
    markdown("## Score discrimination and transaction-cost sensitivity"),
    code(
        """
score_rows = history_unique[["run_id", "code", "source_norm", "score"]].merge(
    raw[["run_id", "code", "source_norm", "horizon", "return_pct"]],
    on=["run_id", "code", "source_norm"],
    how="inner",
)
core_scores = score_rows[score_rows["source_norm"] == "core"]
score_quality = []
for horizon, group in core_scores.groupby("horizon"):
    score_quality.append({
        "horizon": int(horizon),
        "rows": len(group),
        "unique_scores": group["score"].nunique(),
        "score_100_share_pct": (group["score"] == 100).mean() * 100,
        "spearman_score_vs_return": group["score"].rank(method="average").corr(
            group["return_pct"].rank(method="average")
        ),
    })
display(pd.DataFrame(score_quality).round(3))

cost_pp = 0.6
cost_sensitivity = pd.DataFrame([
    {
        "view": "run-level rows",
        "gross_mean_pct": raw["return_pct"].mean(),
        "net_mean_pct_at_0_6pp": (raw["return_pct"] - cost_pp).mean(),
        "gross_win_rate_pct": (raw["return_pct"] > 0).mean() * 100,
        "net_win_rate_pct_at_0_6pp": (raw["return_pct"] > cost_pp).mean() * 100,
    },
    {
        "view": "date-level dedup rows",
        "gross_mean_pct": date_dedup["return_pct"].mean(),
        "net_mean_pct_at_0_6pp": (date_dedup["return_pct"] - cost_pp).mean(),
        "gross_win_rate_pct": (date_dedup["return_pct"] > 0).mean() * 100,
        "net_win_rate_pct_at_0_6pp": (date_dedup["return_pct"] > cost_pp).mean() * 100,
    },
]).round(3)
display(cost_sensitivity)
"""
    ),
    markdown(
        """
## Takeaways

1. **Do not optimize the selector against the current headline win rate.** First fix the measurement contract: one immutable signal ID, explicit live/research environment, strategy version, fixed next-tradable-price entry, transaction costs, and chronological cohorts.
2. **Separate the core list and small/mid-cap radar.** The local sample says they have opposite behavior, and the radar has only two signal dates. Keep it in shadow mode until it passes an independent readiness gate.
3. **Use net excess expectancy as the primary outcome.** Keep win rate secondary and always label the horizon, sample size, signal dates, confidence interval, execution rule, and strategy version.
4. **Replace points with a calibrated ranking baseline only after measurement is fixed.** Use walk-forward splits, probability calibration, and ablation tests for technical, fundamental, and news feature families.
5. **Interpret this as a product-quality audit, not a trading recommendation.** The data is local, stale relative to the audit date, and may not match the Raspberry Pi production state.
"""
    ),
]

nbf.validate(nb)
nbf.write(nb, OUTPUT)

client = NotebookClient(nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}})
client.execute(cwd=str(ROOT))
nbf.validate(nb)
nbf.write(nb, OUTPUT)
print(f"Wrote and executed {OUTPUT}")
