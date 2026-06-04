from __future__ import annotations

import os
from typing import Any

import pandas as pd
import ta
import twstock
import yfinance as yf

from universe import get_theme_for_code, get_tw_name, tw_code_to_yahoo_symbol


DEFAULT_SMALL_MID_CODES = [
    "1504",
    "1513",
    "1514",
    "1522",
    "1560",
    "1590",
    "1723",
    "2059",
    "2383",
    "2404",
    "2474",
    "3014",
    "3030",
    "3105",
    "3163",
    "3260",
    "3450",
    "3563",
    "3592",
    "3708",
    "4763",
    "4906",
    "4966",
    "4979",
    "5289",
    "5443",
    "5483",
    "6121",
    "6147",
    "6213",
    "6269",
    "6274",
    "6643",
    "6781",
    "6805",
    "6806",
    "8086",
    "8299",
]

MIN_AVG_TURNOVER_MILLION = float(os.getenv("SMALL_MID_MIN_TURNOVER_MILLION", "30"))
IDEAL_MAX_PRICE = float(os.getenv("SMALL_MID_IDEAL_MAX_PRICE", "200"))
MAX_PRICE = float(os.getenv("SMALL_MID_MAX_PRICE", "500"))
IDEAL_MARKET_CAP_MIN_BILLION = float(os.getenv("SMALL_MID_MARKET_CAP_MIN_BILLION", "5"))
IDEAL_MARKET_CAP_MAX_BILLION = float(os.getenv("SMALL_MID_MARKET_CAP_MAX_BILLION", "80"))
HARD_MARKET_CAP_MAX_BILLION = float(os.getenv("SMALL_MID_HARD_MARKET_CAP_MAX_BILLION", "250"))


