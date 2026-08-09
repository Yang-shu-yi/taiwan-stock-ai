import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import twstock
import yfinance as yf

from data_layer import twse_json
from company_assessment import build_company_assessment
from daily_quote_overlay import (
    load_official_daily_quotes,
    market_index_quote,
    overlay_latest_quote,
)
from entry_opportunity import (
    EARLY_WATCH_STATUS,
    SCALE_IN_STATUS,
    evaluate_entry_opportunity,
)
from small_mid_cap_radar import build_small_mid_cap_radar
from stock_analyzer import get_revenue_snapshot
from strategy_contract import (
    EARLY_WATCH_CHANNEL,
    PRIMARY_CHANNEL,
    SHADOW_CHANNEL,
    resolve_run_context,
)
from strategy_features import (
    build_model_feature_vector,
    canonical_reasons,
    extract_market_features,
    score_canonical_features,
)
from universe import (
    get_theme_for_code,
    get_tw_core_codes,
    get_tw_name,
    get_us_context_symbols,
    tw_code_to_yahoo_symbol,
)


DEFAULT_SNAPSHOT_FILE = os.getenv("DAILY_CANDIDATES_FILE", "runtime/daily_candidates.json")
LOCAL_TZ = ZoneInfo("Asia/Taipei")


def _safe_float(value: Any, digits: int = 2) -> float | None:
    try:
        return round(float(str(value).replace(",", "").replace("%", "")), digits)
    except Exception:
        return None


def _news_hits(news_items: list[dict[str, Any]], keywords: list[str]) -> int:
    normalized = [keyword.lower() for keyword in keywords if keyword]
    hits = 0
    for item in news_items:
        haystack = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("summary", "")),
            ]
        ).lower()
        if any(keyword in haystack for keyword in normalized):
            hits += 1
    return hits


def _recent_history(symbol: str, period: str = "6mo") -> pd.DataFrame | None:
    try:
        history = yf.Ticker(symbol).history(period=period, auto_adjust=False)
        if history is None or history.empty:
            return None
        return history.dropna(subset=["Close"]).copy()
    except Exception:
        return None


def _history_trading_date(history: pd.DataFrame | None) -> str | None:
    if history is None or history.empty:
        return None
    try:
        return pd.Timestamp(history.index[-1]).date().isoformat()
    except Exception:
        return None


def _daily_metrics(
    history: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
) -> dict[str, float | None] | None:
    return extract_market_features(history, benchmark)


