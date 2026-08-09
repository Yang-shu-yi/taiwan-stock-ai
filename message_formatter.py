import re
import textwrap
from datetime import datetime
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


def _format_number(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        text = "" if value is None else str(value).strip()
        return text or "N/A"
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_turnover(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    match = re.fullmatch(r"([+-]?[\d,]+(?:\.\d+)?)\s*(.*)", text)
    if not match:
        return text or "N/A"
    number, unit = match.groups()
    formatted = _format_number(number)
    return f"{formatted} {unit}".strip()


def _format_pct(value: Any) -> str:
    pct = _to_float(value)
    if pct is None:
        text = "" if value is None else str(value).strip()
        return text or "N/A"
    return f"{pct:+.2f}%"


def _score_light(value: Any) -> str:
    score = _to_float(value)
    if score is None:
        return "⚪"
    if score >= 75:
        return "🟢"
    if score >= 55:
        return "🟡"
    return "🔴"


def _score_text(value: Any) -> str:
    score = _to_float(value)
    return "N/A" if score is None else f"{score:.0f}"


def _wrapped_advice_lines(label: str, value: Any, width: int = 32) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    prefix = f"   {label}："
    content_width = max(12, width - len(prefix))
    chunks = textwrap.wrap(
        text,
        width=content_width,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [text]
    return [
        f"{prefix if index == 0 else '   '}{chunk}"
        for index, chunk in enumerate(chunks)
    ]


def _report_date_label(snapshot: dict[str, Any]) -> str:
    date = str(snapshot.get("report_date") or _snapshot_date(snapshot) or "")
    if not date:
        return ""
    return _short_date(date)


def _short_date(date: str) -> str:
    try:
        return datetime.strptime(date, "%Y-%m-%d").strftime("%m/%d")
    except ValueError:
        return date


def _market_date(snapshot: dict[str, Any]) -> str | None:
    tw = snapshot.get("market", {}).get("tw_index", {})
    date = str(
        snapshot.get("market_data_date")
        or tw.get("trading_date")
        or next(
            (
                item.get("price_date")
                for item in snapshot.get("tw_candidates", [])
                if item.get("price_date")
            ),
            "",
        )
    ).strip()
    return date or None


def _market_reference_label(snapshot: dict[str, Any]) -> str:
    tw = snapshot.get("market", {}).get("tw_index", {})
    as_of = str(tw.get("as_of") or "").strip()
    if as_of:
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            return parsed.strftime("%m/%d %H:%M")
        except ValueError:
            pass
    market_date = _market_date(snapshot)
    return f"{_short_date(market_date)} 收盤" if market_date else ""


def _theme_lines(snapshot: dict[str, Any], limit: int = 3) -> list[str]:
    theme_items = list(snapshot.get("theme_summary", []))
    if not theme_items:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in snapshot.get("tw_candidates", [])[:5]:
            grouped.setdefault(str(item.get("theme") or "其他"), []).append(item)
        theme_items = [
            {
                "theme": theme,
                "score": sum(_to_float(item.get("score")) or 0 for item in items) / len(items),
                "leaders": [f"{item.get('code')} {item.get('name')}" for item in items],
            }
            for theme, items in grouped.items()
        ]
        theme_items.sort(key=lambda item: _to_float(item.get("score")) or 0, reverse=True)
    specific_items = [
        item for item in theme_items if item.get("theme") not in {"電子", "其他"}
    ]
    if specific_items:
        theme_items = specific_items + [item for item in theme_items if item not in specific_items]

    lines: list[str] = []
    for rank, item in enumerate(theme_items[:limit], start=1):
        theme = str(item.get("theme") or "").strip()
        if not theme:
            continue
        leader = next(
            (
                str(value).strip()
                for value in item.get("leaders", [])
                if str(value).strip()
            ),
            "",
        )
        score = _to_float(item.get("score"))
        score_text = f"｜強度 {score:.1f}" if score is not None else ""
        lines.append(f"{rank}. {theme}{score_text}{f'｜{leader}' if leader else ''}")
    return lines


def _focus_lines(snapshot: dict[str, Any], limit: int = 5) -> list[str]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [
        *snapshot.get("actionable_candidates", []),
        *snapshot.get("tw_candidates", []),
    ]:
        code = str(item.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        items.append(item)
        if len(items) >= limit:
            break
    if not items:
        return ["• 名單來源異常，今日暫停新增部位"]
    lines = []
    for rank, item in enumerate(items, start=1):
        reasons = [str(value).strip() for value in item.get("reasons", []) if str(value).strip()]
        risks = [
            str(value).strip()
            for value in item.get("risk_flags", [])
            if str(value).strip() and "未見明顯" not in str(value)
        ]
        preferred = risks[0] if risks else ""
        if not preferred and (_to_float(item.get("vol_ratio")) or 0) >= 1.2:
            preferred = next((reason for reason in reasons if "量能" in reason), "")
        if not preferred:
            preferred = next((reason for reason in reasons if "強於大盤" in reason), "")
        if not preferred:
            preferred = next((reason for reason in reasons if "量能" in reason), "")
        if not preferred:
            preferred = next((reason for reason in reasons if "均線結構" in reason), "")
        if not preferred:
            preferred = reasons[0] if reasons else "等待量價確認"
        preferred = preferred.replace("近 20 日", "20日").replace(" 20 日", "20日")
        invalidation = next(
            (str(value).strip() for value in item.get("invalidations", []) if str(value).strip()),
            "跌破前一交易日低點",
        ).replace("跌破 MA", "跌破MA")
        theme = str(item.get("theme") or "未分類")
        price = _format_number(item.get("price"))
        score = _to_float(item.get("score"))
        score_text = f"{score:.1f}" if score is not None else "N/A"
        entry_score = _to_float(item.get("entry_score"))
        entry_score_text = f"{entry_score:.1f}" if entry_score is not None else "N/A"
        status = str(
            item.get("entry_status_label")
            or item.get("confidence")
            or "等待確認"
        )
        fallback_action = {
            "提前觀察": "轉強初期，等量價確認",
            "可分批布局": "可依停損小量分批",
            "等待回測": "已發動，等回測，不追價",
            "過度延伸、不追": "乖離過大，不追價",
        }.get(status, preferred)
        assessment = item.get("company_assessment") or {}
        quality = assessment.get("company_quality_score", item.get("company_quality_score"))
        valuation = assessment.get(
            "valuation_attractiveness_score",
            item.get("valuation_attractiveness_score"),
        )
        timing = assessment.get("entry_timing_score", item.get("entry_timing_score", entry_score))
        event_risk = assessment.get("event_risk_level", item.get("event_risk_level"))
        opportunity = assessment.get("opportunity_label", item.get("opportunity_label"))
        fundamental = assessment.get("fundamental_summary", item.get("fundamental_summary"))
        action_text = assessment.get(
            "plain_language_advice",
            item.get("plain_language_advice") or fallback_action,
        )
        lines.extend(
            [
                f"{rank}. {item['code']} {item['name']}｜{theme}｜{price}",
                f"   綜合 {score_text} {_score_light(score)}｜{status}",
            ]
        )
        if assessment or quality is not None or valuation is not None:
            lines.extend(
                [
                    f"   品質 {_score_text(quality)}｜估值 {_score_text(valuation)}｜時機 {_score_text(timing)}",
                    f"   事件風險 {event_risk or '待確認'}｜{opportunity or '持續觀察'}",
                ]
            )
            lines.extend(_wrapped_advice_lines("基本面", fundamental))
        else:
            lines.append(f"   進場 {entry_score_text}｜資料待補")
        lines.extend(_wrapped_advice_lines("建議", action_text))
        lines.append(f"   風控：{invalidation}")
    return lines


def _early_watch_lines(snapshot: dict[str, Any], limit: int = 3) -> list[str]:
    items = snapshot.get("early_watch_candidates", [])[:limit]
    lines: list[str] = []
    for rank, item in enumerate(items, start=1):
        reasons = [
            str(value).strip().replace("近 3 日", "3日")
            for value in item.get("early_watch_reasons", [])
            if str(value).strip()
        ]
        reason = "、".join(reasons[:2]) or "轉強條件開始形成"
        price = _format_number(item.get("price"))
        radar_score = _to_float(item.get("early_watch_score"))
        entry_score = _to_float(item.get("entry_score"))
        radar_text = f"{radar_score:.1f}" if radar_score is not None else "N/A"
        entry_text = f"{entry_score:.1f}" if entry_score is not None else "N/A"
        lines.extend(
            [
                f"{rank}. {item['code']} {item['name']}｜{price}",
                f"   雷達 {radar_text}｜進場 {entry_text}",
                f"   轉折：{reason}",
            ]
        )
    return lines


def _small_mid_lines(snapshot: dict[str, Any], limit: int = 3) -> list[str]:
    return [
        f"• {item['code']} {item['name']}"
        for item in snapshot.get("small_mid_candidates", [])[:limit]
    ]


def _strategy_lines(snapshot: dict[str, Any], mode: str, tw_pct: float | None) -> list[str]:
    optimization = snapshot.get("strategy_optimization") or {}
    posture = optimization.get("posture", "normal")
    label = "防守" if posture == "defensive" else "一般"
    period = "明日" if mode == "POST" else "今日"
    if posture == "defensive" or (tw_pct is not None and tw_pct <= -1):
        open_high = "反彈不追；先確認大盤止穩"
        flat = "只看逆勢抗跌且量能回升者"
        open_low = "未守前低前不新增部位"
    elif tw_pct is not None and tw_pct >= 1:
        open_high = "不追第一段；15分鐘後量價續強再看"
        flat = "Top 5 強於大盤者優先，量縮者降級"
        open_low = "守住昨低或MA20才保留觀察"
    else:
        open_high = "先看量價，不追開盤急拉"
        flat = "Top 5 中率先放量轉強者優先"
        open_low = "跌破昨低者取消，等待大盤止穩"
    return [
        f"🎯 {period}執行計畫｜{label}",
        f"• 開高：{open_high}",
        f"• 平盤：{flat}",
        f"• 開低：{open_low}",
    ]


def _market_view_lines(snapshot: dict[str, Any], mode: str, tw_pct: float | None) -> list[str]:
    if tw_pct is None:
        structure = "大盤方向待確認，先以個股相對強弱為主"
    elif tw_pct >= 2:
        structure = "前一交易日強勢長紅，多方結構占優"
    elif tw_pct >= 1:
        structure = "指數維持偏多，仍需確認量價是否延續"
    elif tw_pct <= -1:
        structure = "指數結構偏弱，優先控制回撤與追價風險"
    else:
        structure = "指數偏震盪，選股重於預測大盤方向"

    if mode == "PRE" and tw_pct is not None and tw_pct >= 1:
        rhythm = "大漲後不預設續漲；開高先等籌碼沉澱"
    elif mode == "PRE":
        rhythm = "開盤先觀察15分鐘，再確認主流與成交量"
    else:
        rhythm = "隔日只保留量價未破壞、仍強於大盤者"

    provenance = snapshot.get("candidate_provenance") or {}
    if provenance.get("mode") == "last_valid_snapshot":
        source = f"沿用 {str(provenance.get('as_of') or '')[5:].replace('-', '/')} 最近有效快照"
    else:
        source = "名單採本次正式評分排序"
    return ["🧭 專業判讀", f"• 結構：{structure}", f"• 節奏：{rhythm}", f"• 名單：{source}"]


def _data_warning_lines(snapshot: dict[str, Any]) -> list[str]:
    status = snapshot.get("data_status") or {}
    report_date = _snapshot_date(snapshot)
    market_date = _market_date(snapshot) or report_date
    warnings = []
    for key, item in status.items():
        comparison_date = report_date if key == "news" else market_date
        if _should_show_data_status(key, item, comparison_date):
            warnings.append(_format_data_warning(key, item, comparison_date))
    warnings = [warning for warning in warnings if warning]
    excluded = int(
        (snapshot.get("selection_coverage") or {}).get("stale_price_excluded_count") or 0
    )
    if excluded:
        warnings.append(f"已排除 {excluded} 檔日期不一致行情")
    if not warnings:
        return []
    return ["⚠️ 資料提醒", *(f"• {warning}" for warning in warnings[:2])]


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


def _should_show_data_status(key: str, item: Any, snapshot_date: str | None) -> bool:
    if key not in _DATA_STATUS_LABELS:
        return False
    return _is_data_status_notable(item, snapshot_date)


def _is_data_status_notable(item: Any, snapshot_date: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    trading_date = str(item.get("trading_date") or "").strip()
    return bool(
        not item.get("ok")
        or item.get("fallback_used")
        or item.get("stale_reason")
        or (snapshot_date and trading_date and trading_date != snapshot_date)
    )


def _format_data_warning(key: str, item: Any, snapshot_date: str | None) -> str:
    if not isinstance(item, dict):
        return ""

    label = _DATA_STATUS_LABELS[key]
    trading_date = str(item.get("trading_date") or "").strip()
    short_date = (
        trading_date[5:].replace("-", "/")
        if len(trading_date) >= 10
        else trading_date
    )

    if not item.get("ok") and (item.get("fallback_used") or item.get("cached")):
        return f"{label}使用快取資料"
    if not item.get("ok"):
        return f"{label}暫時無法更新"
    if item.get("fallback_used"):
        if snapshot_date and trading_date and trading_date != snapshot_date:
            return f"{label}使用 {short_date} 備援資料"
        return f"{label}使用備援資料"
    if snapshot_date and trading_date and trading_date != snapshot_date:
        return f"{label}仍為 {short_date} 資料"
    return f"{label}資料可能延遲"


_DATA_STATUS_LABELS = {
    "news": "新聞",
    "yahoo_^TWII_1d_2d": "大盤指數",
    "twse_institutional": "法人",
    "twse_market_snapshot": "台股清單",
    "twse_daily_quotes": "上市收盤行情",
    "tpex_daily_quotes": "上櫃收盤行情",
    "twse_margin": "融資券",
    "twse_turnover": "成交值",
}


def format_market_report(snapshot: dict[str, Any]) -> str:
    mode = str(snapshot.get("mode", "PRE")).upper()
    market = snapshot.get("market", {})
    tw = market.get("tw_index", {})
    tw_pct = _to_float(tw.get("pct", "0"))
    date_label = _report_date_label(snapshot)
    title = "🌅 台股盤前策略" if mode == "PRE" else "🌙 台股盤後策略"
    if date_label:
        title = f"{title}｜{date_label}"
    market_summary = (
        f"{_format_number(tw.get('price', 'N/A'))}｜"
        f"{_format_pct(tw.get('pct'))}｜{_market_bias_label(tw_pct)}"
    )

    market_reference = _market_reference_label(snapshot)
    market_date_text = f"｜{market_reference}" if market_reference else ""
    sections = [
        [title],
        [
            f"📊 台股{market_date_text}",
            market_summary,
            f"成交 {_format_turnover(tw.get('turnover', 'N/A'))}",
        ],
        _market_view_lines(snapshot, mode, tw_pct),
        ["🔥 族群排序", *_theme_lines(snapshot, limit=3)],
        ["🎯 今日行動分層", *_focus_lines(snapshot, limit=5)],
    ]

    early_watch_lines = _early_watch_lines(snapshot, limit=3)
    if early_watch_lines:
        sections.append(["📡 提前雷達｜容許較多誤報", *early_watch_lines])
    sections.append(_strategy_lines(snapshot, mode, tw_pct))
    data_warnings = _data_warning_lines(snapshot)
    if data_warnings:
        sections.append(data_warnings)
    sections.append(["⚠️ 僅供資料參考，非投資建議。"])

    return "\n\n".join("\n".join(section) for section in sections)


def format_intraday_alert(item: dict[str, Any]) -> str:
    entry_status = str(item.get("entry_status") or "")
    if item.get("status") != "UP":
        direction = "📉 轉弱確認"
    elif entry_status == "early_watch":
        direction = "📡 提前雷達轉強確認"
    elif entry_status == "scale_in":
        direction = "✅ 可執行名單續強"
    else:
        direction = "⏳ 盤中急拉，不追價"
    price = item.get("price", 0.0)
    pct = item.get("pct", 0.0)
    rsi = item.get("rsi", 0.0)
    vol_ratio = item.get("vol_ratio")
    vol_text = "N/A" if vol_ratio is None else f"{vol_ratio:.2f}x"
    if pct <= 0:
        risk_line = "風險: 不要急著接弱勢反彈"
    elif entry_status == "scale_in":
        risk_line = "執行: 只依原停損小量分批，不因急拉加碼"
    elif entry_status == "early_watch":
        risk_line = "觀察: 確認收盤能否守住，尚非正式進場訊號"
    else:
        risk_line = "風險: 不追價，等下一次拉回確認"
    daily_label = item.get("entry_status_label") or "等待確認"
    entry_score = item.get("entry_score")
    entry_text = "N/A" if entry_score is None else f"{float(entry_score):.1f}"
    return "\n".join(
        [
            "[⚡ 盤中警示]",
            f"股票: {item['code']} {item['name']}",
            f"狀態: {direction}",
            f"價格: {price:.2f} ({pct:+.2f}%)",
            f"訊號: RSI {rsi:.1f} / 量比 {vol_text}",
            f"日線: {daily_label} / 進場 {entry_text}",
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
    items = [
        *snapshot.get("actionable_candidates", []),
        *snapshot.get("tw_candidates", []),
    ]
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        code = str(item.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        deduplicated.append(item)
    items = deduplicated[:limit]
    lines = ["[📋 今日候選股]"]
    if not items:
        lines.append("目前沒有候選資料")
        return "\n".join(lines)
    for item in items:
        source = " / 中小雷達" if item.get("source") == "small_mid_radar" else ""
        reasons = "、".join(item.get("reasons", [])[:2]) or "訊號整體偏強"
        status = item.get("entry_status_label") or "等待確認"
        assessment = item.get("company_assessment") or {}
        lines.extend(
            [
                f"{item['code']} {item['name']}{source}",
                f"綜合 {_score_text(item.get('score'))} {_score_light(item.get('score'))} / 進場 {_score_text(item.get('entry_score'))} / {status}",
                f"品質 {_score_text(assessment.get('company_quality_score'))} / 估值 {_score_text(assessment.get('valuation_attractiveness_score'))} / 事件 {assessment.get('event_risk_level', '待確認')}",
                f"重點：{assessment.get('opportunity_label') or reasons}",
            ]
        )
    return "\n".join(lines)
