from datetime import datetime
from typing import Any
from urllib.parse import urlparse


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace("+", "").replace("%", "").replace(",", ""))
    except Exception:
        return None


def _market_bias_label(pct: float | None) -> str:
    if pct is None:
        return "中性"
    if pct >= 1.0:
        return "偏多"
    if pct <= -1.0:
        return "偏空"
    return "震盪偏中性"


def _pick_us_context(snapshot: dict[str, Any]) -> str:
    items = snapshot.get("us_context", [])[:3]
    if not items:
        return "美股脈絡不足"
    return "、".join(
        f"{item['symbol']} {item.get('pct_1d', 0):+.2f}%"
        for item in items
        if item.get("symbol")
    )


def _pick_tw_focus(snapshot: dict[str, Any], limit: int = 3) -> str:
    items = snapshot.get("tw_candidates", [])[:limit]
    if not items:
        return "今日沒有明確焦點股"
    return "、".join(f"{item['code']} {item['name']}" for item in items)


def _top_candidate_lines(snapshot: dict[str, Any], limit: int = 5) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(snapshot.get("tw_candidates", [])[:limit], start=1):
        reasons = "、".join(item.get("reasons", [])[:2]) or "訊號整體偏強"
        invalidation = "、".join(item.get("invalidations", [])[:1]) or "跌破前低"
        confidence = item.get("confidence", "中")
        quality = item.get("data_quality", "正常")
        lines.append(
            f"{index}. {item['code']} {item['name']} {item.get('pct_1d', 0):+.2f}% / 信心{confidence} / {reasons} / 失效: {invalidation} / 資料{quality}"
        )
    return lines


def _theme_lines(snapshot: dict[str, Any], limit: int = 3) -> list[str]:
    theme_items = snapshot.get("theme_summary", [])
    specific_items = [item for item in theme_items if item.get("theme") not in {"電子", "其他"}]
    if specific_items:
        theme_items = specific_items + [item for item in theme_items if item not in specific_items]
    lines: list[str] = []
    for item in theme_items[:limit]:
        leaders = "、".join(item.get("leaders", [])[:2]) or "無"
        lines.append(f"- {item['theme']} / 強度 {item['score']:.1f} / 代表股 {leaders}")
    return lines or ["- 電子 / 強度不足 / 需看開盤補量"]


def _opening_scenarios(snapshot: dict[str, Any]) -> list[str]:
    theme_items = snapshot.get("theme_summary", [])
    specific_items = [item for item in theme_items if item.get("theme") not in {"電子", "其他"}]
    top_theme = (specific_items[0] if specific_items else (theme_items[0] if theme_items else {})).get("theme", "電子")
    top_focus = _pick_tw_focus(snapshot, limit=2)
    return [
        f"開高: 先看 {top_theme} 是否帶量續強；若 {top_focus} 開高後量增可追蹤，不追第一根過熱棒",
        f"平盤: 先看 {top_theme} 是否成為主軸；若焦點股先強於大盤，可列入盤中名單",
        f"開低: 先看焦點股是否守前低；若 {top_theme} 量縮抗跌可留意，若同步走弱先觀望",
    ]


def _post_market_review(snapshot: dict[str, Any]) -> list[str]:
    candidates = snapshot.get("tw_candidates", [])[:3]
    if not candidates:
        return ["- 今天沒有明確收斂出可延續焦點股"]
    lines: list[str] = []
    for item in candidates:
        review = "續強結構" if (item.get("pct_1d") or 0) > 0 else "需要再確認"
        lines.append(
            f"- {item['code']} {item['name']} / {item.get('pct_1d', 0):+.2f}% / {item.get('theme', '電子')} / {review}"
        )
    return lines


def _news_hint(snapshot: dict[str, Any]) -> str:
    titles = snapshot.get("news_summary", {}).get("tw_top_titles", [])
    cleaned = [_clean_news_item(title) for title in titles if str(title).strip()]
    if not cleaned:
        return "新聞面未提供明確加分"
    return cleaned[0][:42]


def _clean_news_item(item: Any) -> str:
    if isinstance(item, dict):
        source = str(item.get("source") or "").strip()
        title = _clean_news_title(str(item.get("title") or ""))
        return f"{source}: {title}" if source else title
    return _clean_news_title(str(item))


def _clean_news_title(title: str) -> str:
    text = str(title).replace("\n", " ").strip()
    for separator in [" - news.", " - news", " - Yahoo", " - 奇摩", " - Anue"]:
        if separator in text:
            text = text.split(separator, 1)[0].strip()
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return parsed.netloc
    return text.strip(" -")


def _data_status_line(snapshot: dict[str, Any]) -> str:
    status = snapshot.get("data_status") or {}
    if not status:
        return "🧪 資料狀態: 未記錄"

    snapshot_date = _snapshot_date(snapshot)
    notable = [
        _format_data_status_item(key, item, snapshot_date)
        for key, item in status.items()
        if _is_data_status_notable(item, snapshot_date)
    ]
    notable = [item for item in notable if item]
    if not notable:
        return "🧪 資料狀態: 正常"
    labels = "、".join(notable[:3])
    extra = "" if len(notable) <= 3 else f" 等 {len(notable)} 項"
    return f"🧪 資料狀態: 留意 {labels}{extra}"