def _score_tw_candidate(
    code: str,
    news_items: list[dict[str, Any]],
    benchmark: pd.DataFrame | None = None,
    latest_quote: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    symbol = tw_code_to_yahoo_symbol(code)
    history = _recent_history(symbol)
    history = overlay_latest_quote(history, latest_quote)
    metrics = _daily_metrics(history, benchmark) if history is not None else None
    if metrics is None:
        return None

    name = get_tw_name(code)
    theme = get_theme_for_code(code)
    hits = _news_hits(news_items, [code, name, theme])
    info = twstock.codes.get(code)
    revenue = get_revenue_snapshot(code, info.market) if info is not None else {}
    score_result = score_canonical_features(metrics, revenue)
    final_score = score_result["score"]
    entry = evaluate_entry_opportunity(metrics, final_score)
    company_assessment = build_company_assessment(
        code=code,
        name=name,
        market=info.market if info is not None else "",
        revenue=revenue,
        metrics=metrics,
        entry=entry,
        news_items=news_items,
    )
    reasons = canonical_reasons(metrics)
    invalidations = _candidate_invalidations(metrics, entry)
    risk_flags = _unique_text(
        [
            *entry["entry_risk_flags"],
            *_candidate_risk_flags(metrics),
        ]
    )
    return {
        "code": code,
        "name": name,
        "theme": theme,
        "industry": getattr(info, "group", "") if info is not None else "",
        "symbol": symbol,
        "score": final_score,
        "score_components": score_result["components"],
        "feature_version": score_result["feature_version"],
        "feature_vector": build_model_feature_vector(metrics, revenue),
        "candidate_channel": PRIMARY_CHANNEL,
        "source": "core",
        "confidence": _confidence_label(
            final_score,
            metrics,
            hits,
            entry["entry_status"],
        ),
        "price": _safe_float(metrics["price"]),
        "price_date": _history_trading_date(history),
        "pct_1d": _safe_float(metrics["pct_1d"]),
        "pct_5d": _safe_float(metrics["pct_5d"]),
        "pct_20d": _safe_float(metrics["pct_20d"]),
        "rs_20d": _safe_float(metrics["rs_20d"]),
        "rsi": _safe_float(metrics["rsi"]),
        "vol_ratio": _safe_float(metrics["vol_ratio"]),
        "avg_turnover_million": _safe_float(metrics["avg_turnover_million"]),
        "news_hits": hits,
        "revenue": revenue,
        "company_assessment": company_assessment,
        "company_quality_score": company_assessment["company_quality_score"],
        "valuation_attractiveness_score": company_assessment["valuation_attractiveness_score"],
        "entry_timing_score": company_assessment["entry_timing_score"],
        "event_risk_level": company_assessment["event_risk_level"],
        "opportunity_label": company_assessment["opportunity_label"],
        "plain_language_advice": company_assessment["plain_language_advice"],
        "fundamental_summary": company_assessment["fundamental_summary"],
        "valuation_summary": company_assessment["valuation_summary"],
        "reasons": reasons[:4],
        "risk_flags": risk_flags,
        "invalidations": invalidations,
        "data_quality": "正常",
        **entry,
    }


def _confidence_label(
    score: float,
    metrics: dict[str, float | None],
    news_hits: int,
    entry_status: str,
) -> str:
    if (
        entry_status == SCALE_IN_STATUS
        and score >= 78
        and metrics["price"] > metrics["ma20"]
        and metrics["price"] > metrics["ma60"]
    ):
        return "高"
    if entry_status in {SCALE_IN_STATUS, EARLY_WATCH_STATUS} or news_hits:
        return "中"
    return "低"


def _candidate_risk_flags(metrics: dict[str, float | None]) -> list[str]:
    flags: list[str] = []
    if metrics["rsi"] >= 78:
        flags.append("RSI 偏熱，避免追高")
    if metrics["vol_ratio"] < 0.8:
        flags.append("量能不足，續航需確認")
    if metrics["price"] < metrics["ma20"]:
        flags.append("尚未站回 MA20")
    if metrics["pct_1d"] <= -4:
        flags.append("單日回檔過深")
    return flags or ["未見明顯短線破壞訊號"]


def _candidate_invalidations(
    metrics: dict[str, float | None],
    entry: dict[str, Any] | None = None,
) -> list[str]:
    invalidations = []
    stop_price = (entry or {}).get("entry_plan", {}).get("stop_price")
    if stop_price:
        invalidations.append(f"跌破規劃停損 {float(stop_price):.2f}")
    if metrics["ma20"]:
        invalidations.append(f"跌破 MA20 {metrics['ma20']:.2f}")
    if metrics["ma60"]:
        invalidations.append(f"跌破 MA60 {metrics['ma60']:.2f}")
    if metrics["rsi"] >= 75:
        invalidations.append("隔日開高量縮且 RSI 過熱")
    return invalidations[:2] or ["跌破前一交易日低點"]


def _unique_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:4]


