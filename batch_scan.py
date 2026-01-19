import yfinance as yf
import pandas as pd
import twstock
import json
import time
import os
import requests
import ta
from groq import Groq
from datetime import datetime

# ==========================================
# 🛡️ 設定區 (從 GitHub Secrets 讀取機密)
# ==========================================
SCAN_LIMIT = 500  # 掃描上市前 500 大
LINE_API_URL = "https://api.line.me/v2/bot/message/push"

# 讀取環境變數
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")
WEB_APP_URL = os.environ.get("WEB_APP_URL")

# ==========================================
# 1. 功能函數：發送 LINE (打包版)
# ==========================================
def send_line_push(msg_text):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 未檢測到 LINE 金鑰，跳過發送通知。")
        return

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg_text}]
    }

    try:
        r = requests.post(LINE_API_URL, headers=headers, json=payload)
        if r.status_code == 200:
            print("✅ LINE 推播發送成功")
        else:
            print(f"❌ LINE 推播失敗: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"❌ LINE 連線錯誤: {e}")

# ==========================================
# 2. 功能函數：AI 快篩
# ==========================================
def quick_ai_check(code, name, price, status, rsi):
    if not GROQ_API_KEY:
        return None
    
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"""
    角色：嚴格操盤手。目標：判斷 {name} ({code})。
    數據：現價 {price} / 狀態 {status} / RSI {rsi}
    回覆格式：[評級] 簡評(15字內)
    評級選：強力買進、拉回買進、觀望
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=60
        )
        return completion.choices[0].message.content.strip()
    except: return None

# ==========================================
# 3. 核心邏輯
# ==========================================
def get_target_stocks():
    print("🔍 篩選股票清單...")
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
        latest_price = close.iloc[-1]
        latest_vol = df['Volume'].iloc[-1]
        
        status = "YELLOW"
        if latest_price > ma20 and ma20 > ma60 and rsi > 55:
            status = "RED"
        elif latest_price < ma60 or latest_vol < 50000:
            status = "GREEN"
            
        return {
            "code": code, "name": name, "price": round(latest_price, 2),
            "rsi": round(rsi, 1), "status": status
        }
    except: return None

# ==========================================
# 4. 主程式
# ==========================================
if __name__ == "__main__":
    targets = get_target_stocks()
    database = {}
    report_lines = []
    
    print(f"🚀 開始掃描 {len(targets)} 檔...")
    for i, stock in enumerate(targets):
        try:
            suffix = ".TW" if stock['market'] == "TW" else ".TWO"
            result = analyze_stock(yf.Ticker(f"{stock['code']}{suffix}"), stock['code'], stock['name'])
            
            if result:
                database[stock['code']] = result
                if result['status'] == "RED":
                    print(f"🔥 強勢: {stock['code']}")
                    time.sleep(0.5)
                    ai_comment = quick_ai_check(stock['code'], stock['name'], result['price'], result['status'], result['rsi'])
                    if ai_comment and ("強力買進" in ai_comment or "拉回買進" in ai_comment):
                        report_lines.append(f"🚀 {stock['code']} {stock['name']} ${result['price']}\nRSI:{result['rsi']}｜{ai_comment}")
            
            if i % 50 == 0: print(f"進度 {i}...")
            time.sleep(0.2)
        except: continue

    # 存檔
    with open("stock_database.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)

    # 發送 LINE
    if report_lines:
        link = WEB_APP_URL if WEB_APP_URL else "https://你的網址"
        msg = f"📢 【台股 AI 獵手】\n發現 {len(report_lines)} 檔潛力股 🔥\n" + "─"*10 + "\n" + "\n\n".join(report_lines) + "\n" + "─"*10 + f"\n📊 分析: {link}"
        send_line_push(msg)
            
    print("✅ 完成")