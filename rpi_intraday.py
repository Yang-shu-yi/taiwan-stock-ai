import os
import sys
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import ta
from dotenv import load_dotenv

from alert_store import append_alert
from candidate_selector import DEFAULT_SNAPSHOT_FILE, get_intraday_focus_codes, load_daily_snapshot
from message_formatter import (
    format_candidate_list,
    format_intraday_alert,
    format_telegram_help,
)
from notifier import notify_report, send_report_message
from universe import get_tw_name, tw_code_to_yahoo_symbol


load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

CHECK_INTERVAL_SEC = int(os.getenv("INTRADAY_CHECK_INTERVAL_SEC", "60"))
PRICE_UP_PCT = float(os.getenv("INTRADAY_PRICE_UP_PCT", "2.0"))
PRICE_DOWN_PCT = float(os.getenv("INTRADAY_PRICE_DOWN_PCT", "-2.0"))
RSI_OVERBOUGHT = float(os.getenv("INTRADAY_RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD = float(os.getenv("INTRADAY_RSI_OVERSOLD", "30"))
VOLUME_SPIKE_MULT = float(os.getenv("INTRADAY_VOLUME_SPIKE_MULT", "2.0"))
ALERT_COOLDOWN_MIN = int(os.getenv("INTRADAY_ALERT_COOLDOWN_MIN", "30"))
TG_POLL_INTERVAL_SEC = int(os.getenv("INTRADAY_TG_POLL_SEC", "10"))
INTRADAY_FOCUS_LIMIT = int(os.getenv("INTRADAY_FOCUS_LIMIT", "12"))
SNAPSHOT_FILE = os.getenv("DAILY_CANDIDATES_FILE", DEFAULT_SNAPSHOT_FILE)
REPORT_TELEGRAM_BOT_TOKEN = os.getenv("REPORT_TELEGRAM_BOT_TOKEN")
REPORT_TELEGRAM_CHAT_ID = os.getenv("REPORT_TELEGRAM_CHAT_ID")


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def is_tw_session_open(now: datetime) -> bool:
    try:
        local_now = now.astimezone(ZoneInfo("Asia/Taipei"))
    except Exception:
        local_now = now
    if local_now.weekday() >= 5:
        return False
    hhmm = local_now.hour * 100 + local_now.minute
    return 900 <= hhmm <= 1330


def yahoo_chart(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1m", "range": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def analyze_symbol(code: str) -> dict | None:
    symbol = tw_code_to_yahoo_symbol(code)
    data = yahoo_chart(symbol)
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None

    quote = result[0].get("indicators", {}).get("quote", [])
    meta = result[0].get("meta", {})
    if not quote:
        return None

    closes = [value for value in quote[0].get("close", []) if value is not None]
    volumes = [value for value in quote[0].get("volume", []) if value is not None]
    if len(closes) < 20:
        return None

    close_series = pd.Series(closes, dtype="float64")
    rsi = ta.momentum.RSIIndicator(close_series, 14).rsi().iloc[-1]
    last_price = float(closes[-1])
    prev_close = float(
        meta.get("previousClose") or meta.get("chartPreviousClose") or last_price
    )
    pct = ((last_price - prev_close) / prev_close) * 100 if prev_close else 0.0

    vol_ratio = None
    if len(volumes) >= 20:
        avg_vol = sum(volumes[-20:]) / max(1, len(volumes[-20:]))
        vol_ratio = float(volumes[-1]) / avg_vol if avg_vol else None

    if vol_ratio is None:
        return None

    status = None
    if pct >= PRICE_UP_PCT and rsi >= RSI_OVERBOUGHT and vol_ratio >= VOLUME_SPIKE_MULT:
        status = "UP"
    elif pct <= PRICE_DOWN_PCT and rsi <= RSI_OVERSOLD and vol_ratio >= VOLUME_SPIKE_MULT:
        status = "DOWN"

    if not status:
        return None

    return {
        "code": code,
        "name": get_tw_name(code),
        "price": last_price,
        "pct": pct,
        "rsi": float(rsi),
        "vol_ratio": float(vol_ratio),
        "status": status,
    }


def handle_command(text: str) -> str | None:
    command = (text or "").strip().lower()
    if command in {"/help", "/start"}:
        return format_telegram_help()
    if command == "/list":
        return format_candidate_list(load_daily_snapshot(SNAPSHOT_FILE), limit=10)
    return None


def poll_telegram(last_update_id: int) -> int:
    if not REPORT_TELEGRAM_BOT_TOKEN or not REPORT_TELEGRAM_CHAT_ID:
        return last_update_id

    url = f"https://api.telegram.org/bot{REPORT_TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 0, "offset": last_update_id + 1}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        updates = response.json().get("result", [])
        for update in updates:
            last_update_id = max(last_update_id, update.get("update_id", last_update_id))
            message = update.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            if str(chat_id) != str(REPORT_TELEGRAM_CHAT_ID):
                continue
            reply = handle_command(message.get("text", ""))
            if reply:
                send_report_message(reply)
    except Exception:
        log(f"Telegram polling failed: {traceback.format_exc()}")
    return last_update_id


def main() -> None:
    last_alert_ts: dict[str, float] = {}
    last_update_id = 0
    next_scan_time = time.time()
    next_poll_time = time.time()

    while True:
        now_ts = time.time()
        if now_ts >= next_poll_time:
            last_update_id = poll_telegram(last_update_id)
            next_poll_time = now_ts + TG_POLL_INTERVAL_SEC

        if now_ts >= next_scan_time:
            if not is_tw_session_open(datetime.now()):
                log("Taiwan market closed, waiting for next scan window")
                next_scan_time = now_ts + 300
                time.sleep(1)
                continue

            focus_codes = get_intraday_focus_codes(INTRADAY_FOCUS_LIMIT, SNAPSHOT_FILE)
            log(f"Intraday focus list: {', '.join(focus_codes)}")

            for code in focus_codes:
                try:
                    item = analyze_symbol(code)
                    if not item:
                        continue
                    last_sent = last_alert_ts.get(code, 0.0)
                    if now_ts - last_sent < ALERT_COOLDOWN_MIN * 60:
                        continue

                    message = format_intraday_alert(item)
                    append_alert(
                        {
                            "kind": "intraday_signal",
                            "code": item["code"],
                            "name": item["name"],
                            "status": item["status"],
                            "price": item["price"],
                            "pct": item["pct"],
                            "rsi": item["rsi"],
                            "vol_ratio": item["vol_ratio"],
                            "message": message,
                        }
                    )
                    notify_report(message)
                    last_alert_ts[code] = now_ts
                except Exception:
                    log(f"Error while analyzing {code}: {traceback.format_exc()}")

            next_scan_time = now_ts + CHECK_INTERVAL_SEC

        time.sleep(1)


if __name__ == "__main__":
    main()
