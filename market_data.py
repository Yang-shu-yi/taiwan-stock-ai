"""
Market data aggregation for the daily report.

All network reads go through data_layer so the pipeline can expose source
freshness and fallback status in daily_candidates.json.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from data_layer import fetch_json, record_status, twse_json, yahoo_chart


_NA = "N/A"
LOCAL_TZ = ZoneInfo("Asia/Taipei")

_US_SYMBOLS = {
    "S&P500": "^GSPC",
    "道瓊": "^DJI",
    "那斯達克": "^IXIC",
    "費半": "^SOX",
    "VIX": "^VIX",
}


def _log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("+", "").replace("%", ""))
    except Exception:
        return None


def _format_signed(value: float | None, digits: int = 2) -> str:
    if value is None:
        return _NA
    return f"{value:+.{digits}f}"


def _format_plain(value: float | None, digits: int = 2) -> str:
    if value is None:
        return _NA
    return f"{value:.{digits}f}"


def _recent_twse_dates(days: int = 7) -> list[str]:
    today = datetime.now(LOCAL_TZ).date()
    return [
        today.fromordinal(today.toordinal() - offset).strftime("%Y%m%d")
        for offset in range(days)
    ]


def _yahoo_quote(symbol: str) -> dict[str, Any]:
    try:
        data = yahoo_chart(symbol, interval="1d", range_="2d")
        result = data["chart"]["result"][0]
        meta = result["meta"]
        price = _to_float(meta.get("regularMarketPrice"))
        previous = _to_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
        if price is None or previous is None:
            return {"price": None, "chg": None, "pct": None, "name": ""}
        change = price - previous
        pct = (change / previous * 100.0) if previous else 0.0
        return {
            "price": price,
            "chg": change,
            "pct": pct,
            "name": meta.get("shortName") or meta.get("longName") or symbol,
        }
    except Exception as exc:
        _log(f"Yahoo quote failed for {symbol}: {exc}")
        return {"price": None, "chg": None, "pct": None, "name": ""}


def get_tw_index() -> dict[str, str]:
    quote = _yahoo_quote("^TWII")
    result = {
        "price": _format_plain(quote["price"], 0),
        "chg": _format_signed(quote["chg"], 0),
        "pct": _format_signed(quote["pct"], 2),
        "turnover": _NA,
    }

    try:
        rows = twse_json(
            "twse_turnover",
            "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK",
            ttl_minutes=15,
        )
        if isinstance(rows, list) and rows:
            latest = rows[-1]
            raw_value = _to_float(latest.get("TradeValue"))
            if raw_value is not None:
                result["turnover"] = f"{raw_value / 1e8:.0f}億"
    except Exception as exc:
        _log(f"TWSE turnover failed: {exc}")

    return result


def get_us_indices() -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for label, symbol in _US_SYMBOLS.items():
        quote = _yahoo_quote(symbol)
        results[label] = {
            "price": _format_plain(quote["price"], 2),
            "chg": _format_signed(quote["chg"], 2),
            "pct": _format_signed(quote["pct"], 2),
        }
    return results


def get_forex_twd() -> dict[str, str]:
    quote = _yahoo_quote("TWD=X")
    return {
        "rate": _format_plain(quote["price"], 3),
        "chg": _format_signed(quote["chg"], 3),
    }


def get_institutional_trades() -> dict[str, Any]:
    result: dict[str, Any] = {
        "foreign": _NA,
        "trust": _NA,
        "dealer": _NA,
        "total": _NA,
        "raw": [],
    }
    try:
        rows = twse_json(
            "twse_institutional",
            "https://openapi.twse.com.tw/v1/exchangeReport/TWT38U",
            ttl_minutes=60,
        )
        if not isinstance(rows, list) or not rows:
            return result
        result["raw"] = rows

        values: dict[str, float] = {}
        for row in rows:
            name = str(row.get("Name", "")).strip()
            diff = _to_float(
                row.get("Difference")
                or row.get("difference")
                or row.get("買賣差額")
                or row.get("買賣超")
            )
            if diff is None:
                continue
            amount = diff / 1e8
            if "外資" in name and "自營" not in name:
                values["foreign"] = amount
            elif "投信" in name:
                values["trust"] = amount
            elif "自營商" in name:
                values["dealer"] = amount

        for key, value in values.items():
            result[key] = f"{value:+.1f}億"
        if values:
            result["total"] = f"{sum(values.values()):+.1f}億"
    except Exception as exc:
        _log(f"Institutional trades failed: {exc}")
        fallback = _get_institutional_trades_bfi82u()
        if fallback:
            return fallback
    return result


def _get_institutional_trades_bfi82u() -> dict[str, Any] | None:
    url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
    for date_value in _recent_twse_dates():
        try:
            payload = fetch_json(
                f"twse_institutional_bfi82u_{date_value}",
                url,
                ttl_minutes=60,
                params={
                    "dayDate": date_value,
                    "type": "day",
                    "response": "json",
                    "_": str(int(datetime.now().timestamp())),
                },
                verify=False,
            )
        except Exception:
            continue

        rows = payload.get("data") if isinstance(payload, dict) else None
        if not rows:
            continue

        result: dict[str, Any] = {
            "foreign": _NA,
            "trust": _NA,
            "dealer": _NA,
            "total": _NA,
            "raw": rows,
            "fallback_used": True,
            "source_date": date_value,
        }
        values: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, list) or len(row) < 2:
                continue
            name = str(row[0])
            amount = _to_float(row[-1])
            if amount is None:
                continue
            billions = amount / 1e8
            if "外資" in name and not name.startswith("外資自營商"):
                values["foreign"] = billions
            elif "投信" in name:
                values["trust"] = billions
            elif "自營商" in name and "合計" not in name:
                values["dealer"] = values.get("dealer", 0.0) + billions
            elif "合計" in name:
                values["total"] = billions

        for key in ["foreign", "trust", "dealer", "total"]:
            if key in values:
                result[key] = f"{values[key]:+.1f}億"
        if values and result["total"] == _NA:
            result["total"] = f"{sum(v for k, v in values.items() if k != 'total'):+.1f}億"
        record_status(
            "twse_institutional",
            True,
            "https://www.twse.com.tw/rwd/zh/fund/BFI82U",
            60,
            cached=False,
            trading_date=f"{date_value[:4]}-{date_value[4:6]}-{date_value[6:]}",
            fallback_used=True,
            stale_reason="primary_openapi_failed",
        )
        return result
    return None


def get_margin_trading() -> dict[str, str]:
    result = {"margin_buy": _NA, "short_sell": _NA}
    try:
        rows = twse_json(
            "twse_margin",
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
            ttl_minutes=60,
        )
        if not isinstance(rows, list) or not rows:
            return result
        latest = rows[-1]
        margin_buy = _first_numeric(
            latest,
            [
                "MarginPurchaseTodayBalance",
                "marginPurchaseTodayBalance",
                "融資今日餘額",
                "融資餘額",
            ],
        )
        short_sell = _first_numeric(
            latest,
            [
                "ShortSaleTodayBalance",
                "shortSaleTodayBalance",
                "融券今日餘額",
                "融券餘額",
            ],
        )
        if margin_buy is not None:
            result["margin_buy"] = f"{margin_buy / 1e4:.1f}萬張"
        if short_sell is not None:
            result["short_sell"] = f"{short_sell / 1e4:.1f}萬張"
    except Exception as exc:
        _log(f"Margin trading failed: {exc}")
    return result


def _first_numeric(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _to_float(row.get(key))
        if value is not None:
            return value
    return None


def get_watchlist_quotes(watchlist: list[str]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for code in watchlist:
        symbol = f"{code}.TW" if code.isdigit() else code
        quote = _yahoo_quote(symbol)
        if quote["price"] is None and code.isdigit():
            quote = _yahoo_quote(f"{code}.TWO")
        quotes[code] = {
            "name": quote["name"],
            "price": quote["price"],
            "chg": quote["chg"],
            "pct": quote["pct"],
        }
    return quotes


def get_all_market_data(mode: str = "PRE") -> dict[str, Any]:
    normalized_mode = (mode or "PRE").upper()
    data: dict[str, Any] = {
        "tw_index": get_tw_index(),
        "us_indices": get_us_indices(),
        "forex": get_forex_twd(),
    }
    if normalized_mode == "POST":
        data["institutional"] = get_institutional_trades()
        data["margin"] = get_margin_trading()
    else:
        data["institutional"] = {
            "foreign": "待盤後",
            "trust": "待盤後",
            "dealer": "待盤後",
            "total": "待盤後",
        }
        data["margin"] = {"margin_buy": "待盤後", "short_sell": "待盤後"}
    return data
