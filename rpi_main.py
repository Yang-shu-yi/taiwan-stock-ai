import os
import json
import requests
import feedparser
import urllib3
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 禁用不安全請求警告 (針對證交所 API)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

# RSS 來源
CNBC_RSS = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"
TW_RSS_CNYES = "https://news.google.com/rss/search?q=site:news.cnyes.com%20when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
TW_RSS_MONEYDJ = "https://www.moneydj.com/rss/headlines.rss"
TW_RSS_YAHOO = "https://tw.stock.yahoo.com/rss?category=tw-market"

DEBUG_LOG = True


def log(msg):
    if DEBUG_LOG:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ==========================================
# 2) 數據抓取
# ==========================================


def fetch_rss(url, source, max_items=10):
    try:
        feed = feedparser.parse(url)
        out = []
        for entry in feed.entries[:max_items]:
            title = entry.title.strip()
            if title:
                out.append(f"[{source}] {title}")
        return out
    except Exception as e:
        log(f"RSS Error ({source}): {e}")
        return []


def get_yahoo_realtime_index():
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range=2d"
    )
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        json_data = res.json()
        meta = json_data["chart"]["result"][0]["meta"]
        price = float(meta["regularMarketPrice"])
        prev = float(meta.get("previousClose") or meta.get("chartPreviousClose"))

        return {
            "price": f"{price:.0f}",
            "chg": f"{price - prev:.0f}",
            "pct": f"{(price - prev) / prev * 100:.2f}",
            "turnover": None,
        }
    except Exception as e:
        log(f"Yahoo Index Error: {e}")
        return {"price": "N/A", "chg": "N/A", "pct": "N/A", "turnover": None}


def get_market_index_official():
    yahoo_data = get_yahoo_realtime_index()
    official_turnover = None

    try:
        # 證交所 API: 每日收盤行情 (FMTQIK)
        res = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK",
            timeout=10,
            verify=False,
        )
        json_data = res.json()

        if json_data:
            latest = json_data[-1]
            # 證交所的成交金額單位是「元」，轉成「億」
            raw_value = float(latest["TradeValue"].replace(",", ""))
            billions = f"{raw_value / 100000000:.0f}"
            official_turnover = f"{billions}億"
            log(f"🏛️ 證交所 API: 成交金額 {official_turnover}")
    except Exception as e:
        log(f"⚠️ 證交所 API 失敗: {e}")

    final_turnover = official_turnover or yahoo_data["turnover"] or "N/A"
    yahoo_data["turnover"] = final_turnover
    return yahoo_data


# ==========================================
# 3) 通知系統
# ==========================================


def push_line_message(msg):
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


def push_telegram_message(msg):
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


def notify_all(msg):
    # LINE 限制長度
    line_msg = msg[:4500] + "..." if len(msg) > 4500 else msg
    push_line_message(line_msg)
    push_telegram_message(msg)


# ==========================================
# 4) AI 報告生成
# ==========================================


