import yfinance as yf
import pandas as pd
import twstock
import json
import time
import os
from datetime import datetime

# ==========================================
# 1. 設定掃描清單：台灣前 100 大權值股 (含上市/上櫃熱門)
# ==========================================

# 這份清單包含了：
# 1. 台灣 50 (0050) 成分股 - 台股最大 50 家
# 2. 中型 100 (0051) 前段班 - 成長性高的中型股
# 3. 熱門 AI / 航運 / 金融 / 高股息指標股
TOP_100_CODES = [
    # --- 半導體與 AI 權值 ---
    '2330', '2454', '2303', '2308', '2379', '3711', '3443', '3661', '3034', '2344', # 台積電, 聯發科, 聯電...
    '3035', '3529', '3231', '2382', '2356', '2357', '2353', '2376', '2377', '6669', # 緯創, 廣達, 技嘉, 華碩...
    '3017', '2408', '3008', '8069', '8299', '6515', '5269', '5274', # 奇鋐, 大立光...

    # --- 金融股 (存股族最愛) ---
    '2881', '2882', '2891', '2886', '2884', '2885', '2892', '2880', '2890', '2883',
    '2887', '5880', '5876', '5871', '2801', '2812', '2834', '2845', '2867', '2809',

    # --- 航運三雄與航空 ---
    '2603', '2609', '2615', '2618', '2610', '2637', # 長榮, 陽明, 萬海, 長榮航...

    # --- 傳產龍頭 (塑化/水泥/鋼鐵/食品) ---
    '1101', '1102', '1301', '1303', '1326', '6505', '2002', '1216', '1402', '9910', # 台泥, 台塑, 中鋼, 統一...
    '2105', '1504', '1590', '1605', # 正新, 東元, 亞德客, 華新

    # --- 電信與百貨 ---
    '2412', '3045', '4904', '2912', # 中華電, 台灣大, 遠傳, 統一超

    # --- 熱門高價與上櫃潛力 (包含 3629) ---
    '5903', '5904', '6415', '6409', '4966', '3629', '6176', '6274', '8046', '3293', # 鈊象, 瑞昱...
    '6446', '6472', '6239', '6269', '8454', '9914', '9921', '9941', '9945', '2317'  # 鴻海(補上)
]

# 設定目標為這份清單
TARGET_CODES = TOP_100_CODES

print(f"✅ 已載入「台灣市值前 100 大」清單，共 {len(TARGET_CODES)} 檔，準備掃描...")

# ==========================================
# 2. 核心分析邏輯 (智慧判斷上市/上櫃)
# ==========================================

def get_yahoo_symbol(code):
    """
    自動判斷是上市 (.TW) 還是上櫃 (.TWO)
    """
    try:
        if code not in twstock.codes:
            # 如果 twstock 找不到 (例如剛上市)，預設嘗試 .TW
            return f"{code}.TW"
            
        info = twstock.codes[code]
        if info.market == "上市":
            return f"{code}.TW"
        elif info.market == "上櫃":
            return f"{code}.TWO"
        else:
            return f"{code}.TW"
    except:
        return f"{code}.TW"

def analyze_stock_logic(code):
    try:
        # 1. 取得正確代號
        symbol = get_yahoo_symbol(code)
        
        # 2. 取得名稱 (防呆: 若 twstock 沒資料就用代號)
        try:
            stock_name = twstock.codes[code].name
        except:
            stock_name = code

        # 3. 抓取資料
        stock = yf.Ticker(symbol)
        df = stock.history(period="3mo") 
        
        # 資料防呆
        if df.empty or len(df) < 50: # 放寬一點，有些剛上市的資料較少
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        close = latest['Close']
        volume = latest['Volume']
        pct_change = (close - prev['Close']) / prev['Close'] * 100
        
        # RSI 計算
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        # MA 計算
        ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
        ma60 = df['Close'].rolling(window=60).mean().iloc[-1]

        # --- 🚦 燈號判斷邏輯 ---
        status = "YELLOW"
        
        # [綠燈] 避雷/賣出
        if volume < 50 or (pct_change <= -9.5 and close == latest['Low']) or (close < ma20 and rsi < 40):
            status = "GREEN"
        
        # [紅燈] 關注/買進
        elif close > ma20 and rsi > 55 and ma20 > ma60:
            status = "RED"
            
        return {
            "code": code,
            "name": stock_name,
            "price": round(close, 1),
            "pct_change": round(pct_change, 2),
            "status": status,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        
    except Exception as e:
        # print(f"Error {code}: {e}") # debug 用，平常可關閉
        return None

# ==========================================
# 3. 主程式
# ==========================================

def main():
    results = {}
    count = 0
    success_count = 0
    
    print(f"🚀 開始掃描台灣 Top 100 權值股...")
    
    for code in TARGET_CODES:
        data = analyze_stock_logic(code)
        count += 1
        
        if data:
            results[code] = data
            success_count += 1
            # 格式化輸出，看起來比較整齊
            print(f"[{data['status']}] {code:<4} {data['name']:<6} ${data['price']:<7} ({data['pct_change']:+.2f}%)")
        
        # 雖然只有 100 檔，但還是稍微休息一下比較保險
        if count % 20 == 0:
            print(f"⏳ 進度: {count} / {len(TARGET_CODES)}... 休息 1 秒")
            time.sleep(1) 
            
    with open("stock_database.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    
    print(f"\n🎉 掃描完成！成功率: {success_count}/{len(TARGET_CODES)}")
    print("📁 資料已儲存，請重新整理你的戰情室網頁。")

if __name__ == "__main__":
    main()