def _score_us_context(symbol: str, news_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    history = _recent_history(symbol)
    metrics = _daily_metrics(history) if history is not None else None
    if metrics is None:
        return None

    score = 20
    reasons: list[str] = []

    if metrics["price"] > metrics["ma20"]:
        score += 12
        reasons.append("站上 MA20")
    if metrics["price"] > metrics["ma60"]:
        score += 12
        reasons.append("站上 MA60")
    if metrics["pct_5d"] > 1:
        score += 10
        reasons.append("近 5 日偏強")
    if metrics["vol_ratio"] >= 1.3:
        score += 8
        reasons.append("量能放大")
    if metrics["rsi"] > 78:
        score -= 6
        reasons.append("RSI 偏熱")

    hits = _news_hits(news_items, [symbol])
    if hits:
        score += min(hits * 4, 12)

    return {
        "symbol": symbol,
        "name": symbol,
        "score": max(0, min(score, 100)),
        "price": _safe_float(metrics["price"]),
        "pct_1d": _safe_float(metrics["pct_1d"]),
        "pct_5d": _safe_float(metrics["pct_5d"]),
        "reasons": reasons[:3],
    }


def _theme_summary(
    candidates: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    news_titles = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')}" for item in news_items
    ).lower()

    for candidate in candidates:
        theme = candidate.get("theme", "電子")
        grouped[theme].append(candidate)

    keyword_map = {
        "半導體": ["半導體", "晶圓", "晶片", "foundry", "chip"],
        "記憶體": ["記憶體", "dram", "nand", "memory"],
        "AI伺服器": ["ai server", "伺服器", "機櫃", "資料中心"],
        "PCB/ABF": ["abf", "pcb", "載板", "基板"],
        "塑化": ["塑化", "油價", "原料"],
        "航運": ["航運", "貨櫃", "運價"],
    }
    scored: list[tuple[float, str, list[dict[str, Any]], bool]] = []
    for theme, items in grouped.items():
        ordered_items = sorted(items, key=lambda item: float(item.get("score") or 0), reverse=True)
        top_items = ordered_items[:3]
        mean_score = sum(float(item.get("score") or 0) for item in top_items) / len(top_items)
        mean_momentum = sum(
            max(-10.0, min(float(item.get("pct_5d") or 0), 10.0))
            for item in top_items
        ) / len(top_items)
        momentum_score = (mean_momentum + 10.0) / 20.0 * 100.0
        news_match = any(
            keyword.lower() in news_titles
            for keyword in keyword_map.get(theme, [])
        )
        # Breadth is reported, not rewarded: themes with more constituents no longer win by summation.
        theme_score = mean_score * 0.85 + momentum_score * 0.10 + (100.0 if news_match else 0.0) * 0.05
        scored.append((theme_score, theme, ordered_items, news_match))

    ordered = sorted(scored, key=lambda item: item[0], reverse=True)
    result: list[dict[str, Any]] = []
    for score, theme, items, news_match in ordered[:3]:
        result.append(
            {
                "theme": theme,
                "score": round(max(0.0, min(score, 100.0)), 1),
                "breadth": len(items),
                "news_match": news_match,
                "leaders": [f"{item['code']} {item['name']}" for item in items[:3]],
            }
        )
    return result


def _dynamic_market_codes(limit: int) -> list[str]:
    if limit <= 0:
        return []
    try:
        rows = twse_json(
            "twse_market_snapshot",
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            ttl_minutes=15,
        )
    except Exception:
        return []
    if not isinstance(rows, list):
        return []

    raw_candidates: list[tuple[str, float, float]] = []
    for row in rows:
        code = str(row.get("Code") or row.get("證券代號") or "").strip()
        if not code.isdigit():
            continue
        trade_value = _safe_float(row.get("TradeValue") or row.get("成交金額"), digits=0) or 0
        if trade_value <= 0:
            continue
        change_pct = _market_change_pct(row)
        raw_candidates.append((code, trade_value, change_pct))

    if not raw_candidates:
        return []
    turnover_values = [item[1] for item in raw_candidates]
    change_values = [item[2] for item in raw_candidates]
    scored: list[tuple[float, str]] = []
    for code, trade_value, change_pct in raw_candidates:
        turnover_rank = _percentile_rank(trade_value, turnover_values)
        return_rank = _percentile_rank(change_pct, change_values)
        score = turnover_rank * 0.75 + return_rank * 0.25
        scored.append((score, code))
    scored.sort(reverse=True)
    return [code for _, code in scored[:limit]]


def _market_change_pct(row: dict[str, Any]) -> float:
    explicit = _safe_float(
        row.get("ChangePercent")
        or row.get("ChangePercentage")
        or row.get("漲跌百分比")
        or row.get("漲跌幅"),
        digits=6,
    )
    if explicit is not None:
        return explicit
    close = _safe_float(row.get("ClosingPrice") or row.get("收盤價"), digits=6)
    change = _safe_float(row.get("Change") or row.get("漲跌價差"), digits=6)
    if close is None or change is None:
        return 0.0
    sign = str(row.get("Sign") or row.get("漲跌(+/-)") or "").strip()
    if "-" in sign and change > 0:
        change = -change
    previous_close = close - change
    if previous_close <= 0:
        return 0.0
    return change / previous_close * 100.0


def _percentile_rank(value: float, values: list[float]) -> float:
    if len(values) <= 1:
        return 0.5
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return (below + max(equal - 1, 0) / 2.0) / (len(values) - 1)


def _dynamic_news_codes(news_items: list[dict[str, Any]], limit: int) -> list[str]:
    if limit <= 0:
        return []
    candidates: list[str] = []
    haystack = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')}" for item in news_items
    )
    for code in get_tw_core_codes():
        name = get_tw_name(code)
        theme = get_theme_for_code(code)
        if code in haystack or name in haystack or theme in haystack:
            candidates.append(code)
    return candidates[:limit]