def generate_report_v7(mode, market, us_news, tw_news):
    date_str = datetime.now().strftime("%Y/%m/%d")
    template_type = (
        f"🧭 台股盤前快訊 ({date_str})"
        if mode == "PRE"
        else f"📅 台股盤後法人操盤筆記 ({date_str})"
    )
    index_note = "(昨日收盤)" if mode == "PRE" else ""

    context = f"""
【日期】{date_str}
【模式】{mode}

【市場數據】
指數: {market["price"]} (漲跌 {market["chg"]} / {market["pct"]}%)
★成交值: {market["turnover"]} (資料來源: 證交所/Yahoo)

【新聞素材 (MoneyDJ/鉅亨/Yahoo)】
{"\n".join(tw_news)}

【美股參考】
{"\n".join(us_news)}
""".strip()

    system_prompt = f"""
你是一位專業台股操盤手。請撰寫手機版操盤筆記。

【核心指令】
1. **成交值**：資料已提供為 {market["turnover"]}，請直接填入。
2. **語氣升級**：請模仿「法人研究報告」的語氣，多用「營收動能、庫存調整、本益比評價、資金輪動」等專業詞彙，少用八卦新聞。
3. **盤感邏輯**：美股大跌 -> 台股跳空開低 -> 觀察低接買盤。
4. **Emoji**：使用 Emoji 替代 Markdown 粗體。

【輸出格式】

{template_type}

📈 市場動能
• 指數：{market["price"]} ({market["pct"]}%) ｜ 漲跌：{market["chg"]} {index_note}
• 成交值：{market["turnover"]}
• 盤勢：(一句話描述，例如：⚠️ 量縮觀望，權值股休息，中小型股各自表現)
• 今天的「關鍵」：
  1. (重點1)
  2. (重點2)

🔍 焦點個股 (台股限定)
• 股票 (代號)：(事件) ｜ 盤面影響：(一句話)

⚡ 事件打分 Top3 (台股優先，請選產業/營收相關新聞)
• (分數) 標題
• (分數) 標題
• (分數) 標題

🏁 觀點總結 (100字)
(結論與策略)

⚠️ 免責聲明
• 僅供參考，不構成投資建議
""".strip()

    # 1. Groq
    if GROQ_API_KEY:
        try:
            client = Groq(api_key=GROQ_API_KEY)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context},
                ],
                temperature=0.5,
            )
            return completion.choices[0].message.content
        except Exception as e:
            log(f"Groq Fail: {e}")

    # 2. Gemini Fallback
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": system_prompt + "\n\n" + context}]}]
            }
            res = requests.post(url, json=payload, timeout=30)
            json_data = res.json()
            return json_data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            log(f"Gemini Fail: {e}")

    return "⚠️ AI 無回應"


# ==========================================
# 5) Google Sheets 存檔
# ==========================================


def save_to_sheet(report_text, market, mode):
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
        import re

        summary_match = re.search(r"觀點總結[\s\S]*?\n([\s\S]*?)(\n\n|$)", report_text)
        summary = summary_match.group(1).strip() if summary_match else ""

        date_str = datetime.now().strftime("%Y/%m/%d")
        time_str = datetime.now().strftime("%H:%M:%S")

        row = [
            date_str,
            time_str,
            mode,
            market["price"],
            market["chg"],
            market["turnover"],
            summary,
            report_text,
        ]
        sheet.append_row(row)
        log("✅ Google Sheet 存檔成功")
    except Exception as e:
        log(f"Sheet Error: {e}")


# ==========================================
# 6) 主流程
# ==========================================


def resolve_mode():
    if MODE in ["PRE", "POST"]:
        return MODE
    hhmm = int(datetime.now().strftime("%H%M"))
    return "POST" if hhmm >= 1340 else "PRE"


def main():
    log(f"🚀 啟動 V7.0 流程 ({MODE})...")
    try:
        run_mode = resolve_mode()
        log(f"🧩 執行模式: {run_mode}")

        # 1. 抓新聞
        us_news = fetch_rss(CNBC_RSS, "CNBC", max_items=8)
        tw_news = []
        tw_news.extend(fetch_rss(TW_RSS_MONEYDJ, "MoneyDJ", max_items=8))
        tw_news.extend(fetch_rss(TW_RSS_CNYES, "鉅亨", max_items=8))
        tw_news.extend(fetch_rss(TW_RSS_YAHOO, "Yahoo", max_items=5))

        # 2. 抓指數
        market_data = get_market_index_official()
        log(f"📈 指數數據: {market_data}")

        if not us_news and not tw_news:
            notify_all("⚠️ 系統通知：未抓到新聞，請檢查來源。")
            return

        # 3. 產報告
        report = generate_report_v7(run_mode, market_data, us_news, tw_news)

        # 4. 發送通知
        if report and not report.startswith("⚠️"):
            notify_all(report)
            # 5. 存檔
            save_to_sheet(report, market_data, run_mode)
        else:
            notify_all(report)
            log("⚠️ 報告生成有誤")

    except Exception as e:
        error_msg = f"❌ 系統錯誤: {str(e)}"
        log(error_msg)
        notify_all(error_msg)


if __name__ == "__main__":
    main()
