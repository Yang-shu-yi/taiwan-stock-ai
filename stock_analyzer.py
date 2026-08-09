from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pandas as pd
import ta
import twstock
import yfinance as yf

from company_assessment import build_company_assessment
from data_layer import twse_json
from entry_opportunity import evaluate_entry_opportunity
from strategy_features import (
    build_model_feature_vector,
    extract_market_features,
    score_canonical_features,
)
from universe import get_theme_for_code, tw_code_to_yahoo_symbol


_REVENUE_ENDPOINTS = {
    "上市": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "上櫃": "https://openapi.twse.com.tw/v1/opendata/t187ap05_P",
}


@dataclass(frozen=True)
class StockMatch:
    code: str
    name: str
    market: str
    group: str


def search_tw_stocks(query: str, limit: int = 12) -> list[StockMatch]:
    query = (query or "").strip()
    if not query:
        return []

    matches: list[tuple[int, StockMatch]] = []
    for code, info in twstock.codes.items():
        if info.type != "股票":
            continue

        score = None
        if query.isdigit():
            if code == query:
                score = 0
            elif code.startswith(query):
                score = 1
        else:
            if info.name == query:
                score = 0
            elif query in info.name:
                score = 1
            elif query.lower() == code.lower():
                score = 2

        if score is None:
            continue

        matches.append(
            (
                score,
                StockMatch(
                    code=code,
                    name=info.name,
                    market=info.market,
                    group=info.group,
                ),
            )
        )

    matches.sort(key=lambda item: (item[0], item[1].code))
    return [item[1] for item in matches[:limit]]


@lru_cache(maxsize=4)
def _load_revenue_map(market: str) -> dict[str, dict]:
    url = _REVENUE_ENDPOINTS.get(market)
    if not url:
        return {}
    try:
        rows = twse_json(f"monthly_revenue_{market}", url, ttl_minutes=720)
        if not isinstance(rows, list):
            return {}
        return {row.get("公司代號", ""): row for row in rows if row.get("公司代號")}
    except Exception:
        return {}


def get_revenue_snapshot(code: str, market: str) -> dict:
    row = _load_revenue_map(market).get(code)
    if not row:
        return {}

    def _to_float(value: str) -> float | None:
        try:
            return float(str(value).replace(",", ""))
        except Exception:
            return None

    month_revenue = _to_float(row.get("營業收入-當月營收"))
    mom = _to_float(row.get("營業收入-上月比較增減(%)"))
    yoy = _to_float(row.get("營業收入-去年同月增減(%)"))
    cumulative_yoy = _to_float(row.get("累計營業收入-前期比較增減(%)"))

    month_revenue_billion = None
    if month_revenue is not None:
        # TWSE monthly revenue open data is in thousand TWD.
        month_revenue_billion = month_revenue / 100000

    return {
        "period": row.get("資料年月", ""),
        "industry": row.get("產業別", ""),
        "month_revenue_billion": month_revenue_billion,
        "mom_pct": mom,
        "yoy_pct": yoy,
        "cumulative_yoy_pct": cumulative_yoy,
    }


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    base = float(series.iloc[-periods - 1])
    if not base:
        return None
    return (float(series.iloc[-1]) / base - 1.0) * 100


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _indicator_text(name: str, passed: bool, detail: str) -> str:
    prefix = "符合" if passed else "未達"
    return f"{name}: {prefix} / {detail}"


