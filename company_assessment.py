from __future__ import annotations

from functools import lru_cache
from typing import Any

import twstock

from data_layer import twse_json


_VALUATION_ENDPOINTS = {
    "上市": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
    "上櫃": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
}

_SEVERE_EVENT_KEYWORDS = (
    "停止交易",
    "暫停交易",
    "重整",
    "破產",
    "違約",
    "跳票",
    "掏空",
    "下市",
    "停工",
    "重大災害",
)
_NEGATIVE_EVENT_KEYWORDS = (
    "財測下修",
    "下修展望",
    "虧損",
    "衰退",
    "裁罰",
    "訴訟",
    "調查",
    "召回",
    "客戶流失",
    "延遲出貨",
    "董事辭任",
    "減資",
)


def _number(value: Any) -> float | None:
    try:
        text = str(value).strip().replace(",", "").replace("%", "")
        if text in {"", "-", "--", "---", "N/A", "None"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(value, upper))


def _linear(value: float, low: float, high: float) -> float:
    if high == low:
        return 50.0
    return _clamp((value - low) / (high - low) * 100.0)


def _gregorian_date(raw: Any) -> str:
    digits = "".join(character for character in str(raw or "") if character.isdigit())
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(raw or "").strip()


@lru_cache(maxsize=4)
def _load_valuation_map(market: str) -> dict[str, dict[str, Any]]:
    url = _VALUATION_ENDPOINTS.get(market)
    if not url:
        return {}
    try:
        rows = twse_json(f"official_valuation_{market}", url, ttl_minutes=720)
    except Exception:
        return {}
    if not isinstance(rows, list):
        return {}

    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if market == "上市":
            code = str(row.get("Code") or "").strip()
            pe = _number(row.get("PEratio"))
            pb = _number(row.get("PBratio"))
            yield_pct = _number(row.get("DividendYield"))
        else:
            code = str(row.get("SecuritiesCompanyCode") or "").strip()
            pe = _number(row.get("PriceEarningRatio"))
            pb = _number(row.get("PriceBookRatio"))
            yield_pct = _number(row.get("YieldRatio"))
        if not code:
            continue
        output[code] = {
            "date": _gregorian_date(row.get("Date")),
            "pe_ratio": pe if pe is not None and pe > 0 else None,
            "pb_ratio": pb if pb is not None and pb > 0 else None,
            "dividend_yield_pct": yield_pct if yield_pct is not None and yield_pct >= 0 else None,
            "source": "TWSE" if market == "上市" else "TPEx",
        }
    return output


def _peer_values(
    valuation_map: dict[str, dict[str, Any]],
    code: str,
    field: str,
) -> tuple[list[float], str]:
    info = twstock.codes.get(code)
    group = getattr(info, "group", "") if info is not None else ""
    peer_values: list[float] = []
    if group:
        for peer_code, row in valuation_map.items():
            peer_info = twstock.codes.get(peer_code)
            value = _number(row.get(field))
            if peer_info is not None and getattr(peer_info, "group", "") == group and value is not None:
                peer_values.append(value)
    if len(peer_values) >= 8:
        return peer_values, f"{group}同業"
    market_values = [
        value
        for row in valuation_map.values()
        if (value := _number(row.get(field))) is not None
    ]
    return market_values, "同市場"


def _percentile_score(value: float, peers: list[float], *, lower_is_better: bool) -> float:
    if len(peers) < 2:
        return 50.0
    below = sum(1 for peer in peers if peer < value)
    equal = sum(1 for peer in peers if peer == value)
    percentile = (below + equal * 0.5) / len(peers) * 100.0
    return 100.0 - percentile if lower_is_better else percentile


def get_valuation_snapshot(code: str, market: str) -> dict[str, Any]:
    valuation_map = _load_valuation_map(market)
    snapshot = dict(valuation_map.get(code) or {})
    if not snapshot:
        return {}

    weighted_scores: list[tuple[float, float]] = []
    bases: list[str] = []
    for field, weight, lower_is_better in (
        ("pe_ratio", 0.45, True),
        ("pb_ratio", 0.35, True),
        ("dividend_yield_pct", 0.20, False),
    ):
        value = _number(snapshot.get(field))
        if value is None:
            continue
        peers, basis = _peer_values(valuation_map, code, field)
        weighted_scores.append(
            (_percentile_score(value, peers, lower_is_better=lower_is_better), weight)
        )
        bases.append(basis)

    if weighted_scores:
        total_weight = sum(weight for _, weight in weighted_scores)
        snapshot["score"] = round(
            sum(score * weight for score, weight in weighted_scores) / total_weight,
            1,
        )
        snapshot["comparison_basis"] = (
            bases[0] if bases and all(value == bases[0] for value in bases) else "同業與同市場"
        )
        snapshot["coverage"] = len(weighted_scores)
    return snapshot


