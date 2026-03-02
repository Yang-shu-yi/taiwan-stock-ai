"""
rpi_main.py — 每日報告主流程 (Orchestrator)

整合 news_scraper / market_data / report_generator 三大模組，
負責：排程判斷 → 資料收集 → 報告生成 → 通知推送 → Google Sheets 存檔。
"""

import os
import re
from datetime import datetime

import requests
from dotenv import load_dotenv

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except Exception:
    gspread = None
    ServiceAccountCredentials = None  # type: ignore[assignment,misc]

from news_scraper import fetch_all_news
from market_data import get_all_market_data
from report_generator import generate_report

# 加載環境變數
load_dotenv()

# ==========================================
# 1) 設定區
# ==========================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TARGET_ID = os.getenv("LINE_TARGET_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
MODE = os.getenv("MODE", "AUTO")

# watchlist 來源：環境變數或 watchlist.json
WATCHLIST_CODES = os.getenv("WATCHLIST_CODES", "")

DEBUG_LOG = True


def log(msg: str) -> None:
    if DEBUG_LOG:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ==========================================
# 2) 通知系統
# ==========================================


def push_line_message(msg: str) -> None:
    if not LINE_CHANNEL_TOKEN or not LINE_TARGET_ID:
        log("⚠️ LINE 設定缺失")
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"to": LINE_TARGET_ID, "messages": [{"type": "text", "text": msg}]}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            log("✅ LINE 發送成功")
        else:
            log(f"❌ LINE 發送失敗: {res.text}")
    except Exception as e:
        log(f"❌ LINE 錯誤: {e}")


def push_telegram_message(msg: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️ Telegram 設定缺失")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log("✅ Telegram 發送成功")
        else:
            log(f"❌ Telegram 發送失敗: {res.text}")
    except Exception as e:
        log(f"❌ Telegram 錯誤: {e}")


def notify_all(msg: str) -> None:
    # LINE 限制長度
    line_msg = msg[:4500] + "..." if len(msg) > 4500 else msg
    push_line_message(line_msg)
    push_telegram_message(msg)


# ==========================================
# 3) Watchlist 讀取
# ==========================================


def load_watchlist() -> list[str]:
    """從各來源讀取 watchlist，回傳股票代碼列表"""
    # 1. 環境變數
    if WATCHLIST_CODES.strip():
        codes = [c.strip() for c in WATCHLIST_CODES.split(",") if c.strip()]
        if codes:
            return codes

    # 2. watchlist.json
    import json

    if os.path.exists("watchlist.json"):
        try:
            with open("watchlist.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [str(c).strip() for c in data if str(c).strip()]
        except Exception:
            pass

    # 3. stock_database.json 中的 RED 標記
    if os.path.exists("stock_database.json"):
        try:
            with open("stock_database.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            return [k for k, v in data.items() if v.get("status") == "RED"]
        except Exception:
            pass

    return []


# ==========================================
# 4) Google Sheets 存檔
# ==========================================


def save_to_sheet(report_text: str, market: dict, mode: str) -> None:
    if not gspread or not ServiceAccountCredentials:
        log("⚠️ gspread 未安裝")
        return
    if not SPREADSHEET_ID or not GOOGLE_SERVICE_ACCOUNT_FILE:
        log("⚠️ Google Sheets 設定缺失")
        return
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            GOOGLE_SERVICE_ACCOUNT_FILE, scope
        )
        client = gspread.authorize(creds)

        sheet = client.open_by_key(SPREADSHEET_ID).sheet1

        # 取得摘要
        summary_match = re.search(
            r"(操作策略|明日策略|觀點總結)[\s\S]*?\n([\s\S]*?)(\n\n|$)",
            report_text,
        )
        summary = summary_match.group(2).strip() if summary_match else ""

        tw = market.get("tw_index", {})

        date_str = datetime.now().strftime("%Y/%m/%d")
        time_str = datetime.now().strftime("%H:%M:%S")

        row = [
            date_str,
            time_str,
            mode,
            tw.get("price", "N/A"),
            tw.get("chg", "N/A"),
            tw.get("turnover", "N/A"),
            summary,
            report_text,
        ]
        sheet.append_row(row)
        log("✅ Google Sheet 存檔成功")
    except Exception as e:
        log(f"Sheet Error: {e}")


# ==========================================
# 5) 主流程
# ==========================================


def resolve_mode() -> str:
    if MODE in ["PRE", "POST"]:
        return MODE
    hhmm = int(datetime.now().strftime("%H%M"))
    return "POST" if hhmm >= 1340 else "PRE"


def main() -> None:
    log("🚀 啟動報告流程 (v8.0 模組化架構)...")
    try:
        run_mode = resolve_mode()
        log(f"🧩 執行模式: {run_mode}")

        # 1. 抓新聞 (多來源 + 內文摘要 + 去重)
        log("📰 Step: 抓取新聞...")
        tw_news, us_news = fetch_all_news(
            max_per_source=8,
            fetch_content=True,
            content_max_chars=500,
        )
        log(f"📰 新聞完成: 台股 {len(tw_news)} 則 / 美股 {len(us_news)} 則")

        if not tw_news and not us_news:
            notify_all("⚠️ 系統通知：未抓到新聞，請檢查來源。")
            return

        # 2. 抓市場數據 (台股/美股/匯率/法人)
        log("📊 Step: 抓取市場數據...")
        market = get_all_market_data(mode=run_mode)

        # 3. 讀取 watchlist
        watchlist = load_watchlist()
        log(f"📋 Watchlist: {len(watchlist)} 檔 ({', '.join(watchlist[:10])}...)")

        # 4. 生成報告 (兩步 AI pipeline)
        log("🧠 Step: AI 報告生成...")
        report = generate_report(
            mode=run_mode,
            tw_news=tw_news,
            us_news=us_news,
            market=market,
            watchlist=watchlist,
            groq_key=GROQ_API_KEY,
            gemini_key=GEMINI_API_KEY,
        )

        # 5. 發送通知 + 存檔
        if report and not report.startswith("⚠️"):
            notify_all(report)
            save_to_sheet(report, market, run_mode)
            log("✅ 報告流程完成")
        else:
            notify_all(report)
            log("⚠️ 報告生成有誤")

    except Exception as e:
        error_msg = f"❌ 系統錯誤: {str(e)}"
        log(error_msg)
        notify_all(error_msg)


if __name__ == "__main__":
    main()
