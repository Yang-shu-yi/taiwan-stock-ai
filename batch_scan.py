import yfinance as yf
import pandas as pd
import twstock
import json
import time
import os
import random
from datetime import datetime
import ta

# ==========================================
# 🚀 設定掃描參數
# ==========================================
# 設定要掃描的數量上限 (上市普通股約 980 檔)
# 如果想掃全台股，可以設為 1200
SCAN_LIMIT = 500 

# ==========================================
# 1. 取得目標股票清單 (上市 + 股票)
# ==========================================
def get_target_stocks():
    print("🔍 正在篩選股票清單...")
    targets = []
    
    # 遍歷 twstock 所有代碼
    for code in twstock.codes:
        info = twstock.codes[code]
        
        # 篩選條件：
        # 1. type 必須是 "股票" (排除權證、ETF)
        # 2. market 必須是 "上市" (也可以改成包含 "上櫃")
        if info.type == "股票" and info.market == "上市":
            targets.append({
                "code": code,
                "name": info.name,
                "market": "TW" # 上市後綴
            })
            
    print(f"✅ 篩選出 {len(targets)} 檔上市普通股，將掃描前 {SCAN_LIMIT} 檔。")
    return targets[:SCAN_LIMIT]

# ==========================================
# 2. 核心分析邏輯 (紅綠燈策略)
# ==========================================
def analyze_stock(ticker, code, name):
    try:
        # 抓取 1 年資料 (計算 MA60 需要)
        df = ticker.history(period="1y")
        
        if len(df) < 60:
            return None # 資料不足

        # ---------------------------
        # 指標計算
        # ---------------------------
        close = df['Close']
        
        # 1. 移動平均線 (MA)
        ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
        ma60 = ta.trend.sma_indicator(close, window=60).iloc[-1]
        
        # 2. RSI (相對強弱指標)
        rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        
        # 3. 最新價量
        latest_price = close.iloc[-1]
        latest_vol = df['Volume'].iloc[-1]
        
        # 漲跌幅計算
        prev_close = close.iloc[-2]
        pct_change = ((latest_price - prev_close) / prev_close) * 100

        # ---------------------------
        # 🚦 紅綠燈判斷邏輯
        # ---------------------------
        status = "YELLOW" # 預設觀望
        
        # 🔴 RED (強勢多頭)：站上月線 + 均線多頭排列 + RSI 強勢 (>55)
        if latest_price > ma20 and ma20 > ma60 and rsi > 55:
            status = "RED"
            
        # 🟢 GREEN (避雷/弱勢)：跌破季線 或 流動性太差 (<50張)
        elif latest_price < ma60 or latest_vol < 50000: # 50000股 = 50張
            status = "GREEN"
            
        return {
            "code": code,
            "name": name,
            "price": round(latest_price, 2),
            "pct_change": round(pct_change, 2),
            "volume": int(latest_vol),
            "rsi": round(rsi, 1),
            "status": status,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        
    except Exception as e:
        # print(f"❌ {code} 分析失敗: {e}")
        return None

# ==========================================
# 3. 主程式執行
# ==========================================
if __name__ == "__main__":
    targets = get_target_stocks()
    database = {}
    
    print("🚀 開始批量掃描 (此過程約需 5-10 分鐘)...")
    start_time = time.time()
    
    for i, stock in enumerate(targets):
        code = stock['code']
        suffix = ".TW" if stock['market'] == "TW" else ".TWO"
        symbol = f"{code}{suffix}"
        
        # 呼叫 yfinance
        ticker = yf.Ticker(symbol)
        result = analyze_stock(ticker, code, stock['name'])
        
        if result:
            database[code] = result
            # 即時印出進度 (只印出強勢股 RED，減少雜訊)
            if result['status'] == "RED":
                print(f"🔥 發現強勢股: {code} {stock['name']} RSI={result['rsi']}")
        
        # 進度條
        if i % 50 == 0:
            print(f"進度: {i}/{len(targets)}...")

        # ⚠️ 關鍵：加上延遲，避免被 Yahoo 封鎖 IP
        time.sleep(0.3) 

    # 存檔
    with open("stock_database.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)
        
    end_time = time.time()
    duration = end_time - start_time
    print(f"✅ 掃描完成！共分析 {len(database)} 檔股票。")
    print(f"⏱️ 總耗時: {int(duration // 60)} 分 {int(duration % 60)} 秒")