def score_company_quality(revenue: dict[str, Any] | None) -> dict[str, Any]:
    revenue = revenue or {}
    inputs = (
        ("yoy_pct", 0.45, -20.0, 30.0),
        ("cumulative_yoy_pct", 0.40, -15.0, 25.0),
        ("mom_pct", 0.15, -15.0, 15.0),
    )
    scored: list[tuple[float, float]] = []
    for field, weight, low, high in inputs:
        value = _number(revenue.get(field))
        if value is not None:
            scored.append((_linear(value, low, high), weight))
    if not scored:
        return {
            "score": None,
            "confidence": "不足",
            "basis": "尚無可用月營收資料",
        }
    total_weight = sum(weight for _, weight in scored)
    score = sum(value * weight for value, weight in scored) / total_weight
    confidence = "中" if len(scored) == 3 else "初步"
    return {
        "score": round(score, 1),
        "confidence": confidence,
        "basis": "目前以最新月營收、累計營收與月增率作為品質基線",
    }


def assess_event_risk(
    news_items: list[dict[str, Any]] | None,
    *,
    code: str,
    name: str,
) -> dict[str, Any]:
    related: list[dict[str, Any]] = []
    for item in news_items or []:
        haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        if code.lower() in haystack or (name and name.lower() in haystack):
            related.append(item)

    matched_severe: list[str] = []
    matched_negative: list[str] = []
    for item in related:
        haystack = f"{item.get('title', '')} {item.get('summary', '')}"
        matched_severe.extend(keyword for keyword in _SEVERE_EVENT_KEYWORDS if keyword in haystack)
        matched_negative.extend(keyword for keyword in _NEGATIVE_EVENT_KEYWORDS if keyword in haystack)

    if matched_severe:
        level = "高"
        summary = f"新聞出現「{matched_severe[0]}」等重大風險字詞，先查原始公告，暫不新增部位。"
    elif matched_negative:
        level = "中"
        summary = f"新聞出現「{matched_negative[0]}」等負面字詞，需確認是否影響營收或獲利。"
    elif related:
        level = "低"
        summary = "目前相關新聞未見明顯負面事件，但仍應以公司重大訊息為準。"
    else:
        level = "待確認"
        summary = "目前新聞樣本沒有足夠的公司事件資訊，不能據此判定低風險。"

    return {
        "level": level,
        "summary": summary,
        "related_news_count": len(related),
        "keywords": list(dict.fromkeys([*matched_severe, *matched_negative]))[:3],
        "basis": "RSS 新聞初篩，尚未取代公開資訊觀測站重大訊息",
    }


def _revenue_summary(revenue: dict[str, Any]) -> str:
    yoy = _number(revenue.get("yoy_pct"))
    cumulative = _number(revenue.get("cumulative_yoy_pct"))
    mom = _number(revenue.get("mom_pct"))
    if yoy is None and cumulative is None and mom is None:
        return "月營收資料不足，暫時不能判斷基本面是否改善。"
    parts = []
    if yoy is not None:
        parts.append(f"最新月營收年增 {yoy:+.1f}%")
    if cumulative is not None:
        parts.append(f"累計年增 {cumulative:+.1f}%")
    if mom is not None:
        parts.append(f"月增 {mom:+.1f}%")
    if yoy is not None and cumulative is not None and yoy > 0 and cumulative > 0:
        conclusion = "營收成長仍有延續"
    elif yoy is not None and yoy < 0:
        conclusion = "最新單月營收轉弱，先確認是否只是淡旺季"
    elif cumulative is not None and cumulative < 0:
        conclusion = "今年累計營收仍落後去年"
    else:
        conclusion = "營收方向尚未形成一致訊號"
    return f"{'、'.join(parts)}；{conclusion}。"