def build_small_mid_cap_radar(
    tw_news: list[dict[str, Any]],
    *,
    exclude_codes: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not _env_flag("ENABLE_SMALL_MID_RADAR", True):
        return []

    max_scan = int(os.getenv("SMALL_MID_SCAN_LIMIT", "24"))
    limit = int(os.getenv("SMALL_MID_LIMIT", "8")) if limit is None else limit
    exclude_codes = exclude_codes or set()

    candidates: list[dict[str, Any]] = []
    for code in _small_mid_universe()[:max_scan]:
        if code in exclude_codes:
            continue
        item = analyze_small_mid_candidate(code, tw_news)
        if item is not None:
            candidates.append(item)

    candidates.sort(
        key=lambda item: (
            item.get("small_mid_score", 0),
            item.get("quality_score", 0),
            item.get("pct_20d") or 0,
        ),
        reverse=True,
    )

    for rank, item in enumerate(candidates, start=1):
        item["small_mid_rank"] = rank
    return candidates[:limit]


def analyze_small_mid_candidate(code: str, tw_news: list[dict[str, Any]]) -> dict[str, Any] | None:
    if code not in twstock.codes:
        return None

    symbol = tw_code_to_yahoo_symbol(code)
    history = _recent_history(symbol)
    metrics = _price_metrics(history) if history is not None else None
    if metrics is None:
        return None

    fundamentals = _fundamental_metrics(symbol)
    score_detail = score_small_mid_candidate(metrics, fundamentals, _news_hits(tw_news, code))
    if score_detail["excluded"]:
        return None

    name = get_tw_name(code)
    theme = get_theme_for_code(code)
    reasons = _reason_lines(metrics, fundamentals, score_detail)
    risk_flags = _risk_flags(metrics, fundamentals)
    invalidations = _invalidations(metrics)

    score = score_detail["score"]
    item = {
        "code": code,
        "name": name,
        "symbol": symbol,
        "theme": theme,
        "source": "small_mid_radar",
        "score": score,
        "small_mid_score": score,
        "quality_score": score_detail["quality_score"],
        "valuation_score": score_detail["valuation_score"],
        "liquidity_score": score_detail["liquidity_score"],
        "technical_score": score_detail["technical_score"],
        "confidence": _confidence_label(score, score_detail),
        "price": _round(metrics["price"]),
        "pct_1d": _round(metrics["pct_1d"]),
        "pct_5d": _round(metrics["pct_5d"]),
        "pct_20d": _round(metrics["pct_20d"]),
        "rsi": _round(metrics["rsi"]),
        "vol_ratio": _round(metrics["vol_ratio"]),
        "avg_turnover_million": _round(metrics["avg_turnover_million"]),
        "market_cap_billion": _round(fundamentals.get("market_cap_billion")),
        "trailing_pe": _round(fundamentals.get("trailing_pe")),
        "price_to_book": _round(fundamentals.get("price_to_book")),
        "dividend_yield_pct": _round(fundamentals.get("dividend_yield_pct")),
        "news_hits": score_detail["news_hits"],
        "reasons": reasons,
        "risk_flags": risk_flags,
        "invalidations": invalidations,
        "data_quality": "基本面資料部分依 Yahoo 補充" if fundamentals.get("missing") else "正常",
    }
    return item


def score_small_mid_candidate(
    metrics: dict[str, float],
    fundamentals: dict[str, float | bool | None],
    news_hits: int = 0,
) -> dict[str, Any]:
    excluded_reasons: list[str] = []
    if metrics["avg_turnover_million"] < MIN_AVG_TURNOVER_MILLION:
        excluded_reasons.append("成交值不足")
    if metrics["price"] > MAX_PRICE:
        excluded_reasons.append("股價超過雷達上限")
    market_cap = fundamentals.get("market_cap_billion")
    if isinstance(market_cap, float) and market_cap > HARD_MARKET_CAP_MAX_BILLION:
        excluded_reasons.append("市值過大")

    liquidity_score = _liquidity_score(metrics)
    technical_score = _technical_score(metrics)
    valuation_score = _valuation_score(fundamentals)
    quality_score = _quality_score(metrics, fundamentals)
    theme_score = min(news_hits * 8, 16)

    total = round(
        quality_score * 0.30
        + valuation_score * 0.20
        + liquidity_score * 0.15
        + technical_score * 0.25
        + theme_score
    )
    total = max(0, min(total, 100))

    return {
        "score": total,
        "quality_score": quality_score,
        "valuation_score": valuation_score,
        "liquidity_score": liquidity_score,
        "technical_score": technical_score,
        "theme_score": theme_score,
        "news_hits": news_hits,
        "excluded": bool(excluded_reasons),
        "excluded_reasons": excluded_reasons,
    }


def promote_small_mid_candidates(
    tw_candidates: list[dict[str, Any]],
    small_mid_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    promote_limit = int(os.getenv("SMALL_MID_PROMOTE_LIMIT", "2"))
    if promote_limit <= 0 or not small_mid_candidates:
        return tw_candidates

    existing = {item.get("code") for item in tw_candidates}
    promoted = [
        item
        for item in small_mid_candidates
        if item.get("code") not in existing and item.get("small_mid_score", 0) >= 68
    ][:promote_limit]
    return tw_candidates + promoted


def _small_mid_universe() -> list[str]:
    raw = os.getenv("SMALL_MID_CODES", "").strip()
    codes = _split_csv(raw) if raw else list(DEFAULT_SMALL_MID_CODES)
    extra = _split_csv(os.getenv("SMALL_MID_EXTRA_CODES", ""))
    output: list[str] = []
    seen: set[str] = set()
    for code in codes + extra:
        if code in seen or code not in twstock.codes:
            continue
        seen.add(code)
        output.append(code)
    return output


def _recent_history(symbol: str, period: str = "6mo") -> pd.DataFrame | None:
    try:
        history = yf.Ticker(symbol).history(period=period, auto_adjust=False)
        if history is None or history.empty:
            return None
        return history.dropna(subset=["Close"]).copy()
    except Exception:
        return None


def _price_metrics(history: pd.DataFrame) -> dict[str, float] | None:
    if history is None or len(history) < 60:
        return None
    close = history["Close"].astype("float64")
    volume = history["Volume"].fillna(0).astype("float64")
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    ma20 = float(ta.trend.sma_indicator(close, 20).iloc[-1])
    ma60 = float(ta.trend.sma_indicator(close, 60).iloc[-1])
    rsi = float(ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1])
    avg_volume20 = float(volume.tail(20).mean())
    avg_turnover_million = price * avg_volume20 / 1_000_000
    pct_1d = ((price / prev) - 1.0) * 100 if prev else 0.0
    pct_5d = _pct_change(close, 5) or 0.0
    pct_20d = _pct_change(close, 20) or 0.0
    vol_ratio = float(volume.iloc[-1] / avg_volume20) if avg_volume20 else 1.0
    volatility20 = float(close.pct_change().tail(20).std() * 100)

    return {
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "rsi": rsi,
        "pct_1d": pct_1d,
        "pct_5d": pct_5d,
        "pct_20d": pct_20d,
        "vol_ratio": vol_ratio,
        "avg_turnover_million": avg_turnover_million,
        "volatility20": volatility20,
    }


def _fundamental_metrics(symbol: str) -> dict[str, float | bool | None]:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.get_info() if hasattr(ticker, "get_info") else ticker.info
    except Exception:
        info = {}

    market_cap = _to_float(info.get("marketCap"))
    dividend_yield = _to_float(info.get("dividendYield"))
    return {
        "market_cap_billion": market_cap / 1_000_000_000 if market_cap else None,
        "trailing_pe": _to_float(info.get("trailingPE")),
        "price_to_book": _to_float(info.get("priceToBook")),
        "dividend_yield_pct": dividend_yield * 100 if dividend_yield else None,
        "missing": not bool(info),
    }


def _liquidity_score(metrics: dict[str, float]) -> int:
    turnover = metrics["avg_turnover_million"]
    if turnover >= 500:
        return 90
    if turnover >= 150:
        return 80
    if turnover >= 60:
        return 68
    if turnover >= MIN_AVG_TURNOVER_MILLION:
        return 55
    return 20


def _technical_score(metrics: dict[str, float]) -> int:
    score = 30
    if metrics["price"] > metrics["ma20"]:
        score += 18
    if metrics["price"] > metrics["ma60"]:
        score += 18
    if metrics["ma20"] > metrics["ma60"]:
        score += 12
    if metrics["pct_20d"] > 3:
        score += 10
    if 45 <= metrics["rsi"] <= 72:
        score += 10
    elif metrics["rsi"] > 80:
        score -= 12
    if metrics["vol_ratio"] >= 1.2:
        score += 10
    if metrics["volatility20"] > 5:
        score -= 8
    return max(0, min(score, 100))


def _valuation_score(fundamentals: dict[str, float | bool | None]) -> int:
    score = 50
    market_cap = fundamentals.get("market_cap_billion")
    pe = fundamentals.get("trailing_pe")
    pb = fundamentals.get("price_to_book")
    dividend_yield = fundamentals.get("dividend_yield_pct")

    if isinstance(market_cap, float):
        if IDEAL_MARKET_CAP_MIN_BILLION <= market_cap <= IDEAL_MARKET_CAP_MAX_BILLION:
            score += 18
        elif market_cap > HARD_MARKET_CAP_MAX_BILLION:
            score -= 25
    if isinstance(pe, float):
        if 6 <= pe <= 22:
            score += 20
        elif pe > 40 or pe <= 0:
            score -= 18
    if isinstance(pb, float):
        if 0.7 <= pb <= 3.5:
            score += 12
        elif pb > 6:
            score -= 12
    if isinstance(dividend_yield, float):
        if 2 <= dividend_yield <= 7:
            score += 10
        elif dividend_yield > 10:
            score -= 8
    return max(0, min(score, 100))


def _quality_score(metrics: dict[str, float], fundamentals: dict[str, float | bool | None]) -> int:
    score = 50
    market_cap = fundamentals.get("market_cap_billion")
    pe = fundamentals.get("trailing_pe")

    if metrics["price"] <= IDEAL_MAX_PRICE:
        score += 12
    elif metrics["price"] <= MAX_PRICE:
        score += 4
    if metrics["pct_20d"] > 0:
        score += 12
    if metrics["avg_turnover_million"] >= 80:
        score += 10
    if isinstance(market_cap, float) and market_cap >= IDEAL_MARKET_CAP_MIN_BILLION:
        score += 8
    if isinstance(pe, float) and 0 < pe <= 30:
        score += 8
    if metrics["volatility20"] > 6:
        score -= 12
    return max(0, min(score, 100))


def _news_hits(news_items: list[dict[str, Any]], code: str) -> int:
    name = get_tw_name(code)
    theme = get_theme_for_code(code)
    hits = 0
    for item in news_items:
        haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        if code in haystack or name.lower() in haystack or theme.lower() in haystack:
            hits += 1
    return hits


def _reason_lines(
    metrics: dict[str, float],
    fundamentals: dict[str, float | bool | None],
    score_detail: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if metrics["price"] <= IDEAL_MAX_PRICE:
        reasons.append(f"股價低於 {IDEAL_MAX_PRICE:.0f} 元觀察區")
    if metrics["avg_turnover_million"] >= 80:
        reasons.append(f"20日均成交值 {metrics['avg_turnover_million']:.0f} 百萬")
    if metrics["price"] > metrics["ma20"] and metrics["price"] > metrics["ma60"]:
        reasons.append("站上 MA20/MA60")
    if metrics["pct_20d"] > 0:
        reasons.append(f"20日相對動能 {metrics['pct_20d']:+.1f}%")
    market_cap = fundamentals.get("market_cap_billion")
    if isinstance(market_cap, float) and market_cap <= IDEAL_MARKET_CAP_MAX_BILLION:
        reasons.append(f"市值約 {market_cap:.1f}B")
    if score_detail["news_hits"]:
        reasons.append(f"新聞/主題命中 {score_detail['news_hits']} 則")
    return reasons[:4] or ["中小型股雷達綜合分數達標"]


def _risk_flags(metrics: dict[str, float], fundamentals: dict[str, float | bool | None]) -> list[str]:
    flags: list[str] = []
    pe = fundamentals.get("trailing_pe")
    if metrics["avg_turnover_million"] < 80:
        flags.append("成交值偏低，追價滑價風險較高")
    if metrics["rsi"] >= 78:
        flags.append("RSI 偏熱，避免追第一根長紅")
    if metrics["price"] < metrics["ma20"]:
        flags.append("尚未站回 MA20")
    if isinstance(pe, float) and (pe <= 0 or pe > 40):
        flags.append("估值或獲利品質需複查")
    if fundamentals.get("missing"):
        flags.append("基本面資料不足，需人工複查")
    return flags or ["未見主要流動性或技術面風險"]


def _invalidations(metrics: dict[str, float]) -> list[str]:
    invalidations = [f"跌破 MA20 {metrics['ma20']:.2f}"]
    if metrics["ma60"]:
        invalidations.append(f"跌破 MA60 {metrics['ma60']:.2f}")
    if metrics["avg_turnover_million"] < 80:
        invalidations.append("成交值未放大")
    return invalidations[:2]


def _confidence_label(score: int, score_detail: dict[str, Any]) -> str:
    if score >= 78 and score_detail["quality_score"] >= 70:
        return "高"
    if score >= 65:
        return "中"
    return "低"


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    base = float(series.iloc[-periods - 1])
    if not base:
        return None
    return (float(series.iloc[-1]) / base - 1.0) * 100


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _round(value: Any, digits: int = 2) -> float | None:
    try:
        return round(float(value), digits)
    except Exception:
        return None
