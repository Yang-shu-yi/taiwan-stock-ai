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

# 嘗試讀取 API Key
try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ==========================================
# 2. 核心功能函數 (升級版)
# ==========================================
def resolve_stock_code(query):
    """智慧解析：輸入 '2330' 或 '台積電'，都能找到代號"""
    query = query.strip()
    target_code = None
    market_type = "上市" # 預設

    if query.isdigit(): # 如果輸入數字
        target_code = query
        if target_code in twstock.codes:
            market_type = twstock.codes[target_code].market
    else: # 如果輸入中文
        for code in twstock.codes:
            if twstock.codes[code].name == query:
                target_code = code
                market_type = twstock.codes[code].market
                break
    
    if target_code:
        suffix = ".TW" if market_type == "上市" else ".TWO"
        return target_code, suffix, twstock.codes[target_code].name
    return None, None, None

def get_ai_analysis(code, name, df):
    if not GROQ_API_KEY:
        return "⚠️ 請先設定 GROQ_API_KEY 才能使用 AI 分析功能。"
    
    close = df['Close']
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]
    ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
    price = close.iloc[-1]
    
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"""
    你是一位專業操盤手。請分析 {name} ({code})。
    技術數據：現價 {price:.2f}, MA20 {ma20:.2f}, RSI {rsi:.1f}。
    請給出：1. 趨勢判斷 2. 支撐壓力 3. 操作建議 (買進/觀望/賣出)。
    請用繁體中文，條列式回答。
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=450
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI 連線失敗: {e}"

# ==========================================
# 3. 初始化 Session State (記憶搜尋狀態)
# ==========================================
if 'current_stock' not in st.session_state:
    st.session_state['current_stock'] = None

# ==========================================
# 4. 側邊欄 UI (維持原版排版)
# ==========================================
st.sidebar.title("📂 戰情室資料庫")

if st.sidebar.button("🔄 重新讀取檔案"):
    st.rerun()

# 讀取資料庫
db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    # 防呆：抓取更新時間
    if db:
        first_item = next(iter(db.values()))
        update_time = first_item.get('update_time', '時間未知')
        st.sidebar.caption(f"上次更新: {update_time}")
    else:
        st.sidebar.warning("資料庫目前為空")
except:
    st.sidebar.error("讀取資料庫失敗")

# 資料分類
red_list = [v for k,v in db.items() if v.get('status') == 'RED']
green_list = [v for k,v in db.items() if v.get('status') == 'GREEN']
yellow_list = [v for k,v in db.items() if v.get('status') == 'YELLOW']

# --- 列表顯示區 (點擊後把股票代號存入 Session) ---
with st.sidebar:
    # 紅燈區
    with st.expander(f"🔴 強力關注 ({len(red_list)})", expanded=True):
        for item in red_list:
            # 這裡用 pct_change 防呆，如果沒有就顯示 0
            change = item.get('pct_change', 0)
            btn_label = f"{item['code']} {item['name']} ${item['price']} ({change}%)"
            if st.button(btn_label, key=f"btn_{item['code']}"):
                st.session_state['current_stock'] = item['code'] # 記住點了誰

    # 綠燈區
    with st.expander(f"🟢 避雷/賣出 ({len(green_list)})"):
        for item in green_list:
            if st.button(f"{item['code']} {item['name']}", key=f"btn_{item['code']}"):
                st.session_state['current_stock'] = item['code']

    # 黃燈區
    with st.expander(f"🟡 觀望持有 ({len(yellow_list)})"):
        for item in yellow_list:
            if st.button(f"{item['code']} {item['name']}", key=f"btn_{item['code']}"):
                st.session_state['current_stock'] = item['code']

    st.sidebar.markdown("---")
    
    # --- 搜尋區 (這裡就是你要的「補齊搜尋功能」) ---
    st.sidebar.write("輸入代號或中文股名 (如: 國碩)")
    search_query = st.sidebar.text_input("Search Box", label_visibility="collapsed")
    
    if st.sidebar.button("🚀 AI 深度分析", type="primary", use_container_width=True):
        if search_query:
            # 呼叫解析函數，把「國碩」轉成「2406」
            resolved_code, _, _ = resolve_stock_code(search_query)
            if resolved_code:
                st.session_state['current_stock'] = resolved_code
            else:
                st.sidebar.error("❌ 找不到該股票，請確認名稱")

# ==========================================
# 5. 主畫面 UI (顯示分析結果)
# ==========================================
st.title("📈 台股 AI 全方位戰情室")

# 檢查是否有選中股票 (無論是點列表 還是 搜尋來的)
target = st.session_state['current_stock']

if target:
    # 解析代號與名稱
    code, suffix, name = resolve_stock_code(target)
    
    if code:
        try:
            st.subheader(f"📊 {name} ({code}) 即時分析")
            
            # 1. 抓取即時資料 (不依賴 JSON，直接抓最新的)
            with st.spinner(f"正在連線抓取 {name} 最新數據..."):
                ticker = yf.Ticker(f"{code}{suffix}")
                df = ticker.history(period="6mo")
            
            if len(df) < 5:
                st.error("無法取得該股資料 (可能暫停交易或代號錯誤)")
            else:
                # 2. 畫圖 (K線 + 均線)
                df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
                df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
                
                fig = go.Figure(data=[
                    go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="K線"),
                    go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1), name="MA20"),
                    go.Scatter(x=df.index, y=df['MA60'], line=dict(color='green', width=1), name="MA60")
                ])
                fig.update_layout(xaxis_rangeslider_visible=False, height=450)
                st.plotly_chart(fig, use_container_width=True)

                # 3. AI 分析
                st.markdown("### 🤖 AI 操盤手觀點")
                with st.chat_message("assistant"):
                    with st.spinner("AI 正在分析技術型態..."):
                        analysis = get_ai_analysis(code, name, df)
                        st.write(analysis)
                        
        except Exception as e:
            st.error(f"發生錯誤: {e}")
    else:
        st.error("無效的股票代號")

else:
    # 預設畫面 (沒選股票時顯示)
    st.info("👈 請從左側側邊欄選擇股票，或輸入代號/中文名稱進行搜尋。")