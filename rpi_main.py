import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

try:
    import gspread
except Exception:
    gspread = None

from candidate_selector import (
    DEFAULT_SNAPSHOT_FILE,
    build_daily_snapshot,
    load_daily_snapshot,
    save_daily_snapshot,
)
from config_check import env_flag, validate_runtime_config
from data_layer import get_data_status, record_news_status, reset_data_status
from dashboard_publisher import publish_dashboard_snapshot
from market_data import get_all_market_data
from message_formatter import format_market_report
from news_scraper import fetch_all_news
from notifier import notify_report, safe_exception_text, send_report_error
from portfolio_risk import build_portfolio_risk, build_research_governance
from signal_tracker import (
    EARLY_WATCH_HISTORY_FILE,
    EARLY_WATCH_PERFORMANCE_FILE,
    append_early_watch_history,
    append_signal_history,
    evaluate_signal_performance,
    summarize_performance,
)
from snapshot_fallback import apply_candidate_fallback, has_valid_candidate_snapshot
from strategy_contract import EARLY_WATCH_CHANNEL, LIVE_ENVIRONMENT, resolve_run_context
from strategy_model import build_research_model_report
from strategy_optimizer import build_strategy_optimization

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

MODE = os.getenv("MODE", "AUTO").strip().upper()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
SNAPSHOT_FILE = os.getenv("DAILY_CANDIDATES_FILE", DEFAULT_SNAPSHOT_FILE)
RESEARCH_SNAPSHOT_FILE = os.getenv("RESEARCH_SNAPSHOT_FILE", "runtime/research_daily_candidates.json")
LAST_VALID_SNAPSHOT_FILE = os.getenv(
    "LAST_VALID_SNAPSHOT_FILE",
    "runtime/last_valid_daily_candidates.json",
)
DRY_RUN = env_flag("DRY_RUN", False)
SHEETS_ENABLED = env_flag("ENABLE_GOOGLE_SHEETS", bool(SPREADSHEET_ID))


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def resolve_mode() -> str:
    if MODE in {"PRE", "POST"}:
        return MODE
    hhmm = int(datetime.now().strftime("%H%M"))
    return "POST" if hhmm >= 1340 else "PRE"


def save_summary_to_sheet(snapshot: dict) -> None:
    if not SHEETS_ENABLED:
        log("Google Sheets disabled")
        return
    if not gspread or not SPREADSHEET_ID or not GOOGLE_SERVICE_ACCOUNT_FILE:
        log("Google Sheets skipped: missing gspread/SPREADSHEET_ID/GOOGLE_SERVICE_ACCOUNT_FILE")
        return
    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
        log(f"Google Sheets skipped: {GOOGLE_SERVICE_ACCOUNT_FILE} not found")
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
    is_live_run = False
    try:
        reset_data_status()
        for issue in validate_runtime_config():
            log(f"[{issue.level}] {issue.message}")

        mode = resolve_mode()
        run_context = resolve_run_context(dry_run=DRY_RUN)
        is_live_run = (
            run_context["execution_environment"] == LIVE_ENVIRONMENT
            and run_context["run_type"] not in {"dry_run", "research", "backfill"}
        )
        log(
            f"Running daily pipeline in {mode} mode "
            f"({run_context['execution_environment']}/{run_context['run_type']}/"
            f"{run_context['strategy_version']})"
        )

        tw_news, us_news = fetch_all_news(
            max_per_source=6,
            fetch_content=False,
        )
        record_news_status(len(tw_news), len(us_news))
        market = get_all_market_data(mode=mode)

        previous_snapshot = load_daily_snapshot(SNAPSHOT_FILE) if is_live_run else {}
        last_valid_snapshot = (
            load_daily_snapshot(LAST_VALID_SNAPSHOT_FILE) if is_live_run else {}
        )
        if not has_valid_candidate_snapshot(last_valid_snapshot):
            last_valid_snapshot = previous_snapshot
        snapshot = build_daily_snapshot(
            mode,
            market,
            tw_news,
            us_news,
            run_context=run_context,
        )
        if is_live_run:
            evaluated = evaluate_signal_performance(
                execution_environment=run_context["execution_environment"]
            )
            log(f"Signal performance appended: {evaluated}")
            early_evaluated = evaluate_signal_performance(
                EARLY_WATCH_HISTORY_FILE,
                EARLY_WATCH_PERFORMANCE_FILE,
                execution_environment=run_context["execution_environment"],
            )
            log(f"Early-watch performance appended: {early_evaluated}")
        else:
            log("Research execution: skip formal performance evaluation")
        snapshot["data_status"] = get_data_status()
        snapshot["performance_summary"] = summarize_performance()
        snapshot["shadow_performance_summary"] = summarize_performance(
            candidate_channel="shadow"
        )
        snapshot["early_watch_performance_summary"] = summarize_performance(
            performance_path=EARLY_WATCH_PERFORMANCE_FILE,
            candidate_channel=EARLY_WATCH_CHANNEL,
        )
        snapshot["strategy_optimization"] = build_strategy_optimization()
        snapshot["model_research"] = build_research_model_report(
            current_candidates=snapshot.get("tw_candidates", [])
        )
        snapshot["portfolio_risk"] = build_portfolio_risk(
            snapshot,
            previous_snapshot=previous_snapshot,
            performance_summary=snapshot["performance_summary"],
        )
        snapshot["research_governance"] = build_research_governance(
            snapshot["model_research"],
            snapshot["performance_summary"],
        )
        snapshot = apply_candidate_fallback(snapshot, last_valid_snapshot)

        report_message = format_market_report(snapshot)
        if is_live_run:
            if snapshot.get("candidate_provenance", {}).get("mode") == "current":
                save_daily_snapshot(snapshot, LAST_VALID_SNAPSHOT_FILE)
                log(f"Last valid candidate snapshot saved to {LAST_VALID_SNAPSHOT_FILE}")
            save_daily_snapshot(snapshot, SNAPSHOT_FILE)
            appended = append_signal_history(snapshot)
            log(f"Signal history appended: {appended}")
            early_appended = append_early_watch_history(snapshot)
            log(f"Early-watch history appended: {early_appended}")
            try:
                publication = publish_dashboard_snapshot(snapshot)
                if publication.get("ok"):
                    log(f"Dashboard snapshot published: {publication.get('url')}")
                else:
                    log(f"Dashboard publish skipped: {publication.get('status', 'disabled')}")
            except Exception as exc:
                log(f"Dashboard publish failed (report delivery continues): {safe_exception_text(exc)}")
            notify_report(report_message)
            save_summary_to_sheet(snapshot)
            log(f"Live snapshot saved to {SNAPSHOT_FILE}")
        else:
            save_daily_snapshot(snapshot, RESEARCH_SNAPSHOT_FILE)
            log(
                f"Research snapshot saved to {RESEARCH_SNAPSHOT_FILE}; "
                "formal snapshot/history/performance/Sheets/notifications unchanged"
            )

        log("Daily pipeline completed")
    except Exception as exc:
        error_message = f"[系統錯誤]\n每日流程失敗: {exc}"
        log(error_message)
        if is_live_run:
            send_report_error(error_message)


if __name__ == "__main__":
    main()