def _valuation_summary(valuation: dict[str, Any]) -> str:
    if not valuation:
        return "官方估值資料不足，暫不判定便宜或昂貴。"
    parts = []
    if valuation.get("pe_ratio") is not None:
        parts.append(f"本益比 {valuation['pe_ratio']:.1f} 倍")
    if valuation.get("pb_ratio") is not None:
        parts.append(f"股價淨值比 {valuation['pb_ratio']:.2f} 倍")
    if valuation.get("dividend_yield_pct") is not None:
        parts.append(f"殖利率 {valuation['dividend_yield_pct']:.1f}%")
    basis = valuation.get("comparison_basis") or "同市場"
    return f"{'、'.join(parts)}；吸引力分數採{basis}相對排名，不代表絕對便宜。"


def _actionable_advice(
    quality_score: float | None,
    valuation_score: float | None,
    timing_score: float | None,
    event_level: str,
    revenue: dict[str, Any],
    metrics: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[str, str]:
    ma20 = _number(metrics.get("ma20") or metrics.get("sma20"))
    yoy = _number(revenue.get("yoy_pct"))
    stop_price = _number((entry.get("entry_plan") or {}).get("stop_price"))

    if event_level == "高":
        return "重大事件查證", "先閱讀公司原始公告並確認財務影響；事件未釐清前，系統不列為新增部位。"
    if quality_score is None or valuation_score is None:
        missing = "公司品質" if quality_score is None else "估值"
        return "資料不足", f"{missing}資料尚未補齊；先維持觀察，不因技術反彈直接視為買點。"
    if quality_score < 45:
        condition = "等最新月營收年增與累計年增都回到正數"
        if yoy is not None and yoy >= 0:
            condition = "等營收成長連續兩期改善"
        return "基本面先保守", f"即使股價反彈也先當短線訊號；至少{condition}，再重新評估。"
    if quality_score >= 70 and valuation_score >= 60 and (timing_score or 0) < 55:
        price_condition = f"站回 MA20 約 {ma20:.2f}" if ma20 is not None else "重新站回短期趨勢"
        return (
            "優質回檔觀察",
            f"公司與估值條件較佳，但價格尚未止跌；先等股價{price_condition}，且下次月營收年增未轉負，再考慮小量分批。",
        )
    if quality_score >= 70 and valuation_score < 45:
        return "好公司但估值偏高", "基本面較佳，但目前相對同業不便宜；等待估值回到中間區間或獲利上修，不追價。"
    if (timing_score or 0) >= 65 and quality_score >= 60:
        risk_condition = f"跌破規劃停損 {stop_price:.2f} 就取消觀察" if stop_price is not None else "跌破主要支撐就取消觀察"
        return "條件較完整", f"基本面、估值與進場條件沒有明顯衝突；若要分批，務必小量，且{risk_condition}。"
    if (timing_score or 0) < 55:
        price_condition = f"站回 MA20 約 {ma20:.2f}" if ma20 is not None else "價格止跌"
        return "等待止跌", f"目前不是追價訊號；先等{price_condition}並確認量能回升，再重新評估。"
    return "持續觀察", "條件尚未同時到位；等待基本面、估值或價格訊號至少再改善一項。"


def build_company_assessment(
    *,
    code: str,
    name: str,
    market: str,
    revenue: dict[str, Any] | None,
    metrics: dict[str, Any],
    entry: dict[str, Any],
    news_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    revenue = revenue or {}
    quality = score_company_quality(revenue)
    valuation = get_valuation_snapshot(code, market)
    event = assess_event_risk(news_items, code=code, name=name)
    timing_score = _number(entry.get("entry_score"))
    quality_score = _number(quality.get("score"))
    valuation_score = _number(valuation.get("score"))
    opportunity_label, advice = _actionable_advice(
        quality_score,
        valuation_score,
        timing_score,
        event["level"],
        revenue,
        metrics,
        entry,
    )
    return {
        "company_quality_score": quality_score,
        "company_quality_confidence": quality["confidence"],
        "company_quality_basis": quality["basis"],
        "valuation_attractiveness_score": valuation_score,
        "entry_timing_score": timing_score,
        "event_risk_level": event["level"],
        "event_risk_summary": event["summary"],
        "event_risk_basis": event["basis"],
        "related_news_count": event["related_news_count"],
        "opportunity_label": opportunity_label,
        "plain_language_advice": advice,
        "fundamental_summary": _revenue_summary(revenue),
        "valuation_summary": _valuation_summary(valuation),
        "valuation": valuation,
    }