def build_scan_universe(
    tw_news: list[dict[str, Any]],
    official_quotes: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    codes = list(get_tw_core_codes())
    market_limit = int(os.getenv("TW_DYNAMIC_MARKET_LIMIT", "12"))
    news_limit = int(os.getenv("TW_DYNAMIC_NEWS_LIMIT", "12"))
    if official_quotes:
        liquid_quotes = sorted(
            official_quotes.values(),
            key=lambda item: float(item.get("Close") or 0)
            * float(item.get("Volume") or 0),
            reverse=True,
        )
        codes.extend(
            str(item.get("code"))
            for item in liquid_quotes[:market_limit]
            if str(item.get("code") or "").isdigit()
        )
    else:
        codes.extend(_dynamic_market_codes(market_limit))
    codes.extend(_dynamic_news_codes(tw_news, news_limit))
    seen: set[str] = set()
    output: list[str] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        output.append(code)
    return output


def build_daily_snapshot(
    mode: str,
    market: dict[str, Any],
    tw_news: list[dict[str, Any]],
    us_news: list[dict[str, Any]],
    data_status: dict[str, Any] | None = None,
    run_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    market_date = market.get("tw_index", {}).get("trading_date")
    official_quotes = load_official_daily_quotes(market_date)
    benchmark = overlay_latest_quote(
        _recent_history("^TWII"),
        market_index_quote(market, market_date),
    )
    all_tw_candidates = [
        item
        for item in (
            _score_tw_candidate(
                code,
                tw_news,
                benchmark,
                official_quotes.get(code),
            )
            for code in build_scan_universe(tw_news, official_quotes)
        )
        if item is not None
    ]
    scored_candidate_count = len(all_tw_candidates)
    stale_candidate_count = 0
    if market_date:
        current_candidates = [
            item for item in all_tw_candidates if item.get("price_date") == market_date
        ]
        stale_candidate_count = scored_candidate_count - len(current_candidates)
        all_tw_candidates = current_candidates
    all_tw_candidates.sort(
        key=lambda item: (item["score"], item.get("pct_1d") or 0),
        reverse=True,
    )

    for rank, item in enumerate(all_tw_candidates, start=1):
        item["rank"] = rank

    us_context = [
        item
        for item in (_score_us_context(symbol, us_news) for symbol in get_us_context_symbols())
        if item is not None
    ]
    us_context.sort(key=lambda item: (item["score"], item.get("pct_1d") or 0), reverse=True)

    top_tw = int(os.getenv("TW_CANDIDATE_LIMIT", "8"))
    top_us = int(os.getenv("US_CONTEXT_TOP", "6"))
    actionable_limit = int(os.getenv("ACTIONABLE_CANDIDATE_LIMIT", "5"))
    early_watch_limit = int(os.getenv("EARLY_WATCH_LIMIT", "5"))
    selected_tw = all_tw_candidates[:top_tw]
    actionable_candidates = [
        dict(item)
        for item in sorted(
            (
                item
                for item in all_tw_candidates
                if item.get("entry_status") == SCALE_IN_STATUS
            ),
            key=lambda item: (
                float(item.get("entry_score") or 0),
                float(item.get("score") or 0),
            ),
            reverse=True,
        )[:actionable_limit]
    ]
    for rank, item in enumerate(actionable_candidates, start=1):
        item["actionable_rank"] = rank
        item["candidate_channel"] = PRIMARY_CHANNEL
        item["source"] = "entry_opportunity"

    early_watch_candidates = [
        dict(item)
        for item in sorted(
            (
                item
                for item in all_tw_candidates
                if item.get("entry_status") == EARLY_WATCH_STATUS
                and item.get("early_watch_qualified")
            ),
            key=lambda item: (
                float(item.get("early_watch_score") or 0),
                float(item.get("entry_score") or 0),
            ),
            reverse=True,
        )[:early_watch_limit]
    ]
    for rank, item in enumerate(early_watch_candidates, start=1):
        item["early_watch_rank"] = rank
        item["candidate_channel"] = EARLY_WATCH_CHANNEL
        item["source"] = "early_watch"

    small_mid_candidates = build_small_mid_cap_radar(
        tw_news,
        exclude_codes={item.get("code") for item in selected_tw if item.get("code")},
        latest_quotes=official_quotes,
    )
    for item in small_mid_candidates:
        item["candidate_channel"] = SHADOW_CHANNEL
    early_codes = {str(item.get("code") or "") for item in early_watch_candidates}
    for item in small_mid_candidates:
        code = str(item.get("code") or "")
        if (
            code
            and code not in early_codes
            and item.get("entry_status") == EARLY_WATCH_STATUS
            and item.get("early_watch_qualified")
        ):
            copied = dict(item)
            copied["candidate_channel"] = EARLY_WATCH_CHANNEL
            copied["source"] = "early_watch_small_mid"
            early_watch_candidates.append(copied)
            early_codes.add(code)
    early_watch_candidates.sort(
        key=lambda item: (
            float(item.get("early_watch_score") or 0),
            float(item.get("entry_score") or 0),
        ),
        reverse=True,
    )
    early_watch_candidates = early_watch_candidates[:early_watch_limit]
    for rank, item in enumerate(early_watch_candidates, start=1):
        item["early_watch_rank"] = rank
    context = run_context or resolve_run_context(dry_run=False)
    now = datetime.now(LOCAL_TZ)
    if not market_date:
        market_date = next(
            (
                item.get("price_date")
                for item in [
                    *selected_tw,
                    *actionable_candidates,
                    *early_watch_candidates,
                ]
                if item.get("price_date")
            ),
            None,
        )

    return {
        "schema_version": 2,
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at": now.isoformat(timespec="seconds"),
        "report_date": now.strftime("%Y-%m-%d"),
        "market_data_date": market_date,
        "mode": mode,
        "market": market,
        "run_context": context,
        "strategy_version": context.get("strategy_version"),
        "feature_version": context.get("feature_version"),
        "selection_coverage": {
            "scored_count": scored_candidate_count,
            "current_price_count": len(all_tw_candidates),
            "stale_price_excluded_count": stale_candidate_count,
            "required_price_date": market_date,
            "actionable_count": len(actionable_candidates),
            "early_watch_count": len(early_watch_candidates),
        },
        "tw_candidates": selected_tw,
        "actionable_candidates": actionable_candidates,
        "early_watch_candidates": early_watch_candidates,
        "small_mid_candidates": small_mid_candidates,
        "theme_summary": _theme_summary(all_tw_candidates, tw_news),
        "us_context": us_context[:top_us],
        "news_summary": {
            "tw_top_titles": [_news_summary_item(item) for item in tw_news[:5]],
            "us_top_titles": [_news_summary_item(item) for item in us_news[:5]],
        },
        "data_status": data_status or {},
    }


def _news_summary_item(item: dict[str, Any]) -> dict[str, str]:
    return {
        "source": str(item.get("source", "")).strip(),
        "title": str(item.get("title", "")).replace("\n", " ").strip(),
        "url": str(item.get("url", "")).strip(),
        "published": str(item.get("published", "")).strip(),
    }


def save_daily_snapshot(snapshot: dict[str, Any], path: str = DEFAULT_SNAPSHOT_FILE) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)


def load_daily_snapshot(path: str = DEFAULT_SNAPSHOT_FILE) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def get_intraday_focus_codes(limit: int, path: str = DEFAULT_SNAPSHOT_FILE) -> list[str]:
    snapshot = load_daily_snapshot(path)
    candidates = [
        *snapshot.get("actionable_candidates", []),
        *snapshot.get("early_watch_candidates", []),
        *[
            item
            for item in snapshot.get("tw_candidates", [])
            if item.get("entry_status") != "overextended"
        ],
    ]
    if candidates:
        output: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            code = str(item.get("code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            output.append(code)
            if len(output) >= limit:
                break
        return output
    return get_tw_core_codes()[:limit]
