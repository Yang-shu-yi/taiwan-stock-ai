import streamlit as st
import yfinance as yf
import pandas as pd
import twstock
import ta
import json
import os
import plotly.graph_objects as go
from groq import Groq
from datetime import datetime

# ==========================================
# 1. 設定與金鑰讀取
# ==========================================
st.set_page_config(page_title="台股 AI 戰情室", layout="wide", page_icon="📈")

# 嘗試從 Secrets 讀取 (Streamlit Cloud)，如果沒有則讀取環境變數 (Local)
try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ==========================================
# 2. 核心功能函數
# ==========================================
def get_stock_name(code):
    """輸入代號，回傳中文股名 (使用 twstock)"""
    try:
        return twstock.codes[code].name
    except:
        return code

def resolve_stock_code(query):
    """智慧解析：輸入 '2330' 或 '台積電'，回傳 '2330' 與市場別"""
    query = query.strip() # 去除前後空白
    
    target_code = None
    market_type = "上市" # 預設
    
    # 情況 A: 輸入的是代號 (如 2330)
    if query.isdigit():
        target_code = query
        if target_code in twstock.codes:
            market_type = twstock.codes[target_code].market
            
    # 情況 B: 輸入的是中文 (如 台積電)
    else:
        for code in twstock.codes:
            if twstock.codes[code].name == query:
                target_code = code
                market_type = twstock.codes[code].market
                break
                
    if target_code:
        suffix = ".TW" if market_type == "上市" else ".TWO"
        return target_code, suffix, twstock.codes[target_code].name
    else:
        return None, None, None

def get_ai_analysis(code, name, df):
    """呼叫 Groq AI 進行即時分析"""
    if not GROQ_API_KEY:
        return "⚠️ 請先設定 GROQ_API_KEY 才能使用 AI 分析功能。"
    
    close = df['Close']
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]
    ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
    price = close.iloc[-1]
    
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"""
    你是一位專業操盤手。請分析 {name} ({code})。
    技術數據：
    - 現價: {price:.2f}
    - MA20: {ma20:.2f} (判斷支撐/壓力)
    - RSI: {rsi:.1f} (判斷過熱/背離)
    - 趨勢: {"多頭" if price > ma20 else "空頭/整理"}
    
    請給出：
    1. 短評 (趨勢判斷)
    2. 支撐與壓力位建議
    3. 操作建議 (買進/觀望/減碼)
    (請用條列式，語氣專業簡潔)
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=400
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI 分析連線失敗: {str(e)}"

# ==========================================
# 3. 側邊欄：讀取掃描報告 (靜態)
# ==========================================
st.sidebar.title("📂 戰情室資料庫")

# 讀取 JSON 資料庫
db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
        
    # 顯示更新時間 (防呆機制)
    if db:
        first_key = next(iter(db))
        update_time = db[first_key].get('update_time', '時間未知')
        st.sidebar.caption(f"上次更新: {update_time}")
    else:
        st.sidebar.warning("資料庫為空")
except:
    st.sidebar.error("尚未讀取到資料庫 (請等待 GitHub Actions 執行)")

# 分類統計
red_list = [v for k,v in db.items() if v.get('status') == 'RED']
green_list = [v for k,v in db.items() if v.get('status') == 'GREEN']
yellow_list = [v for k,v in db.items() if v.get('status') == 'YELLOW']

# 側邊欄選單
with st.sidebar:
    st.info(f"📊 掃描總數: {len(db)}")
    
    with st.expander(f"🔴 強力關注 ({len(red_list)})", expanded=True):
        for item in red_list:
            # 這裡按鈕點擊後，可以自動填入搜尋欄 (需配合 Session State，這裡先做簡單顯示)
            st.write(f"**{item['code']} {item['name']}** ${item['price']}")
            
    with st.expander(f"🟢 避雷/賣出 ({len(green_list)})"):
        for item in green_list:
            st.write(f"{item['code']} {item['name']} ${item['price']}")

# ==========================================
# 4. 主畫面：全市場搜尋 (動態)
# ==========================================
st.title("📈 台股 AI 全方位戰情室")
st.markdown("---")

col1, col2 = st.columns([3, 1])
with col1:
    query = st.text_input("🔍 輸入代號或中文股名 (例如: 鴻海, 2330, 國碩)", placeholder="支援全台股搜尋...")

with col2:
    st.write("") # 排版用
    st.write("") 
    search_btn = st.button("🚀 AI 深度分析", use_container_width=True)

if search_btn and query:
    code, suffix, name = resolve_stock_code(query)
    
    if code:
        st.success(f"✅ 成功鎖定: {code} {name} ({'上市' if suffix=='.TW' else '上櫃'})")
        
        # 1. 抓取即時資料 (Live Data)
        try:
            with st.spinner(f"正在連線證交所抓取 {name} 資料..."):
                ticker = yf.Ticker(f"{code}{suffix}")
                df = ticker.history(period="6mo") # 抓半年資料畫圖
                
            if len(df) < 5:
                st.error("❌ 資料不足，可能為新股或暫停交易。")
            else:
                # 2. 繪製 K 線圖
                st.subheader(f"📊 {name} ({code}) 技術走勢")
                
                # 計算均線
                df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
                df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
                
                fig = go.Figure(data=[go.Candlestick(x=df.index,
                                open=df['Open'], high=df['High'],
                                low=df['Low'], close=df['Close'], name="K線"),
                                go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1), name="月線"),
                                go.Scatter(x=df.index, y=df['MA60'], line=dict(color='green', width=1), name="季線")
                                ])
                fig.update_layout(xaxis_rangeslider_visible=False, height=400)
                st.plotly_chart(fig, use_container_width=True)
                
                # 3. AI 分析報告
                st.subheader("🤖 AI 操盤手觀點")
                with st.chat_message("assistant"):
                    with st.spinner("AI 正在思考策略..."):
                        analysis = get_ai_analysis(code, name, df)
                        st.markdown(analysis)
                        
        except Exception as e:
            st.error(f"❌ 數據抓取失敗: {e}")
            
    else:
        st.error(f"❌ 找不到 '{query}'，請確認輸入正確 (例如試試輸入代號)。")