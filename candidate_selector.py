import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import ta
import yfinance as yf

from data_layer import twse_json
from universe import (
    get_theme_for_code,
    get_tw_core_codes,
    get_tw_name,
    get_us_context_symbols,
    tw_code_to_yahoo_symbol,
)


DEFAULT_SNAPSHOT_FILE = os.getenv("DAILY_CANDIDATES_FILE", "runtime/daily_candidates.json")


def _safe_float(value: Any, digits: int = 2) -> float | None:
    try:
        return round(float(str(value).replace(",", "")), digits)
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


def _daily_metrics(history: pd.DataFrame) -> dict[str, float] | None:
    if history is None or len(history) < 60:
        return None

    close = history["Close"]
    volume = history["Volume"].fillna(0)
    ma20 = ta.trend.sma_indicator(close, 20).iloc[-1]
    ma60 = ta.trend.sma_indicator(close, 60).iloc[-1]
    rsi = ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1]
    price = close.iloc[-1]
    prev = close.iloc[-2]
    pct_1d = ((price - prev) / prev) * 100 if prev else 0.0
    pct_5d = ((price - close.iloc[-6]) / close.iloc[-6]) * 100 if close.iloc[-6] else 0.0
    avg_vol20 = volume.tail(20).mean()
    vol_ratio = (volume.iloc[-1] / avg_vol20) if avg_vol20 else 1.0

    return {
        "price": float(price),
        "ma20": float(ma20),
        "ma60": float(ma60),
        "rsi": float(rsi),
        "pct_1d": float(pct_1d),
        "pct_5d": float(pct_5d),
        "vol_ratio": float(vol_ratio),
    }


def _score_tw_candidate(code: str, news_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    symbol = tw_code_to_yahoo_symbol(code)
    history = _recent_history(symbol)
    metrics = _daily_metrics(history) if history is not None else None
    if metrics is None:
        return None

    name = get_tw_name(code)
    theme = get_theme_for_code(code)
    score = 18
    reasons: list[str] = []

    if metrics["price"] > metrics["ma20"]:
        score += 16
        reasons.append("站上 MA20")
    if metrics["price"] > metrics["ma60"]:
        score += 18
        reasons.append("站上 MA60")
    if metrics["ma20"] > metrics["ma60"]:
        score += 12
        reasons.append("均線結構偏多")
    if metrics["pct_5d"] > 2:
        score += 8
        reasons.append("近 5 日動能轉強")
    if 55 <= metrics["rsi"] <= 75:
        score += 10
        reasons.append("RSI 位於健康強勢區")
    elif metrics["rsi"] < 35:
        score += 4
        reasons.append("RSI 偏低可留意反彈")
    elif metrics["rsi"] > 80:
        score -= 8
        reasons.append("RSI 偏高避免追價")
    if metrics["vol_ratio"] >= 1.5:
        score += 12
        reasons.append("量能放大")
    if metrics["pct_1d"] >= 3:
        score += 6
        reasons.append("單日漲幅具辨識度")
    elif metrics["pct_1d"] <= -4:
        score -= 6
        reasons.append("單日回檔過深")

    hits = _news_hits(news_items, [code, name, theme])
    if hits:
        score += min(hits * 6, 18)
        reasons.append(f"新聞相關性 {hits} 則")

    final_score = max(0, min(score, 100))
    invalidations = _candidate_invalidations(metrics)
    risk_flags = _candidate_risk_flags(metrics)
    return {
        "code": code,
        "name": name,
        "theme": theme,
        "symbol": symbol,
        "score": final_score,
        "confidence": _confidence_label(final_score, metrics, hits),
        "price": _safe_float(metrics["price"]),
        "pct_1d": _safe_float(metrics["pct_1d"]),
        "pct_5d": _safe_float(metrics["pct_5d"]),
        "rsi": _safe_float(metrics["rsi"]),
        "vol_ratio": _safe_float(metrics["vol_ratio"]),
        "news_hits": hits,
        "reasons": reasons[:4],
        "risk_flags": risk_flags,
        "invalidations": invalidations,
        "data_quality": "正常",
    }


def _confidence_label(score: int, metrics: dict[str, float], news_hits: int) -> str:
    if score >= 78 and metrics["price"] > metrics["ma20"] and metrics["price"] > metrics["ma60"]:
        return "高"
    if score >= 62 or news_hits:
        return "中"
    return "低"


def _candidate_risk_flags(metrics: dict[str, float]) -> list[str]:
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


def _candidate_invalidations(metrics: dict[str, float]) -> list[str]:
    invalidations = []
    if metrics["ma20"]:
        invalidations.append(f"跌破 MA20 {metrics['ma20']:.2f}")
    if metrics["ma60"]:
        invalidations.append(f"跌破 MA60 {metrics['ma60']:.2f}")
    if metrics["rsi"] >= 75:
        invalidations.append("隔日開高量縮且 RSI 過熱")
    return invalidations[:2] or ["跌破前一交易日低點"]


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
    scores: dict[str, float] = defaultdict(float)
    leaders: dict[str, list[str]] = defaultdict(list)
    news_titles = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')}" for item in news_items
    ).lower()

    for candidate in candidates:
        theme = candidate.get("theme", "電子")
        base = float(candidate.get("score", 0))
        base += max(0.0, float(candidate.get("pct_1d", 0)) * 1.4)
        base += max(0.0, float(candidate.get("pct_5d", 0)) * 0.8)
        base += max(0.0, float(candidate.get("news_hits", 0)) * 4)
        scores[theme] += base
        if len(leaders[theme]) < 3:
            leaders[theme].append(f"{candidate['code']} {candidate['name']}")

    keyword_map = {
        "半導體": ["半導體", "晶圓", "晶片", "foundry", "chip"],
        "記憶體": ["記憶體", "dram", "nand", "memory"],
        "AI伺服器": ["ai server", "伺服器", "機櫃", "資料中心"],
        "PCB/ABF": ["abf", "pcb", "載板", "基板"],
        "塑化": ["塑化", "油價", "原料"],
        "航運": ["航運", "貨櫃", "運價"],
    }
    for theme, keywords in keyword_map.items():
        if any(keyword.lower() in news_titles for keyword in keywords):
            scores[theme] += 12

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    result: list[dict[str, Any]] = []
    for theme, score in ordered[:3]:
        result.append(
            {
                "theme": theme,
                "score": round(score, 1),
                "leaders": leaders.get(theme, [])[:3],
            }
        )
    return result


