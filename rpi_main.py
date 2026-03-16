import json
import os
from datetime import datetime

from dotenv import load_dotenv

try:
    import gspread
except Exception:
    gspread = None

from candidate_selector import (
    DEFAULT_SNAPSHOT_FILE,
    build_daily_snapshot,
    save_daily_snapshot,
)
from market_data import get_all_market_data
from message_formatter import format_market_report
from news_scraper import fetch_all_news
from notifier import notify_report, send_report_error


load_dotenv()

MODE = os.getenv("MODE", "AUTO").strip().upper()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
SNAPSHOT_FILE = os.getenv("DAILY_CANDIDATES_FILE", DEFAULT_SNAPSHOT_FILE)


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def resolve_mode() -> str:
    if MODE in {"PRE", "POST"}:
        return MODE
    hhmm = int(datetime.now().strftime("%H%M"))
    return "POST" if hhmm >= 1340 else "PRE"


def save_summary_to_sheet(snapshot: dict) -> None:
    if not gspread or not SPREADSHEET_ID or not GOOGLE_SERVICE_ACCOUNT_FILE:
        return
    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
        return
    try:
        client = gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        tw = snapshot.get("market", {}).get("tw_index", {})
        top_names = "、".join(
            f"{item['code']} {item['name']}"
            for item in snapshot.get("tw_candidates", [])[:5]
        )
        row = [
            datetime.now().strftime("%Y/%m/%d"),
            datetime.now().strftime("%H:%M:%S"),
            snapshot.get("mode", ""),
            snapshot.get("updated_at", ""),
            tw.get("price", "N/A"),
            tw.get("pct", "N/A"),
            top_names,
            json.dumps(snapshot.get("tw_candidates", []), ensure_ascii=False),
        ]
        sheet.append_row(row)
    except Exception as exc:
        log(f"Google Sheets sync failed: {exc}")


def main() -> None:
    try:
        mode = resolve_mode()
        log(f"Running daily pipeline in {mode} mode")

        tw_news, us_news = fetch_all_news(
            max_per_source=6,
            fetch_content=False,
        )
        market = get_all_market_data(mode=mode)
        snapshot = build_daily_snapshot(mode, market, tw_news, us_news)
        save_daily_snapshot(snapshot, SNAPSHOT_FILE)

        report_message = format_market_report(snapshot)
        notify_report(report_message)
        save_summary_to_sheet(snapshot)

        log(f"Snapshot saved to {SNAPSHOT_FILE}")
        log("Daily pipeline completed")
    except Exception as exc:
        error_message = f"[系統錯誤]\n每日流程失敗: {exc}"
        log(error_message)
        send_report_error(error_message)


if __name__ == "__main__":
    main()
