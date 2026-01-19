import yfinance as yf
import pandas as pd
import twstock
import json
import time
import os
import requests
import ta
from groq import Groq
from datetime import datetime, timedelta, timezone

# ==========================================
# 🛡️ 設定區
# ==========================================
SCAN_LIMIT = 500
LINE_API_URL = "https://api.line.me/v2/bot/message/push"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")
WEB_APP_URL = os.environ.get("WEB_APP_URL")

# 設定台灣時區 (UTC+8)
TW_TZ = timezone(timedelta(hours=8))

# ==========================================
# 1. 功能函數
# ==========================================
def get_tw_time():
    """取得台灣目前的日期與時間字串"""
    now = datetime.now(TW_TZ)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M")

def send_line_push(msg_text):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 未設定 LINE Token，跳過通知")
        return
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg_text}]}
    try:
        r = requests.post(LINE_API_URL, headers=headers, json=payload)
        print(f"📡 LINE 回應代碼: {r.status_code}") # 除錯用
    except Exception as e:
        print(f"❌ Line Error: {e}")

def quick_ai_check(code, name, price, status, rsi):
    if not GROQ_API_KEY: return None
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"角色：操盤手。評估 {name}({code}) 現價{price}/RSI{rsi}/狀態{status}。請回覆格式：[評級] 簡評(15字內)。評級選：強力買進、拉回買進、觀望"
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=60
        )
        return completion.choices[0].message.content.strip()
    except: return None

# ==========================================
# 2. 核心邏輯
# ==========================================
def get_target_stocks():
    print("🔍 建立清單中...")
    targets = []
    for code in twstock.codes:
        info = twstock.codes[code]
        if info.type == "股票" and info.market == "上市":
            targets.append({"code": code, "name": info.name, "market": "TW"})
    return targets[:SCAN_LIMIT]

def analyze_stock(ticker, code, name):
    try:
        df = ticker.history(period="1y")
        if len(df) < 60: return None
        close = df['Close']
        
        # 技術指標
        ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
        ma60 = ta.trend.sma_indicator(close, window=60).iloc[-1]
        rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        latest = close.iloc[-1]
        vol = df['Volume'].iloc[-1]

        # 漲跌幅計算
        prev_close = close.iloc[-2]
        pct_change = (latest - prev_close) / prev_close * 100
        
        status = "YELLOW"
        # 這裡可以調整寬鬆度，例如 RSI > 50 即可，方便測試
        if latest > ma20 and ma20 > ma60 and rsi > 55: status = "RED"
        elif latest < ma60 or vol < 50000: status = "GREEN"
            
        date_str, time_str = get_tw_time()
        
        return {
            "code": code, 
            "name": name, 
            "price": round(latest, 2),
            "pct_change": round(pct_change, 2),
            "rsi": round(rsi, 1), 
            "status": status,
            "update_date": date_str,  # 給 LINE 用
            "update_time": time_str   # 給網頁顯示用
        }
    except: return None

# ==========================================
# 3. 主程式
# ==========================================
if __name__ == "__main__":
    targets = get_target_stocks()
    database = {}
    report = []
    
    date_str, time_str = get_tw_time()
    print(f"🚀 開始掃描 {len(targets)} 檔股票 (台灣時間: {time_str})...")
    
    for i, stock in enumerate(targets):
        try:
            suffix = ".TW" if stock['market'] == "TW" else ".TWO"
            res = analyze_stock(yf.Ticker(f"{stock['code']}{suffix}"), stock['code'], stock['name'])
            
            if res:
                database[stock['code']] = res
                if res['status'] == "RED":
                    print(f"🔥 強勢: {stock['code']}")
                    time.sleep(0.5)
                    ai_msg = quick_ai_check(stock['code'], stock['name'], res['price'], res['status'], res['rsi'])
                    # 只要 AI 有回應就加入，方便測試通知 (如果不想要太寬鬆，可以把下一行註解拿掉)
                    if ai_msg: # and ("買進" in ai_msg):
                        report.append(f"🚀 {stock['code']} {stock['name']} ${res['price']} ({res['pct_change']}%)\nAI: {ai_msg}")
            
            if i % 50 == 0: print(f"進度 {i}...")
            time.sleep(0.2)
        except: continue

    # 存檔
    with open("stock_database.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)

    # 📢 LINE 通知邏輯 (修改重點)
    # 不管有沒有找到股票，都發送通知，確保機器人還活著
    if report:
        msg = f"📢 【AI 獵手日報】{date_str}\n發現 {len(report)} 檔潛力股 🔥\n" + "─"*10 + "\n" + "\n\n".join(report) + "\n" + "─"*10 + f"\n📊 戰情室: {WEB_APP_URL}"
    else:
        msg = f"💤 【AI 獵手日報】{date_str}\n今日掃描 500 檔，無符合「強勢多頭」條件之個股。\n(機器人運作正常 ✅)"

    print("📨 正在發送 LINE 通知...")
    send_line_push(msg)
            
    print("✅ 完成")