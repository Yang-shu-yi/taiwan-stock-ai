import os
import json
import time
import traceback
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import ta
import twstock
from dotenv import load_dotenv

from alert_store import append_alert
from watchlist_store import (
    load_watchlist_file,
    save_watchlist_file,
)

try:
    import gspread
except Exception:
    gspread = None

load_dotenv()

LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TARGET_ID = os.getenv("LINE_TARGET_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
WATCHLIST_SPREADSHEET_ID = os.getenv("WATCHLIST_SPREADSHEET_ID")
WATCHLIST_SHEET_NAME = os.getenv("WATCHLIST_SHEET_NAME", "watchlist")

WATCHLIST_CODES = os.getenv("WATCHLIST_CODES", "")
WATCHLIST_SEED_CODES = os.getenv("WATCHLIST_SEED_CODES", "")

INTRADAY_NOTIFY_LINE = os.getenv("INTRADAY_NOTIFY_LINE", "0").strip().lower() in [
    "1",
    "true",
    "yes",
    "y",
]
CHECK_INTERVAL_SEC = int(os.getenv("INTRADAY_CHECK_INTERVAL_SEC", "60"))
PRICE_UP_PCT = float(os.getenv("INTRADAY_PRICE_UP_PCT", "2.0"))
PRICE_DOWN_PCT = float(os.getenv("INTRADAY_PRICE_DOWN_PCT", "-2.0"))
RSI_OVERBOUGHT = float(os.getenv("INTRADAY_RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD = float(os.getenv("INTRADAY_RSI_OVERSOLD", "30"))
VOLUME_SPIKE_MULT = float(os.getenv("INTRADAY_VOLUME_SPIKE_MULT", "2.5"))
ALERT_COOLDOWN_MIN = int(os.getenv("INTRADAY_ALERT_COOLDOWN_MIN", "30"))
TG_POLL_INTERVAL_SEC = int(os.getenv("INTRADAY_TG_POLL_SEC", "10"))

WATCHLIST_FILE = "watchlist.json"

# Used only when no watchlist is configured.
DEFAULT_WATCHLIST_SEED = [
    # US mega caps / ETFs
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "SPY",
    "QQQ",
    # Crypto (Yahoo tickers)
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
]


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def push_line_message(msg):
    if not LINE_CHANNEL_TOKEN or not LINE_TARGET_ID:
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": LINE_TARGET_ID,
        "messages": [{"type": "text", "text": msg[:4500]}],
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
    except Exception:
        log(f"Error sending Line message: {traceback.format_exc()}")
        return


def push_telegram_message(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
    except Exception:
        log(f"Error sending Telegram message: {traceback.format_exc()}")
        return


def notify_all(msg):
    if INTRADAY_NOTIFY_LINE:
        push_line_message(msg)
    push_telegram_message(msg)


def is_market_open():
    # Backward-compatible alias. Prefer is_session_open_for_code().
    return is_session_open_for_code("2330", datetime.now())


def detect_symbol_type(code: str) -> str:
    c = (code or "").strip()
    if not c:
        return "UNKNOWN"
    if c.isdigit() and c in twstock.codes:
        return "TW"

    upper = c.upper()
    if upper.endswith("-USD") or upper.endswith("-USDT"):
        return "CRYPTO"
    if upper.endswith(".TW") or upper.endswith(".TWO"):
        return "TW_YF"
    return "US"


def is_session_open_for_symbol(symbol_type: str, now: datetime) -> bool:
    st = (symbol_type or "").upper()
    if st == "CRYPTO":
        return True

    if st in ["TW", "TW_YF"]:
        try:
            n = now.astimezone(ZoneInfo("Asia/Taipei"))
        except Exception:
            n = now
        if n.weekday() >= 5:
            return False
        hhmm = n.hour * 100 + n.minute
        return 900 <= hhmm <= 1330

    if st == "US":
        try:
            n = now.astimezone(ZoneInfo("America/New_York"))
        except Exception:
            n = now
        if n.weekday() >= 5:
            return False
        hhmm = n.hour * 100 + n.minute
        return 930 <= hhmm <= 1600

    return False


def is_session_open_for_code(code: str, now: datetime) -> bool:
    return is_session_open_for_symbol(detect_symbol_type(code), now)


def load_watchlist():
    file_list = load_watchlist_file(WATCHLIST_FILE)
    if file_list:
        return file_list
    if WATCHLIST_CODES.strip():
        return [c.strip() for c in WATCHLIST_CODES.split(",") if c.strip()]
    if os.path.exists("stock_database.json"):
        try:
            with open("stock_database.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            return [k for k, v in data.items() if v.get("status") == "RED"]
        except Exception:
            return []
    return []


def seed_watchlist_if_empty():
    # Do not overwrite existing file-based watchlist.
    existing = load_watchlist_file(WATCHLIST_FILE)
    if existing:
        return

    # If user explicitly configured watchlist via env, do nothing.
    if WATCHLIST_CODES.strip():
        return

    # If stock_database has RED entries, do nothing (keeps legacy behavior).
    if os.path.exists("stock_database.json"):
        try:
            with open("stock_database.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            red = [k for k, v in data.items() if v.get("status") == "RED"]
            if red:
                return
        except Exception:
            pass

    if WATCHLIST_SEED_CODES.strip():
        seed = parse_codes([WATCHLIST_SEED_CODES])
    else:
        seed = list(DEFAULT_WATCHLIST_SEED)

    if not seed:
        return

    save_watchlist(seed)
    log(f"🌱 初始化 watchlist: {', '.join(seed)}")


def yahoo_chart(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1m", "range": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, params=params, headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()


def save_watchlist(codes):
    save_watchlist_file(codes, WATCHLIST_FILE)
    sync_watchlist_to_sheet(codes)


def get_sheet_client():
    if not gspread:
        return None
    sheet_id = WATCHLIST_SPREADSHEET_ID or SPREADSHEET_ID
    if not sheet_id or not GOOGLE_SERVICE_ACCOUNT_FILE:
        return None
    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
        return None
    try:
        return gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)
    except Exception:
        return None


def sync_watchlist_to_sheet(codes):
    client = get_sheet_client()
    if not client:
        return
    try:
        sheet_id = WATCHLIST_SPREADSHEET_ID or SPREADSHEET_ID
        if not sheet_id:
            return
        sh = client.open_by_key(sheet_id)
        try:
            ws = sh.worksheet(WATCHLIST_SHEET_NAME)
        except Exception:
            ws = sh.add_worksheet(title=WATCHLIST_SHEET_NAME, rows=1000, cols=1)
        ws.clear()
        if codes:
            ws.update("A1", [[c] for c in sorted(list(set(codes)))])
    except Exception:
        return


def parse_codes(tokens):
    raw = []
    for t in tokens:
        raw.extend([x.strip() for x in str(t).split(",")])

    out = []
    valid_tw = set(twstock.codes.keys())
    for code in raw:
        if not code:
            continue
        if code.isdigit():
            if code in valid_tw:
                out.append(code)
            continue

        upper = code.upper()
        # Allow Yahoo tickers like AAPL, TSLA, BTC-USD, ^GSPC, 2330.TW
        if not re.fullmatch(r"[A-Z0-9.\-\^]{1,20}", upper):
            continue
        out.append(upper)

    return out


def handle_command(text, current):
    if not text:
        return current, None
    parts = text.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ["/help", "/start"]:
        return current, "指令: /add 2330,AAPL,BTC-USD /del 2330 /list"

    if cmd == "/list":
        if not current:
            return current, "目前清單為空。"
        return current, "\n".join(current)

    if cmd == "/add":
        codes = parse_codes(args)
        if not codes:
            return current, "格式: /add 2330,2317,AAPL,BTC-USD"
        new_list = sorted(list(set(current + codes)))
        save_watchlist(new_list)
        return new_list, f"已加入: {', '.join(codes)}"

    if cmd == "/del":
        codes = parse_codes(args)
        if not codes:
            return current, "格式: /del 2330"
        new_list = [c for c in current if c not in codes]
        save_watchlist(new_list)
        return new_list, f"已刪除: {', '.join(codes)}"

    return current, None


def poll_telegram(last_update_id, watchlist):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return last_update_id, watchlist
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 0, "offset": last_update_id + 1}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        updates = data.get("result", [])
        for upd in updates:
            last_update_id = max(last_update_id, upd.get("update_id", last_update_id))
            msg = upd.get("message", {})
            chat = msg.get("chat", {})
            if str(chat.get("id")) != str(TELEGRAM_CHAT_ID):
                continue
            text = msg.get("text", "")
            watchlist, reply = handle_command(text, watchlist)
            if reply:
                push_telegram_message(reply)
    except Exception:
        log(f"Error polling Telegram: {traceback.format_exc()}")
        return last_update_id, watchlist
    return last_update_id, watchlist


def analyze_symbol(code):
    c = (code or "").strip()
    if not c:
        return None

    name = c
    symbol_type = detect_symbol_type(c)
    if symbol_type == "TW":
        market = twstock.codes[c].market
        suffix = ".TW" if market == "上市" else ".TWO"
        symbol = f"{c}{suffix}"
        name = twstock.codes[c].name
    else:
        symbol = c

    data = yahoo_chart(symbol)
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    meta = result[0].get("meta", {})
    timestamp = result[0].get("timestamp", [])
    indicators = result[0].get("indicators", {}).get("quote", [])
    if not timestamp or not indicators:
        return None

    quote = indicators[0]
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])
    closes = [c for c in closes if c is not None]
    volumes = [v for v in volumes if v is not None]
    if len(closes) < 20:
        return None

    close_series = pd.Series(closes, dtype="float64")
    rsi = ta.momentum.RSIIndicator(close_series, window=14).rsi().iloc[-1]
    last_price = float(closes[-1])
    prev_close = float(
        meta.get("previousClose") or meta.get("chartPreviousClose") or last_price
    )
    pct = ((last_price - prev_close) / prev_close) * 100 if prev_close else 0.0

    last_vol = float(volumes[-1]) if volumes else None
    if VOLUME_SPIKE_MULT <= 0:
        vol_ok = True
    elif not volumes or len(volumes) < 20:
        # Some tickers (esp. crypto) may have missing/short volume series.
        vol_ok = True
    else:
        avg_vol = sum(volumes[-20:]) / max(1, len(volumes[-20:]))
        vol_ok = float(volumes[-1]) >= avg_vol * VOLUME_SPIKE_MULT

    status = None
    if pct >= PRICE_UP_PCT and rsi >= RSI_OVERBOUGHT and vol_ok:
        status = "UP"
    elif pct <= PRICE_DOWN_PCT and rsi <= RSI_OVERSOLD and vol_ok:
        status = "DOWN"

    if not status:
        return None

    return {
        "code": c,
        "name": name,
        "price": last_price,
        "pct": pct,
        "rsi": float(rsi),
        "volume": last_vol,
        "status": status,
    }


def format_alert(item):
    arrow = "📈" if item["status"] == "UP" else "📉"
    vol = item.get("volume")
    vol_text = "N/A" if vol is None else f"{int(vol):,}"
    return (
        f"{arrow} 盤中訊號 {item['code']} {item['name']}\n"
        f"價格: {item['price']:.2f} ({item['pct']:.2f}%)\n"
        f"RSI: {item['rsi']:.1f} 量: {vol_text}\n"
        "條件: 價格變動 + RSI + 量能"
    )


def main():
    seed_watchlist_if_empty()
    watchlist = load_watchlist()
    if not watchlist:
        log("⚠️ watchlist 為空，請設定 WATCHLIST_CODES 或更新 stock_database.json")
    else:
        log(f"🚀 盤中監控啟動: {len(watchlist)} 檔")

    last_alert = {}
    last_update_id = 0
    next_scan_time = time.time()
    next_poll_time = time.time()

    while True:
        now = time.time()

        if now >= next_poll_time:
            last_update_id, watchlist = poll_telegram(last_update_id, watchlist)
            next_poll_time = now + TG_POLL_INTERVAL_SEC

        if now >= next_scan_time:
            watchlist = load_watchlist()
            if not watchlist:
                log(
                    "⚠️ watchlist 為空，請設定 WATCHLIST_CODES 或更新 stock_database.json"
                )
                next_scan_time = now + CHECK_INTERVAL_SEC
                time.sleep(1)
                continue

            now_dt = datetime.now()
            open_list = [c for c in watchlist if is_session_open_for_code(c, now_dt)]
            if not open_list:
                log("⏸️ 目前沒有市場開盤（TW/US 盤中或 Crypto 24/7），延後掃描")
                next_scan_time = now + 300
                time.sleep(1)
                continue

            for code in open_list:
                try:
                    item = analyze_symbol(code)
                    if not item:
                        continue
                    last_ts = last_alert.get(code, 0)
                    if now - last_ts < ALERT_COOLDOWN_MIN * 60:
                        continue

                    append_alert(
                        {
                            "kind": "intraday_signal",
                            "code": item["code"],
                            "name": item["name"],
                            "status": item["status"],
                            "price": item["price"],
                            "pct": item["pct"],
                            "rsi": item["rsi"],
                            "volume": item["volume"],
                            "message": format_alert(item),
                        }
                    )

                    notify_all(format_alert(item))
                    last_alert[code] = now
                    log(f"✅ 通知: {code} {item['status']}")
                except Exception:
                    log(f"Error analyzing symbol {code}: {traceback.format_exc()}")
                    continue

            next_scan_time = now + CHECK_INTERVAL_SEC

        time.sleep(1)


if __name__ == "__main__":
    main()
