from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from universe import tw_code_to_yahoo_symbol


SIGNAL_HISTORY_FILE = "signal_history.jsonl"
SIGNAL_PERFORMANCE_FILE = "signal_performance.jsonl"
HORIZONS = (1, 3, 5, 10)


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


def _parse_snapshot_date(snapshot: dict[str, Any]) -> str:
    raw = snapshot.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def append_signal_history(
    snapshot: dict[str, Any],
    path: str | Path = SIGNAL_HISTORY_FILE,
) -> int:
    signal_date = _parse_snapshot_date(snapshot)
    mode = snapshot.get("mode", "")
    run_id = f"{signal_date}:{mode}:{snapshot.get('updated_at', '')}"
    existing = {(row.get("run_id"), row.get("code")) for row in _read_jsonl(path)}

    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(snapshot.get("tw_candidates", []), start=1):
        key = (run_id, item.get("code"))
        if key in existing:
            continue
        rows.append(
            {
                "run_id": run_id,
                "date": signal_date,
                "mode": mode,
                "code": item.get("code"),
                "name": item.get("name"),
                "rank": item.get("rank") or rank,
                "score": item.get("score"),
                "theme": item.get("theme"),
                "price": item.get("price"),
                "pct_1d": item.get("pct_1d"),
                "reasons": item.get("reasons", []),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    _append_jsonl(path, rows)
    return len(rows)


def _history_for_code(code: str) -> pd.DataFrame:
    symbol = tw_code_to_yahoo_symbol(code)
    history = yf.Ticker(symbol).history(period="6mo", auto_adjust=False)
    if history is None or history.empty:
        return pd.DataFrame()
    history = history.dropna(subset=["Close"]).copy()
    history.index = pd.to_datetime(history.index).tz_localize(None)
    return history


def _performance_rows_for_signal(signal: dict[str, Any]) -> list[dict[str, Any]]:
    code = str(signal.get("code") or "")
    if not code:
        return []
    history = _history_for_code(code)
    if history.empty:
        return []

    signal_date = pd.to_datetime(signal.get("date"), errors="coerce")
    if pd.isna(signal_date):
        return []
    eligible = history[history.index.normalize() >= signal_date.normalize()]
    if len(eligible) < 2:
        return []

    base_close = float(eligible.iloc[0]["Close"])
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        if len(eligible) <= horizon or not base_close:
            continue
        future_close = float(eligible.iloc[horizon]["Close"])
        return_pct = (future_close / base_close - 1.0) * 100.0
        rows.append(
            {
                "run_id": signal.get("run_id"),
                "date": signal.get("date"),
                "mode": signal.get("mode"),
                "code": code,
                "name": signal.get("name"),
                "rank": signal.get("rank"),
                "theme": signal.get("theme"),
                "horizon": horizon,
                "entry_close": round(base_close, 4),
                "exit_close": round(future_close, 4),
                "return_pct": round(return_pct, 4),
                "evaluated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    return rows


def evaluate_signal_performance(
    history_path: str | Path = SIGNAL_HISTORY_FILE,
    performance_path: str | Path = SIGNAL_PERFORMANCE_FILE,
) -> int:
    signals = _read_jsonl(history_path)
    existing = {
        (row.get("run_id"), row.get("code"), row.get("horizon"))
        for row in _read_jsonl(performance_path)
    }
    rows: list[dict[str, Any]] = []
    for signal in signals:
        for row in _performance_rows_for_signal(signal):
            key = (row.get("run_id"), row.get("code"), row.get("horizon"))
            if key not in existing:
                rows.append(row)
                existing.add(key)
    _append_jsonl(performance_path, rows)
    return len(rows)


def summarize_performance(
    performance_path: str | Path = SIGNAL_PERFORMANCE_FILE,
    lookback: int = 200,
) -> dict[str, Any]:
    rows = _read_jsonl(performance_path)[-lookback:]
    if not rows:
        return {"count": 0}

    returns = [float(row["return_pct"]) for row in rows if row.get("return_pct") is not None]
    if not returns:
        return {"count": 0}

    top3 = [row for row in rows if int(row.get("rank") or 999) <= 3]
    top5 = [row for row in rows if int(row.get("rank") or 999) <= 5]
    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in HORIZONS:
        subset = [row for row in rows if row.get("horizon") == horizon]
        subset_returns = [float(row["return_pct"]) for row in subset if row.get("return_pct") is not None]
        if not subset_returns:
            continue
        by_horizon[str(horizon)] = {
            "count": len(subset_returns),
            "avg_return_pct": round(sum(subset_returns) / len(subset_returns), 2),
            "win_rate": round(sum(1 for value in subset_returns if value > 0) / len(subset_returns), 4),
        }

    return {
        "count": len(returns),
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns), 4),
        "max_drawdown_proxy_pct": round(min(returns), 2),
        "top3_hit_rate": _hit_rate(top3),
        "top5_hit_rate": _hit_rate(top5),
        "by_horizon": by_horizon,
    }


def _hit_rate(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row["return_pct"]) for row in rows if row.get("return_pct") is not None]
    if not values:
        return None
    return round(sum(1 for value in values if value > 0) / len(values), 4)
