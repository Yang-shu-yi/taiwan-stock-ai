from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from data_layer import fetch_json, record_status


TWSE_DAILY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_DAILY_URL = (
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
)


def _number(value: Any) -> float | None:
    try:
        text = str(value).strip().replace(",", "")
        if text in {"", "--", "---", "除權", "除息"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _gregorian_date(raw: Any) -> str | None:
    text = "".join(character for character in str(raw or "") if character.isdigit())
    if len(text) != 7:
        return None
    try:
        year = int(text[:3]) + 1911
        parsed = date(year, int(text[3:5]), int(text[5:7]))
    except ValueError:
        return None
    return parsed.isoformat()


def _quote(
    *,
    trading_date: str,
    code: Any,
    open_price: Any,
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    source: str,
) -> dict[str, Any] | None:
    normalized_code = str(code or "").strip()
    closing_price = _number(close)
    if not normalized_code.isdigit() or closing_price is None or closing_price <= 0:
        return None
    return {
        "code": normalized_code,
        "date": trading_date,
        "Open": _number(open_price) or closing_price,
        "High": _number(high) or closing_price,
        "Low": _number(low) or closing_price,
        "Close": closing_price,
        "Volume": _number(volume) or 0.0,
        "source": source,
    }


def parse_twse_daily_quotes(
    payload: Any,
    requested_date: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return {}
    raw_date = str(payload.get("date") or "").strip()
    actual_date = (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        if len(raw_date) == 8 and raw_date.isdigit()
        else requested_date
    )
    for table in payload.get("tables") or []:
        fields = [str(value).strip() for value in table.get("fields") or []]
        if "證券代號" not in fields or "收盤價" not in fields:
            continue
        indexes = {field: index for index, field in enumerate(fields)}
        output: dict[str, dict[str, Any]] = {}
        for row in table.get("data") or []:
            if not isinstance(row, list):
                continue
            value = _quote(
                trading_date=actual_date,
                code=_row_value(row, indexes.get("證券代號")),
                open_price=_row_value(row, indexes.get("開盤價")),
                high=_row_value(row, indexes.get("最高價")),
                low=_row_value(row, indexes.get("最低價")),
                close=_row_value(row, indexes.get("收盤價")),
                volume=_row_value(row, indexes.get("成交股數")),
                source="TWSE",
            )
            if value is not None:
                output[value["code"]] = value
        return output
    return {}


def parse_tpex_daily_quotes(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        trading_date = _gregorian_date(row.get("Date"))
        if trading_date is None:
            continue
        value = _quote(
            trading_date=trading_date,
            code=row.get("SecuritiesCompanyCode"),
            open_price=row.get("Open"),
            high=row.get("High"),
            low=row.get("Low"),
            close=row.get("Close"),
            volume=row.get("TradingShares"),
            source="TPEX",
        )
        if value is not None:
            output[value["code"]] = value
    return output


def _row_value(row: list[Any], index: int | None) -> Any:
    if index is None or index < 0 or index >= len(row):
        return None
    return row[index]


def load_official_daily_quotes(
    market_date: str | None,
) -> dict[str, dict[str, Any]]:
    if not market_date:
        return {}
    compact_date = market_date.replace("-", "")
    output: dict[str, dict[str, Any]] = {}

    try:
        twse_payload = fetch_json(
            f"twse_daily_quotes_{compact_date}",
            TWSE_DAILY_URL,
            ttl_minutes=15,
            verify=False,
            params={
                "date": compact_date,
                "type": "ALLBUT0999",
                "response": "json",
            },
        )
        twse_quotes = parse_twse_daily_quotes(twse_payload, market_date)
        output.update(twse_quotes)
        actual_date = next(
            (item["date"] for item in twse_quotes.values()),
            market_date,
        )
        record_status(
            "twse_daily_quotes",
            bool(twse_quotes),
            TWSE_DAILY_URL,
            15,
            error=None if twse_quotes else "empty quote table",
            trading_date=actual_date,
            stale_reason=None if twse_quotes else "empty_quote_table",
        )
    except Exception:
        pass

    try:
        tpex_payload = fetch_json(
            "tpex_daily_quotes",
            TPEX_DAILY_URL,
            ttl_minutes=15,
        )
        tpex_quotes = parse_tpex_daily_quotes(tpex_payload)
        output.update(tpex_quotes)
        actual_date = next(
            (item["date"] for item in tpex_quotes.values()),
            market_date,
        )
        record_status(
            "tpex_daily_quotes",
            bool(tpex_quotes),
            TPEX_DAILY_URL,
            15,
            error=None if tpex_quotes else "empty quote table",
            trading_date=actual_date,
            stale_reason=None if tpex_quotes else "empty_quote_table",
        )
    except Exception:
        pass
    return output


def overlay_latest_quote(
    history: pd.DataFrame | None,
    quote: dict[str, Any] | None,
) -> pd.DataFrame | None:
    if history is None or history.empty or not quote:
        return history
    trading_date = str(quote.get("date") or "")
    close = _number(quote.get("Close"))
    if not trading_date or close is None or close <= 0:
        return history

    frame = history.copy()
    target = pd.Timestamp(trading_date)
    timezone = getattr(frame.index, "tz", None)
    if timezone is not None:
        target = target.tz_localize(timezone)
    latest = pd.Timestamp(frame.index[-1])
    if target < latest:
        return frame

    for column in frame.columns:
        if column in {"Dividends", "Stock Splits", "Capital Gains"}:
            frame.loc[target, column] = 0.0
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in frame.columns or column == "Close":
            frame.loc[target, column] = _number(quote.get(column))
    if "Adj Close" in frame.columns:
        frame.loc[target, "Adj Close"] = close
    return frame.sort_index()


def market_index_quote(
    market: dict[str, Any],
    market_date: str | None,
) -> dict[str, Any] | None:
    if not market_date:
        return None
    price = _number((market.get("tw_index") or {}).get("price"))
    if price is None or price <= 0:
        return None
    return {
        "date": market_date,
        "Open": price,
        "High": price,
        "Low": price,
        "Close": price,
        "Volume": 0.0,
        "source": "TWSE_INDEX",
    }