def _snapshot_date(snapshot: dict[str, Any]) -> str | None:
    updated_at = str(snapshot.get("updated_at") or "").strip()
    if not updated_at:
        return None
    normalized = updated_at.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        return datetime.strptime(updated_at[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        pass
    return updated_at[:10] if len(updated_at) >= 10 else None


def _is_data_status_notable(item: Any, snapshot_date: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    trading_date = str(item.get("trading_date") or "").strip()
    return bool(
        not item.get("ok")
        or item.get("cached")
        or item.get("fallback_used")
        or item.get("stale_reason")
        or (snapshot_date and trading_date and trading_date != snapshot_date)
    )


def _format_data_status_item(key: str, item: Any, snapshot_date: str | None) -> str:
    if not isinstance(item, dict):
        return str(key)

    label = _DATA_STATUS_LABELS.get(key, key)
    notes: list[str] = []
    trading_date = str(item.get("trading_date") or "").strip()

    if not item.get("ok"):
        notes.append("來源失敗")
    if item.get("cached"):
        notes.append("快取")
    if item.get("fallback_used"):
        notes.append("備援")
    if snapshot_date and trading_date and trading_date != snapshot_date:
        notes.append(f"{trading_date}資料")
    elif item.get("stale_reason") and str(item.get("stale_reason")) not in {"fresh_cache"}:
        notes.append(str(item.get("stale_reason")))

    return f"{label}({'/'.join(notes)})" if notes else label


_DATA_STATUS_LABELS = {
    "news": "新聞",
    "twse_institutional": "法人",
    "twse_market_snapshot": "台股清單",
    "twse_margin": "融資券",
    "twse_turnover": "成交值",
}


def _performance_line(snapshot: dict[str, Any]) -> str | None:
    summary = snapshot.get("performance_summary") or {}
    if not summary or not summary.get("count"):
        return None
    avg_return = summary.get("avg_return_pct")
    avg_excess = summary.get("avg_excess_return_pct")
    win_rate = summary.get("win_rate")
    top5 = summary.get("top5_hit_rate")
    parts = [f"樣本 {summary.get('count')}"]
    if avg_return is not None:
        parts.append(f"平均 {avg_return:+.2f}%")
    if avg_excess is not None:
        parts.append(f"相對大盤 {avg_excess:+.2f}%")
    if win_rate is not None:
        parts.append(f"勝率 {win_rate:.0%}")
    if top5 is not None:
        parts.append(f"Top5 {top5:.0%}")
    return "📈 近期訊號: " + " / ".join(parts)


def format_market_report(snapshot: dict[str, Any]) -> str:
    mode = snapshot.get("mode", "PRE")
    market = snapshot.get("market", {})
    tw = market.get("tw_index", {})
    forex = market.get("forex", {})
    tw_pct = _to_float(tw.get("pct", "0"))

    title = "[🌅 盤前可執行摘要]" if mode == "PRE" else "[🌙 盤後可復盤報告]"
    lines = [
        title,
        f"📊 台股: {tw.get('price', 'N/A')} ({tw.get('pct', 'N/A')}%) / 成交值 {tw.get('turnover', 'N/A')} / 氣氛 {_market_bias_label(tw_pct)}",
        f"🌍 美股: {_pick_us_context(snapshot)} / 匯率 USDTWD {forex.get('rate', 'N/A')}",
        f"🎯 台股焦點: {_pick_tw_focus(snapshot)}",
        "🔥 今日主軸:",
    ]
    lines.extend(_theme_lines(snapshot))
    lines.append("📌 重點股:")
    lines.extend(_top_candidate_lines(snapshot, limit=5))
    lines.append(f"📰 新聞提示: {_news_hint(snapshot)}")
    lines.append(_data_status_line(snapshot))
    performance = _performance_line(snapshot)
    if performance:
        lines.append(performance)

    if mode == "PRE":
        lines.append("🧭 開盤劇本:")
        lines.extend(f"- {line}" for line in _opening_scenarios(snapshot))
    else:
        lines.append("🔎 盤後復盤:")
        lines.extend(_post_market_review(snapshot))
        lines.append("👀 隔日觀察: 先看主軸族群是否續強，再決定是否追蹤焦點股")

    lines.append("⚠️ 以上為資料輔助判讀，不是保證獲利或直接下單建議。")
    return "\n".join(lines)


def format_intraday_alert(item: dict[str, Any]) -> str:
    direction = "📈 突破確認" if item.get("status") == "UP" else "📉 轉弱確認"
    price = item.get("price", 0.0)
    pct = item.get("pct", 0.0)
    rsi = item.get("rsi", 0.0)
    vol_ratio = item.get("vol_ratio")
    vol_text = "N/A" if vol_ratio is None else f"{vol_ratio:.2f}x"
    risk_line = (
        "風險: 不追價，等下一次拉回確認"
        if pct > 0
        else "風險: 不要急著接弱勢反彈"
    )
    return "\n".join(
        [
            "[⚡ 盤中警示]",
            f"股票: {item['code']} {item['name']}",
            f"狀態: {direction}",
            f"價格: {price:.2f} ({pct:+.2f}%)",
            f"訊號: RSI {rsi:.1f} / 量比 {vol_text}",
            f"⚠️ {risk_line}",
        ]
    )


def format_telegram_help() -> str:
    return "\n".join(
        [
            "[🧾 指令說明]",
            "/list 查看今日候選股",
            "/help 查看指令說明",
        ]
    )


def format_candidate_list(snapshot: dict[str, Any], limit: int = 10) -> str:
    items = snapshot.get("tw_candidates", [])[:limit]
    lines = ["[📋 今日候選股]"]
    if not items:
        lines.append("目前沒有候選資料")
        return "\n".join(lines)
    for item in items:
        reasons = "、".join(item.get("reasons", [])[:2]) or "訊號整體偏強"
        lines.append(
            f"{item['code']} {item['name']} / 分數 {item.get('score', 0)} / {item.get('pct_1d', 0):+.2f}% / {reasons}"
        )
    return "\n".join(lines)
