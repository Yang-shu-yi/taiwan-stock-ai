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
SCAN_LIMIT = 500  # 掃描上市前 500 大，兼顧速度與機會
LINE_API_URL = "https://api.line.me/v2/bot/message/push"

# 讀取環境變數 (如果本地執行沒有設環境變數，會回傳 None)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")
WEB_APP_URL = os.environ.get("WEB_APP_URL") 

# ==========================================
# 1. 功能函數：發送 LINE Messaging API (推播)
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
        "messages": [
            {
                "type": "text",
                "text": msg_text
            }
        ]
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
# 2. 功能函數：AI 簡易快篩
# ==========================================
def quick_ai_check(code, name, price, status, rsi):
    if not GROQ_API_KEY:
        return None
    
    client = Groq(api_key=GROQ_API_KEY)
    
    # Prompt 優化：極簡短評，節省 Token 與版面
    prompt = f"""
    角色：嚴格的操盤手。
    目標：判斷 {name} ({code}) 是否值得買進。
    數據：現價 {price} / 狀態 {status} / RSI {rsi}
    
    請回覆格式：
    [評級] 簡短理由 (15字內)
    
    評級只選：強力買進、拉回買進、觀望
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=60
        )
        return completion.choices[0].message.content.strip()
    except:
        return None

# ==========================================
# 3. 取得目標股票清單 (上市普通股)
# ==========================================
def get_target_stocks():
    print("🔍 正在篩選股票清單...")
    targets = []
    for code in twstock.codes:
        info = twstock.codes[code]
        if info.type == "股票" and info.market == "上市":
            targets.append({"code": code, "name": info.name, "market": "TW"})
    
    # 取前 N 檔進行掃描
    return targets[:SCAN_LIMIT]

# ==========================================
# 4. 核心分析邏輯 (技術指標 + 紅綠燈)
# ==========================================
def analyze_stock(ticker, code, name):
    try:
        df = ticker.history(period="1y")
        if len(df) < 60: return None # 資料不足跳過

        close = df['Close']
        # 技術指標計算
        ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
        ma60 = ta.trend.sma_indicator(close, window=60).iloc[-1]
        rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        
        latest_price = close.iloc[-1]
        latest_vol = df['Volume'].iloc[-1]
        
        status = "YELLOW"
        
        # 🔴 RED 強勢條件：站上月線 + 多頭排列 + RSI 強勢區 (>55)
        if latest_price > ma20 and ma20 > ma60 and rsi > 55:
            status = "RED"
            
        # 🟢 GREEN 弱勢/避雷條件：跌破季線 或 成交量太低 (<50張)
        elif latest_price < ma60 or latest_vol < 50000:
            status = "GREEN"
            
        return {
            "code": code, 
            "name": name, 
            "price": round(latest_price, 2),
            "volume": int(latest_vol), 
            "rsi": round(rsi, 1), 
            "status": status,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    except: 
        return None

# ==========================================
# 5. 主程式執行
# ==========================================
if __name__ == "__main__":
    targets = get_target_stocks()
    database = {}
    report_lines = [] # 用來存放要發送的 LINE 訊息
    
    print(f"🚀 開始掃描 {len(targets)} 檔股票...")
    
    for i, stock in enumerate(targets):
        code = stock['code']
        # 判斷上市櫃後綴
        suffix = ".TW" if stock['market'] == "TW" else ".TWO"
        
        try:
            ticker = yf.Ticker(f"{code}{suffix}")
            result = analyze_stock(ticker, code, stock['name'])
            
            if result:
                database[code] = result
                
                # 🔥 只針對 RED 強勢股進行 AI 複查
                if result['status'] == "RED":
                    print(f"🔥 強勢股初篩: {code} {stock['name']} (RSI: {result['rsi']})")
                    
                    # 呼叫 AI (加上延遲避免被擋)
                    time.sleep(0.5) 
                    ai_comment = quick_ai_check(code, stock['name'], result['price'], result['status'], result['rsi'])
                    
                    # 只有 AI 說「買進」的才放入通知清單
                    if ai_comment and ("強力買進" in ai_comment or "拉回買進" in ai_comment):
                        print(f"✅ AI 認證通過: {ai_comment}")
                        line_msg = f"🚀 {code} {stock['name']} ${result['price']}\nRSI:{result['rsi']}｜{ai_comment}"
                        report_lines.append(line_msg)
            
            # 進度顯示
            if i % 50 == 0: 
                print(f"進度: {i}/{len(targets)}...")
            
            # 避免 yfinance 封鎖 IP
            time.sleep(0.2) 
            
        except Exception as e:
            print(f"Error processing {code}: {e}")
            continue

    # 💾 存檔 JSON (供 Streamlit 讀取)
    with open("stock_database.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)
        
    # 📨 統一發送 LINE 推播 (打包成一則)
    if report_lines:
        current_date = datetime.now().strftime("%m/%d")
        
        # 處理戰情室網址 (如果有設定變數就用，沒有就給提示)
        link_text = WEB_APP_URL if WEB_APP_URL else "https://你的-streamlit-app網址"
        
        header = f"📢 【台股 AI 獵手】{current_date}\n發現 {len(report_lines)} 檔潛力股 🔥\n" + "─" * 12 + "\n"
        body = "\n\n".join(report_lines)
        footer = "\n" + "─" * 12 + f"\n📊 詳細分析:\n{link_text}"
        
        full_message = header + body + footer
        
        print("📨 正在發送 LINE 推播...")
        send_line_push(full_message)
            
    print("✅ 掃描任務完成")