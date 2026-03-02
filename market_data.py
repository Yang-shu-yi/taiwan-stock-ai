"""
market_data.py — 市場數據整合

整合台股大盤、美股四大指數、VIX、匯率、三大法人買賣超。
提供 get_all_market_data(mode) 作為主要入口。
"""

import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_NA = "N/A"


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def _yahoo_quote(symbol: str) -> dict:
    """從 Yahoo Finance chart API 取得報價 (price, chg, pct)"""
    try:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{symbol}?interval=1d&range=2d"
        )
        res = requests.get(url, headers=_HEADERS, timeout=10)
        res.raise_for_status()
        meta = res.json()["chart"]["result"][0]["meta"]
        price = float(meta["regularMarketPrice"])
        prev = float(meta.get("previousClose") or meta.get("chartPreviousClose"))
        chg = price - prev
        pct = (chg / prev * 100) if prev else 0.0
        return {"price": price, "chg": chg, "pct": pct}
    except Exception as e:
        _log(f"Yahoo quote {symbol} Error: {e}")
        return {"price": None, "chg": None, "pct": None}


# ==========================================
# 台股大盤
# ==========================================


def get_tw_index() -> dict:
    """取得台股加權指數 + 證交所成交值"""
    quote = _yahoo_quote("%5ETWII")

    result = {
        "price": f"{quote['price']:.0f}" if quote["price"] else _NA,
        "chg": f"{quote['chg']:.0f}" if quote["chg"] is not None else _NA,
        "pct": f"{quote['pct']:.2f}" if quote["pct"] is not None else _NA,
        "turnover": _NA,
    }

    # 證交所成交值
    try:
        res = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK",
            timeout=10,
            verify=False,
        )
        res.raise_for_status()
        data = res.json()
        if data:
            latest = data[-1]
            raw_value = float(latest["TradeValue"].replace(",", ""))
            result["turnover"] = f"{raw_value / 1e8:.0f}億"
            _log(f"🏛️ 證交所成交值: {result['turnover']}")
    except Exception as e:
        _log(f"TWSE turnover Error: {e}")

    return result


# ==========================================
# 美股指數 + VIX
# ==========================================

_US_SYMBOLS = {
    "S&P500": "%5EGSPC",
    "道瓊": "%5EDJI",
    "那斯達克": "%5EIXIC",
    "費半": "%5ESOX",
    "VIX": "%5EVIX",
}


def get_us_indices() -> dict:
    """取得美股四大指數 + VIX"""
    results: dict = {}
    for name, symbol in _US_SYMBOLS.items():
        q = _yahoo_quote(symbol)
        if q["price"] is not None:
            results[name] = {
                "price": f"{q['price']:.2f}",
                "chg": f"{q['chg']:+.2f}",
                "pct": f"{q['pct']:+.2f}",
            }
        else:
            results[name] = {"price": _NA, "chg": _NA, "pct": _NA}
        _log(f"🇺🇸 {name}: {results[name]['price']} ({results[name]['pct']}%)")
    return results


# ==========================================
# 匯率 USD/TWD
# ==========================================


def get_forex_twd() -> dict:
    """取得 USD/TWD 匯率"""
    q = _yahoo_quote("TWD=X")
    if q["price"] is not None:
        result = {
            "rate": f"{q['price']:.3f}",
            "chg": f"{q['chg']:+.3f}",
        }
    else:
        result = {"rate": _NA, "chg": _NA}
    _log(f"💱 USD/TWD: {result['rate']} ({result['chg']})")
    return result


# ==========================================
# 三大法人買賣超 (盤後)
# ==========================================


def get_institutional_trades() -> dict:
    """
    從證交所 OpenAPI 取三大法人買賣超金額。

    API: TWT38U (三大法人買賣金額統計表)
    回傳單位轉為「億元」。
    """
    result = {
        "foreign": _NA,
        "trust": _NA,
        "dealer": _NA,
        "total": _NA,
        "raw": [],
    }
    try:
        res = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/TWT38U",
            timeout=10,
            verify=False,
        )
        res.raise_for_status()
        data = res.json()

        if not data:
            _log("⚠️ TWT38U 回傳空資料 (可能非交易日)")
            return result

        result["raw"] = data

        for row in data:
            name = row.get("Name", "").strip()
            # 買賣差額欄位名稱
            diff_str = row.get("Difference", "") or row.get("difference", "") or "0"
            diff = float(str(diff_str).replace(",", ""))
            billions = diff / 1e8

            if "外資" in name and "自營" not in name:
                result["foreign"] = f"{billions:+.1f}億"
            elif "投信" in name:
                result["trust"] = f"{billions:+.1f}億"
            elif "自營商" in name:
                result["dealer"] = f"{billions:+.1f}億"

        # 計算合計
        parts = []
        for key in ["foreign", "trust", "dealer"]:
            val = result[key]
            if val != _NA:
                parts.append(float(str(val).replace("億", "").replace("+", "")))
        if parts:
            result["total"] = f"{sum(parts):+.1f}億"

        _log(
            f"🏦 法人: 外資{result['foreign']} "
            f"投信{result['trust']} 自營{result['dealer']}"
        )

    except Exception as e:
        _log(f"Institutional trades Error: {e}")

    return result


# ==========================================
# 融資融券 (盤後)
# ==========================================


def get_margin_trading() -> dict:
    """從證交所取融資融券變化"""
    result = {"margin_buy": _NA, "short_sell": _NA}
    try:
        res = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
            timeout=10,
            verify=False,
        )
        res.raise_for_status()
        data = res.json()

        if data:
            # MI_MARGN 最後一筆通常是合計
            last = data[-1]
            margin_buy = last.get("MarginPurchaseTodayBalance", "")
            short_sell = last.get("ShortSaleTodayBalance", "")
            if margin_buy:
                result["margin_buy"] = (
                    f"{float(str(margin_buy).replace(',', '')) / 1e4:.1f}萬張"
                )
            if short_sell:
                result["short_sell"] = (
                    f"{float(str(short_sell).replace(',', '')) / 1e4:.1f}萬張"
                )
            _log(f"📊 融資餘額: {result['margin_buy']} / 融券: {result['short_sell']}")

    except Exception as e:
        _log(f"Margin trading Error: {e}")

    return result


# ==========================================
# 主入口
# ==========================================


def get_all_market_data(mode: str = "PRE") -> dict:
    """
    整合所有市場數據。

    Args:
        mode: "PRE" (盤前) 或 "POST" (盤後)

    Returns:
        dict 包含:
            tw_index:      台股加權指數 + 成交值
            us_indices:    美股四大指數 + VIX
            forex:         USD/TWD 匯率
            institutional: 三大法人買賣超 (盤後才有)
            margin:        融資融券 (盤後才有)
    """
    _log(f"📊 開始抓取市場數據 (mode={mode})...")

    data: dict = {
        "tw_index": get_tw_index(),
        "us_indices": get_us_indices(),
        "forex": get_forex_twd(),
    }

    if mode == "POST":
        data["institutional"] = get_institutional_trades()
        data["margin"] = get_margin_trading()
    else:
        data["institutional"] = {
            "foreign": "待開盤",
            "trust": "待開盤",
            "dealer": "待開盤",
            "total": "待開盤",
        }
        data["margin"] = {"margin_buy": "待開盤", "short_sell": "待開盤"}

    _log("📊 市場數據抓取完成")
    return data
