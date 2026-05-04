import json
import os
import sys
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
from config_check import env_flag, validate_runtime_config
from data_layer import get_data_status, record_news_status, reset_data_status
from market_data import get_all_market_data
from message_formatter import format_market_report
from news_scraper import fetch_all_news
from notifier import notify_report, send_report_error
from signal_tracker import (
    append_signal_history,
    evaluate_signal_performance,
    summarize_performance,
)


load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

MODE = os.getenv("MODE", "AUTO").strip().upper()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
SNAPSHOT_FILE = os.getenv("DAILY_CANDIDATES_FILE", DEFAULT_SNAPSHOT_FILE)
DRY_RUN = env_flag("DRY_RUN", False)


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
        reset_data_status()
        for issue in validate_runtime_config():
            log(f"[{issue.level}] {issue.message}")

        mode = resolve_mode()
        log(f"Running daily pipeline in {mode} mode")

        tw_news, us_news = fetch_all_news(
            max_per_source=6,
            fetch_content=False,
        )
        record_news_status(len(tw_news), len(us_news))
        market = get_all_market_data(mode=mode)

        evaluate_signal_performance()
        snapshot = build_daily_snapshot(
            mode,
            market,
            tw_news,
            us_news,
            data_status=get_data_status(),
        )
        snapshot["performance_summary"] = summarize_performance()
        save_daily_snapshot(snapshot, SNAPSHOT_FILE)
        appended = append_signal_history(snapshot)
        log(f"Signal history appended: {appended}")

        report_message = format_market_report(snapshot)
        if DRY_RUN:
            log("DRY_RUN=true, skip Telegram/LINE notification")
        else:
            notify_report(report_message)
        save_summary_to_sheet(snapshot)

        log(f"Snapshot saved to {SNAPSHOT_FILE}")
        log("Daily pipeline completed")
    except Exception as exc:
        error_message = f"[系統錯誤]\n每日流程失敗: {exc}"
        log(error_message)
        if not DRY_RUN:
            send_report_error(error_message)


if __name__ == "__main__":
    main()