def analyze_tw_stock(
    code: str,
    news_items: list[dict] | None = None,
) -> dict:
    if code not in twstock.codes:
        raise ValueError(f"Unknown stock code: {code}")

    info = twstock.codes[code]
    symbol = tw_code_to_yahoo_symbol(code)
    history = yf.Ticker(symbol).history(period="1y", auto_adjust=False)
    benchmark = yf.Ticker("^TWII").history(period="1y", auto_adjust=False)

    if history.empty or len(history) < 80:
        raise RuntimeError(f"Insufficient history for {code}")
    if benchmark.empty or len(benchmark) < 80:
        raise RuntimeError("Insufficient benchmark history")

    history = history.dropna().copy()
    benchmark = benchmark.dropna().copy()

    revenue = get_revenue_snapshot(code, info.market)
    revenue_yoy = revenue.get("yoy_pct")
    features = extract_market_features(history, benchmark)
    if features is None:
        raise RuntimeError(f"Insufficient canonical features for {code}")
    score_result = score_canonical_features(features, revenue)

    close = history["Close"].astype("float64")
    history["MA20"] = ta.trend.sma_indicator(close, 20)
    history["MA60"] = ta.trend.sma_indicator(close, 60)
    history["MA120"] = ta.trend.sma_indicator(close, 120)

    close_price = float(features["price"])
    pct_1d = features["pct_1d"]
    pct_5d = features["pct_5d"]
    pct_20d = features["pct_20d"]
    pct_60d = features["pct_60d"]
    twii_20d = features["benchmark_20d"]
    twii_60d = features["benchmark_60d"]
    rs_20d = features["rs_20d"]
    rs_60d = features["rs_60d"]
    ma20 = float(features["ma20"])
    ma60 = float(features["ma60"])
    ma120 = _safe_float(features["ma120"])
    rsi14 = float(features["rsi14"])
    macd_hist = float(features["macd_hist"])
    atr14 = float(features["atr14"])
    vol_ratio = features["vol_ratio"]
    recent_high_20 = float(features["recent_high_20"])
    recent_low_20 = float(features["recent_low_20"])
    recent_high_60 = float(features["recent_high_60"])
    distance_to_ma20 = features["distance_to_ma20"]
    distance_to_ma60 = features["distance_to_ma60"]
    breakout_gap_20 = features["breakout_gap_20"]

    components = score_result["components"]
    trend_score = components["trend"]
    momentum_score = components["momentum"]
    revenue_score = components["fundamental"]
    relative_score = components["relative_strength"]
    liquidity_score = components["liquidity"]
    overall_score = round(score_result["score"])
    entry_opportunity = evaluate_entry_opportunity(features, overall_score)
    company_assessment = build_company_assessment(
        code=code,
        name=info.name,
        market=info.market,
        revenue=revenue,
        metrics=features,
        entry=entry_opportunity,
        news_items=news_items,
    )

    breakout_ready = (
        close_price >= recent_high_20 * 0.985
        and (vol_ratio or 0) >= 1.2
        and close_price > ma20
        and close_price > ma60
        and distance_to_ma20 is not None
        and distance_to_ma20 <= 6
        and (pct_5d or 0) <= 10
    )
    pullback_setup = (
        close_price > ma20
        and close_price > ma60
        and distance_to_ma20 is not None
        and 0 <= distance_to_ma20 <= 4
        and 45 <= rsi14 <= 62
    )
    weak_rebound = close_price < ma60 and macd_hist < 0

    if overall_score >= 78 and breakout_ready:
        bias = "強勢突破觀察"
        action = "若次日能續量站穩近 20 日高點，可列入強勢股名單；若量縮跌回高點下方，避免追價。"
    elif overall_score >= 68 and pullback_setup:
        bias = "趨勢拉回觀察"
        action = "仍在多頭結構內，等靠近 MA20 或前波整理區有承接，再評估低風險切入。"
    elif overall_score >= 60:
        bias = "高檔整理"
        action = "結構沒有壞，但量價尚未重新發動，先看突破或回測是否有量能確認。"
    elif weak_rebound:
        bias = "弱勢修復"
        action = "尚未站回中期均線前，不建議主動追價，先等結構翻多。"
    else:
        bias = "中性偏保守"
        action = "先觀察價格是否重新站回 MA20 / MA60，再決定是否納入追蹤。"
    trend_bias = bias
    trend_action = action
    bias = entry_opportunity["entry_status_label"]
    action = entry_opportunity["entry_action"]

    risk_flags: list[str] = list(entry_opportunity["entry_risk_flags"])
    if rsi14 >= 75:
        risk_flags.append("RSI 偏熱，短線追價風險高")
    if (vol_ratio or 0) < 0.8:
        risk_flags.append("量能低於 20 日均量，突破延續性不足")
    if distance_to_ma20 is not None and distance_to_ma20 <= -2:
        risk_flags.append("已跌破月線一段距離，結構轉弱")
    if revenue_yoy is not None and revenue_yoy < 0:
        risk_flags.append("最新月營收年增轉負，基本面動能偏弱")
    if rs_20d is not None and rs_20d < 0:
        risk_flags.append("近 20 日表現落後大盤")

    risk_flags = list(dict.fromkeys(risk_flags))
    if not risk_flags:
        risk_flags.append("目前沒有明顯破壞結構的訊號，但仍需留意大盤風險")

    indicator_checks = [
        _indicator_text("趨勢", close_price > ma20 and close_price > ma60, f"現價 {close_price:.2f} / MA20 {ma20:.2f} / MA60 {ma60:.2f}"),
        _indicator_text("量能", (vol_ratio or 0) >= 1.2, f"量比 {vol_ratio:.2f}x" if vol_ratio is not None else "量比無資料"),
        _indicator_text("相對強弱", (rs_20d or 0) > 0, f"近 20 日強於大盤 {rs_20d:+.2f}%" if rs_20d is not None else "無相對強弱資料"),
        _indicator_text("營收動能", (revenue_yoy or 0) > 0, f"月營收年增 {revenue_yoy:+.2f}%" if revenue_yoy is not None else "尚無營收資料"),
    ]

    support_levels = [level for level in [ma20, ma60, recent_low_20] if level]
    resistance_levels = [level for level in [recent_high_20, recent_high_60] if level]

    return {
        "code": code,
        "name": info.name,
        "market": info.market,
        "industry_group": info.group,
        "theme": get_theme_for_code(code),
        "symbol": symbol,
        "history": history.tail(180).copy(),
        "price": {
            "close": close_price,
            "pct_1d": pct_1d,
            "pct_5d": pct_5d,
            "pct_20d": pct_20d,
            "pct_60d": pct_60d,
            "distance_to_ma20": distance_to_ma20,
            "distance_to_ma60": distance_to_ma60,
            "breakout_gap_20": breakout_gap_20,
        },
        "indicators": {
            "ma20": ma20,
            "ma60": ma60,
            "ma120": ma120,
            "rsi14": rsi14,
            "macd_hist": macd_hist,
            "atr14": atr14,
            "vol_ratio": vol_ratio,
            "recent_high_20": recent_high_20,
            "recent_low_20": recent_low_20,
            "recent_high_60": recent_high_60,
        },
        "relative_strength": {
            "stock_20d": pct_20d,
            "stock_60d": pct_60d,
            "twii_20d": twii_20d,
            "twii_60d": twii_60d,
            "rs_20d": rs_20d,
            "rs_60d": rs_60d,
        },
        "revenue": revenue,
        "feature_version": score_result["feature_version"],
        "feature_vector": build_model_feature_vector(features, revenue),
        "entry_opportunity": entry_opportunity,
        "company_assessment": company_assessment,
        "scores": {
            "趨勢結構": trend_score,
            "動能續航": momentum_score,
            "營收動能": revenue_score,
            "相對強弱": relative_score,
            "流動性": liquidity_score,
            "進場可行性": entry_opportunity["entry_score"],
            "總分": overall_score,
        },
        "analysis": {
            "bias": bias,
            "action": action,
            "trend_bias": trend_bias,
            "trend_action": trend_action,
            "indicator_checks": indicator_checks,
            "risk_flags": risk_flags,
            "setup_flags": {
                "breakout_ready": breakout_ready,
                "pullback_setup": pullback_setup,
                "weak_rebound": weak_rebound,
            },
            "support_levels": sorted(support_levels, reverse=True),
            "resistance_levels": sorted(resistance_levels),
        },
    }