def _dynamic_market_codes(limit: int) -> list[str]:
    if limit <= 0:
        return []
    try:
        rows = twse_json(
            "twse_market_snapshot",
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX_ALL",
            ttl_minutes=15,
        )
    except Exception:
        return []
    if not isinstance(rows, list):
        return []

    scored: list[tuple[float, str]] = []
    for row in rows:
        code = str(row.get("Code") or row.get("證券代號") or "").strip()
        if not code.isdigit():
            continue
        trade_value = _safe_float(row.get("TradeValue") or row.get("成交金額"), digits=0) or 0
        change = _safe_float(row.get("Change") or row.get("漲跌價差"), digits=2) or 0
        if trade_value <= 0:
            continue
        score = trade_value + max(change, 0) * 1_000_000_000
        scored.append((score, code))
    scored.sort(reverse=True)
    return [code for _, code in scored[:limit]]


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


def build_scan_universe(tw_news: list[dict[str, Any]]) -> list[str]:
    codes = list(get_tw_core_codes())
    market_limit = int(os.getenv("TW_DYNAMIC_MARKET_LIMIT", "12"))
    news_limit = int(os.getenv("TW_DYNAMIC_NEWS_LIMIT", "12"))
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
) -> dict[str, Any]:
    all_tw_candidates = [
        item
        for item in (_score_tw_candidate(code, tw_news) for code in build_scan_universe(tw_news))
        if item is not None
    ]
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

    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "market": market,
        "tw_candidates": all_tw_candidates[:top_tw],
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
    candidates = snapshot.get("tw_candidates", [])
    if candidates:
        return [item["code"] for item in candidates[:limit] if item.get("code")]
    return get_tw_core_codes()[:limit]
