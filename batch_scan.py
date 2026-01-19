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

TW_TZ = timezone(timedelta(hours=8))

# ==========================================
# 1. 功能函數
# ==========================================
def get_tw_time():
    now = datetime.now(TW_TZ)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M")

def send_line_push(msg_text):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        return
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg_text}]}
    try:
        requests.post(LINE_API_URL, headers=headers, json=payload)
    except Exception as e:
        print(f"❌ Line Error: {e}")

def quick_ai_check(code, name, price, status, rsi):
    if not GROQ_API_KEY: return None
    client = Groq(api_key=GROQ_API_KEY)
    # Prompt 簡化，節省 tokens
    prompt = f"評估 {name}({code}) 現價{price}/RSI{rsi}。簡單給評級(買進/觀望)與理由(15字內)。"
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
        
        ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
        ma60 = ta.trend.sma_indicator(close, window=60).iloc[-1]
        rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        latest = close.iloc[-1]
        
        # 漲跌幅
        prev_close = close.iloc[-2]
        pct_change = (latest - prev_close) / prev_close * 100
        
        status = "YELLOW"
        
        # 🟢 正式版嚴格策略：
        # 1. 股價 > 月線 (MA20)
        # 2. 月線 > 季線 (MA60) -> 多頭排列
        # 3. RSI > 55 -> 動能強勢
        if latest > ma20 and ma20 > ma60 and rsi > 60:
            status = "RED"
            
        # 🟢 弱勢/避雷標準：
        # 跌破季線 (MA60) 或 成交量太低 (< 500張)
        elif latest < ma60 or vol < 500000: 
            status = "GREEN"
            
        date_str, time_str = get_tw_time()
        
        return {
            "code": code, "name": name, "price": round(latest, 2),
            "pct_change": round(pct_change, 2),
            "rsi": round(rsi, 1), "status": status,
            "update_date": date_str, "update_time": time_str
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
    print(f"🚀 開始掃描 (時間: {time_str})...")
    
    count = 0
    for i, stock in enumerate(targets):
        try:
            suffix = ".TW" if stock['market'] == "TW" else ".TWO"
            res = analyze_stock(yf.Ticker(f"{stock['code']}{suffix}"), stock['code'], stock['name'])
            
            if res:
                database[stock['code']] = res
                # 只取前 3 檔強勢股來測試 AI (節省時間與額度)
                if res['status'] == "RED" and count < 3:
                    print(f"🔥 發現強勢: {stock['code']}")
                    ai_msg = quick_ai_check(stock['code'], stock['name'], res['price'], res['status'], res['rsi'])
                    if ai_msg:
                        report.append(f"🚀 {stock['code']} {stock['name']} ${res['price']} ({res['pct_change']}%)\nAI: {ai_msg}")
                        count += 1
            
            if i % 50 == 0: print(f"進度 {i}...")
            time.sleep(0.1) # 加快一點速度
        except: continue

    with open("stock_database.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)

    # 📢 最終通知
    if report:
        msg = f"📢 【AI 獵手日報】{date_str}\n(測試版: RSI>50即入選)\n" + "─"*10 + "\n" + "\n\n".join(report) + "\n" + "─"*10 + f"\n📊 戰情室: {WEB_APP_URL}"
    else:
        msg = f"💤 【AI 獵手日報】{date_str}\n今日無符合條件個股。\n(系統運作正常 ✅)"

    print("📨 發送通知中...")
    send_line_push(msg)
    print("✅ 完成")