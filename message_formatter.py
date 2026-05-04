from typing import Any


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
        lines.append(
            f"{index}. {item['code']} {item['name']} {item.get('pct_1d', 0):+.2f}% / {reasons}"
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
    cleaned = [title.replace("\n", " ").strip() for title in titles if title.strip()]
    if not cleaned:
        return "新聞面未提供明確加分"
    return cleaned[0][:42]


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

    if mode == "PRE":
        lines.append("🧭 開盤劇本:")
        lines.extend(f"- {line}" for line in _opening_scenarios(snapshot))
    else:
        lines.append("🔎 盤後復盤:")
        lines.extend(_post_market_review(snapshot))
        lines.append("👀 隔日觀察: 先看主軸族群是否續強，再決定是否追蹤焦點股")

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
