from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
import yfinance as yf

from strategy_contract import (
    EARLY_WATCH_CHANNEL,
    LIVE_ENVIRONMENT,
    PERFORMANCE_SCHEMA_VERSION,
    PRIMARY_CHANNEL,
    SHADOW_CHANNEL,
    SIGNAL_SCHEMA_VERSION,
    STRATEGY_VERSION,
    CostAssumptions,
    build_run_id,
    build_signal_id,
    calculate_net_trade_return,
    entry_rule_for_mode,
    public_cost_assumptions,
)
from universe import tw_code_to_yahoo_symbol


SIGNAL_HISTORY_FILE = "signal_history.jsonl"
SIGNAL_PERFORMANCE_FILE = "signal_performance.jsonl"
EARLY_WATCH_HISTORY_FILE = "early_watch_history.jsonl"
EARLY_WATCH_PERFORMANCE_FILE = "early_watch_performance.jsonl"
HORIZONS = (1, 3, 5, 10)
PRIMARY_HORIZON = int(os.getenv("PERFORMANCE_PRIMARY_HORIZON", "5"))


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


def _append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _decision_at(snapshot: dict[str, Any]) -> str:
    raw = str(snapshot.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        parsed = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        parsed = datetime.now()
    return parsed.isoformat(timespec="seconds")


def _parse_snapshot_date(snapshot: dict[str, Any]) -> str:
    return _decision_at(snapshot)[:10]


def append_signal_history(
    snapshot: dict[str, Any],
    path: str | Path = SIGNAL_HISTORY_FILE,
    *,
    execution_environment: str | None = None,
    run_type: str | None = None,
    strategy_version: str | None = None,
) -> int:
    return _append_signal_rows(
        snapshot,
        path,
        _iter_snapshot_signals(snapshot),
        execution_environment=execution_environment,
        run_type=run_type,
        strategy_version=strategy_version,
    )


def append_early_watch_history(
    snapshot: dict[str, Any],
    path: str | Path = EARLY_WATCH_HISTORY_FILE,
    *,
    execution_environment: str | None = None,
    run_type: str | None = None,
    strategy_version: str | None = None,
) -> int:
    return _append_signal_rows(
        snapshot,
        path,
        _iter_early_watch_signals(snapshot),
        execution_environment=execution_environment,
        run_type=run_type,
        strategy_version=strategy_version,
    )


def _append_signal_rows(
    snapshot: dict[str, Any],
    path: str | Path,
    signals: list[tuple[int, dict[str, Any]]],
    *,
    execution_environment: str | None,
    run_type: str | None,
    strategy_version: str | None,
) -> int:
    context = dict(snapshot.get("run_context") or {})
    environment = (execution_environment or context.get("execution_environment") or "research").lower()
    resolved_run_type = (run_type or context.get("run_type") or "manual").lower()
    version = strategy_version or context.get("strategy_version") or STRATEGY_VERSION

    # Defense in depth: a dry/research execution is never allowed into the formal ledger.
    if environment != LIVE_ENVIRONMENT or resolved_run_type in {"dry_run", "research", "backfill"}:
        return 0

    decision_at = _decision_at(snapshot)
    signal_date = decision_at[:10]
    mode = str(snapshot.get("mode") or "").upper()
    run_id = build_run_id(
        decision_at=decision_at,
        mode=mode,
        execution_environment=environment,
        run_type=resolved_run_type,
        strategy_version=version,
    )
    existing = {
        str(row.get("signal_id"))
        for row in _read_jsonl(path)
        if row.get("signal_id")
    }

    rows: list[dict[str, Any]] = []
    for rank, item in signals:
        code = str(item.get("code") or "")
        if not code:
            continue
        channel = str(item.get("candidate_channel") or PRIMARY_CHANNEL)
        signal_id = build_signal_id(
            run_id=run_id,
            code=code,
            candidate_channel=channel,
            strategy_version=version,
        )
        if signal_id in existing:
            continue
        rows.append(
            {
                "schema_version": SIGNAL_SCHEMA_VERSION,
                "signal_id": signal_id,
                "run_id": run_id,
                "decision_at": decision_at,
                "date": signal_date,
                "mode": mode,
                "entry_rule": entry_rule_for_mode(mode),
                "execution_environment": environment,
                "run_type": resolved_run_type,
                "strategy_version": version,
                "feature_version": item.get("feature_version") or context.get("feature_version"),
                "candidate_channel": channel,
                "source": item.get("source", "core"),
                "code": code,
                "name": item.get("name"),
                "rank": item.get("rank") or item.get("small_mid_rank") or rank,
                "score": item.get("score"),
                "small_mid_score": item.get("small_mid_score"),
                "entry_score": item.get("entry_score"),
                "entry_status": item.get("entry_status"),
                "early_watch_score": item.get("early_watch_score"),
                "entry_plan": item.get("entry_plan") or {},
                "theme": item.get("theme"),
                "decision_price": item.get("price"),
                "pct_1d": item.get("pct_1d"),
                "avg_turnover_million": item.get("avg_turnover_million"),
                "feature_vector": item.get("feature_vector") or {},
                "reasons": item.get("reasons", []),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        existing.add(signal_id)
    _append_jsonl(path, rows)
    return len(rows)


def _iter_snapshot_signals(snapshot: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    signals: list[tuple[int, dict[str, Any]]] = []
    has_actionable_contract = "actionable_candidates" in snapshot
    primary_items = (
        snapshot.get("actionable_candidates", [])
        if has_actionable_contract
        else snapshot.get("tw_candidates", [])
    )
    for rank, item in enumerate(primary_items, start=1):
        if item.get("eligible_for_performance") is False:
            continue
        copied = dict(item)
        copied["source"] = item.get("source") or (
            "entry_opportunity" if has_actionable_contract else "core"
        )
        copied["candidate_channel"] = PRIMARY_CHANNEL
        signals.append((rank, copied))

    for rank, item in enumerate(snapshot.get("small_mid_candidates", []), start=1):
        if item.get("eligible_for_performance") is False:
            continue
        copied = dict(item)
        copied["source"] = "small_mid_radar"
        copied["candidate_channel"] = SHADOW_CHANNEL
        copied["rank"] = copied.get("small_mid_rank") or rank
        signals.append((rank, copied))
    return signals


def _iter_early_watch_signals(
    snapshot: dict[str, Any],
) -> list[tuple[int, dict[str, Any]]]:
    signals: list[tuple[int, dict[str, Any]]] = []
    for rank, item in enumerate(snapshot.get("early_watch_candidates", []), start=1):
        if item.get("eligible_for_performance") is False:
            continue
        copied = dict(item)
        copied["source"] = item.get("source") or "early_watch"
        copied["candidate_channel"] = EARLY_WATCH_CHANNEL
        copied["rank"] = copied.get("early_watch_rank") or rank
        signals.append((rank, copied))
    return signals


@lru_cache(maxsize=128)
def _history_for_symbol(symbol: str) -> pd.DataFrame:
    try:
        history = yf.Ticker(symbol).history(period="6mo", auto_adjust=False)
        if history is None or history.empty:
            return pd.DataFrame()
        history = history.dropna(subset=["Close"]).copy()
        history.index = pd.to_datetime(history.index).tz_localize(None)
        return history
    except Exception as exc:
        print(f"[signal_tracker] history fetch failed for {symbol}: {exc}")
        return pd.DataFrame()


def _history_for_code(code: str) -> pd.DataFrame:
    return _history_for_symbol(tw_code_to_yahoo_symbol(code))


def _entry_for_signal(
    history: pd.DataFrame,
    signal_date: pd.Timestamp,
    mode: str,
) -> tuple[int, pd.Timestamp, float, str] | None:
    normalized = history.index.normalize()
    if str(mode).upper() == "POST":
        positions = [index for index, date in enumerate(normalized) if date > signal_date.normalize()]
    else:
        positions = [index for index, date in enumerate(normalized) if date >= signal_date.normalize()]
    if not positions:
        return None
    position = positions[0]
    row = history.iloc[position]
    open_price = _positive_float(row.get("Open"))
    if open_price is not None:
        return position, history.index[position], open_price, "Open"
    close_price = _positive_float(row.get("Close"))
    if close_price is None:
        return None
    return position, history.index[position], close_price, "Close_fallback"


def _performance_rows_for_signal(
    signal: dict[str, Any],
    assumptions: CostAssumptions | None = None,
) -> list[dict[str, Any]]:
    if signal.get("schema_version") != SIGNAL_SCHEMA_VERSION:
        return []
    if signal.get("execution_environment") != LIVE_ENVIRONMENT:
        return []
    if signal.get("run_type") in {"dry_run", "research", "backfill"}:
        return []

    code = str(signal.get("code") or "")
    if not code:
        return []
    history = _history_for_code(code)
    if history.empty:
        return []
    benchmark = _history_for_symbol("^TWII")

    signal_date = pd.to_datetime(signal.get("date"), errors="coerce")
    if pd.isna(signal_date):
        return []
    entry = _entry_for_signal(history, signal_date, str(signal.get("mode") or ""))
    if entry is None:
        return []
    entry_position, entry_date, entry_price, entry_field = entry
    assumptions = assumptions or CostAssumptions.from_env()

    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        exit_position = entry_position + horizon
        if exit_position >= len(history):
            continue
        exit_price = _positive_float(history.iloc[exit_position].get("Close"))
        if exit_price is None:
            continue
        exit_date = history.index[exit_position]
        trade = calculate_net_trade_return(entry_price, exit_price, assumptions)
        benchmark_return_pct = _benchmark_return_pct(benchmark, entry_date, exit_date)
        gross_excess = None
        net_excess = None
        if benchmark_return_pct is not None:
            gross_excess = trade["gross_return_pct"] - benchmark_return_pct
            net_excess = trade["net_return_pct"] - benchmark_return_pct
        rows.append(
            {
                "schema_version": PERFORMANCE_SCHEMA_VERSION,
                "signal_id": signal.get("signal_id"),
                "run_id": signal.get("run_id"),
                "date": signal.get("date"),
                "decision_at": signal.get("decision_at"),
                "mode": signal.get("mode"),
                "entry_rule": signal.get("entry_rule"),
                "execution_environment": signal.get("execution_environment"),
                "run_type": signal.get("run_type"),
                "strategy_version": signal.get("strategy_version"),
                "feature_version": signal.get("feature_version"),
                "candidate_channel": signal.get("candidate_channel", PRIMARY_CHANNEL),
                "source": signal.get("source", "core"),
                "code": code,
                "name": signal.get("name"),
                "rank": signal.get("rank"),
                "score": signal.get("score"),
                "theme": signal.get("theme"),
                "avg_turnover_million": signal.get("avg_turnover_million"),
                "feature_vector": signal.get("feature_vector") or {},
                "horizon": horizon,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "entry_price": round(entry_price, 4),
                "entry_price_field": entry_field,
                "exit_date": exit_date.strftime("%Y-%m-%d"),
                "exit_price": round(exit_price, 4),
                "gross_return_pct": round(trade["gross_return_pct"], 4),
                "transaction_cost_pct": round(trade["transaction_cost_pct"], 4),
                "net_return_pct": round(trade["net_return_pct"], 4),
                # Compatibility aliases intentionally point to the net metrics in schema v2.
                "return_pct": round(trade["net_return_pct"], 4),
                "benchmark_return_pct": _rounded(benchmark_return_pct, 4),
                "gross_excess_return_pct": _rounded(gross_excess, 4),
                "net_excess_return_pct": _rounded(net_excess, 4),
                "excess_return_pct": _rounded(net_excess, 4),
                "evaluated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    return rows


def _benchmark_return_pct(
    benchmark: pd.DataFrame,
    entry_date: pd.Timestamp,
    exit_date: pd.Timestamp,
) -> float | None:
    if benchmark.empty:
        return None
    normalized = benchmark.index.normalize()
    entry_positions = [index for index, date in enumerate(normalized) if date >= entry_date.normalize()]
    exit_positions = [index for index, date in enumerate(normalized) if date <= exit_date.normalize()]
    if not entry_positions or not exit_positions:
        return None
    entry_position = entry_positions[0]
    exit_position = exit_positions[-1]
    if exit_position < entry_position:
        return None
    entry_price = _positive_float(benchmark.iloc[entry_position].get("Open"))
    if entry_price is None:
        entry_price = _positive_float(benchmark.iloc[entry_position].get("Close"))
    exit_price = _positive_float(benchmark.iloc[exit_position].get("Close"))
    if entry_price is None or exit_price is None:
        return None
    return (exit_price / entry_price - 1.0) * 100.0


def evaluate_signal_performance(
    history_path: str | Path = SIGNAL_HISTORY_FILE,
    performance_path: str | Path = SIGNAL_PERFORMANCE_FILE,
    *,
    execution_environment: str = LIVE_ENVIRONMENT,
) -> int:
    if execution_environment != LIVE_ENVIRONMENT:
        return 0
    signals = [
        row
        for row in _read_jsonl(history_path)
        if row.get("schema_version") == SIGNAL_SCHEMA_VERSION
        and row.get("execution_environment") == LIVE_ENVIRONMENT
        and row.get("run_type") not in {"dry_run", "research", "backfill"}
    ]
    existing = {
        (row.get("signal_id"), row.get("horizon"))
        for row in _read_jsonl(performance_path)
        if row.get("signal_id")
    }
    rows: list[dict[str, Any]] = []
    for signal in signals:
        try:
            performance_rows = _performance_rows_for_signal(signal)
        except Exception as exc:
            print(f"[signal_tracker] skip signal {signal.get('code')}: {exc}")
            continue
        for row in performance_rows:
            key = (row.get("signal_id"), row.get("horizon"))
            if key not in existing:
                rows.append(row)
                existing.add(key)
    _append_jsonl(performance_path, rows)
    return len(rows)


def summarize_performance(
    performance_path: str | Path = SIGNAL_PERFORMANCE_FILE,
    lookback: int = 200,
    *,
    execution_environment: str = LIVE_ENVIRONMENT,
    candidate_channel: str = PRIMARY_CHANNEL,
    strategy_version: str = STRATEGY_VERSION,
    primary_horizon: int = PRIMARY_HORIZON,
) -> dict[str, Any]:
    all_rows = _read_jsonl(performance_path)
    contract_rows = [
        row
        for row in all_rows
        if row.get("schema_version") == PERFORMANCE_SCHEMA_VERSION
        and row.get("execution_environment") == execution_environment
        and row.get("candidate_channel") == candidate_channel
        and row.get("strategy_version") == strategy_version
        and row.get("net_return_pct") is not None
    ]
    rows = _last_signal_rows(contract_rows, lookback)
    legacy_excluded = sum(
        1 for row in all_rows if row.get("schema_version") != PERFORMANCE_SCHEMA_VERSION
    )
    base = {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "execution_environment": execution_environment,
        "candidate_channel": candidate_channel,
        "strategy_version": strategy_version,
        "primary_horizon": primary_horizon,
        "cost_assumptions": public_cost_assumptions(),
        "legacy_rows_excluded": legacy_excluded,
    }
    if not rows:
        return {**base, "count": 0, "signal_dates": 0, "status": "collecting"}

    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in HORIZONS:
        subset = [row for row in rows if int(row.get("horizon") or -1) == horizon]
        if subset:
            by_horizon[str(horizon)] = _stats(subset)

    primary_rows = [
        row for row in rows if int(row.get("horizon") or -1) == primary_horizon
    ]
    if not primary_rows:
        available_horizons = sorted(by_horizon, key=int)
        if not available_horizons:
            return {**base, "count": 0, "signal_dates": 0, "status": "collecting"}
        fallback = available_horizons[-1]
        primary_rows = [row for row in rows if str(row.get("horizon")) == fallback]
        primary_horizon = int(fallback)
        base["primary_horizon"] = primary_horizon

    primary_stats = _stats(primary_rows)
    equity = _equity_curve_metrics(primary_rows)
    themes = _group_stats(primary_rows, "theme")

    return {
        **base,
        "status": "ready" if primary_stats["signal_dates"] >= 20 else "collecting",
        "count": primary_stats["count"],
        "signal_dates": primary_stats["signal_dates"],
        "gross_avg_return_pct": primary_stats["gross_avg_return_pct"],
        "net_avg_return_pct": primary_stats["net_avg_return_pct"],
        "net_excess_expectancy_pct": primary_stats["net_excess_expectancy_pct"],
        "median_net_excess_return_pct": primary_stats["median_net_excess_return_pct"],
        "win_rate": primary_stats["win_rate"],
        "excess_win_rate": primary_stats["excess_win_rate"],
        "profit_factor": primary_stats["profit_factor"],
        "max_drawdown_pct": equity["max_drawdown_pct"],
        "equity_curve": equity["equity_curve"],
        "capital_curve_method": equity["method"],
        "capital_curve_cohorts": equity["cohort_count"],
        "by_horizon": by_horizon,
        "theme_performance": themes,
    }


def _last_signal_rows(rows: list[dict[str, Any]], lookback: int) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row.get("entry_date") or row.get("date") or ""),
            str(row.get("signal_id") or ""),
            int(row.get("horizon") or 0),
        ),
    )
    signal_ids: list[str] = []
    seen: set[str] = set()
    for row in reversed(ordered):
        signal_id = str(row.get("signal_id") or "")
        if signal_id and signal_id not in seen:
            signal_ids.append(signal_id)
            seen.add(signal_id)
        if len(signal_ids) >= lookback:
            break
    selected = set(signal_ids)
    return [row for row in ordered if row.get("signal_id") in selected]


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    net_returns = [float(row["net_return_pct"]) for row in rows if row.get("net_return_pct") is not None]
    gross_returns = [float(row["gross_return_pct"]) for row in rows if row.get("gross_return_pct") is not None]
    net_excess = [
        float(row["net_excess_return_pct"])
        for row in rows
        if row.get("net_excess_return_pct") is not None
    ]
    gains = sum(value for value in net_returns if value > 0)
    losses = abs(sum(value for value in net_returns if value < 0))
    return {
        "count": len(net_returns),
        "signal_dates": len({str(row.get("entry_date") or row.get("date")) for row in rows}),
        "gross_avg_return_pct": _average(gross_returns),
        "net_avg_return_pct": _average(net_returns),
        "net_excess_expectancy_pct": _average(net_excess),
        "median_net_excess_return_pct": None if not net_excess else round(median(net_excess), 2),
        "win_rate": _rate(net_returns),
        "excess_win_rate": _rate(net_excess),
        "profit_factor": None if losses == 0 else round(gains / losses, 3),
    }


def _group_stats(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "未分類")].append(row)
    return dict(
        sorted(
            ((name, _stats(items)) for name, items in grouped.items()),
            key=lambda item: item[1].get("net_excess_expectancy_pct")
            if item[1].get("net_excess_expectancy_pct") is not None
            else -999.0,
            reverse=True,
        )
    )


def _equity_curve_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("entry_date") and row.get("exit_date") and row.get("net_return_pct") is not None:
            grouped[str(row["entry_date"])].append(row)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    previous_exit: str | None = None
    curve: list[dict[str, Any]] = []
    for entry_date in sorted(grouped):
        cohort = grouped[entry_date]
        if previous_exit is not None and entry_date <= previous_exit:
            continue
        cohort_return = sum(float(row["net_return_pct"]) for row in cohort) / len(cohort)
        equity *= 1.0 + cohort_return / 100.0
        peak = max(peak, equity)
        drawdown = (equity / peak - 1.0) * 100.0
        max_drawdown = min(max_drawdown, drawdown)
        exit_date = max(str(row["exit_date"]) for row in cohort)
        curve.append(
            {
                "entry_date": entry_date,
                "exit_date": exit_date,
                "net_return_pct": round(cohort_return, 4),
                "equity": round(equity, 6),
                "drawdown_pct": round(drawdown, 4),
                "positions": len(cohort),
            }
        )
        previous_exit = exit_date
    return {
        "method": "non_overlapping_equal_weight_cohorts",
        "cohort_count": len(curve),
        "max_drawdown_pct": round(max_drawdown, 2) if curve else None,
        "equity_curve": curve[-120:],
    }


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0) / len(values), 4)
