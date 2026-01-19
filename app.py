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

try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ==========================================
# 2. 核心功能函數
# ==========================================
def resolve_stock_code(query):
    """智慧解析代號"""
    query = query.strip()
    target_code = None
    market_type = "上市"

    if query.isdigit():
        target_code = query
        if target_code in twstock.codes:
            market_type = twstock.codes[target_code].market
    else:
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
    """
    🔥 核心修改：優化 Prompt，讓 AI 輸出符合參考圖的漂亮排版
    """
    if not GROQ_API_KEY:
        return "⚠️ 請先設定 GROQ_API_KEY 才能使用 AI 分析功能。"
    
    # 準備數據
    close = df['Close']
    open_p = df['Open']
    high = df['High']
    low = df['Low']
    vol = df['Volume']
    
    # 計算指標
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]
    ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
    ma60 = ta.trend.sma_indicator(close, window=60).iloc[-1]
    price = close.iloc[-1]
    vol_latest = vol.iloc[-1]
    
    # 判斷均線趨勢
    trend = "多頭排列" if ma20 > ma60 else "整理/空頭"
    
    client = Groq(api_key=GROQ_API_KEY)
    
    # 📝 這裡就是讓 AI 變聰明的關鍵 Prompt
    prompt = f"""
    你是一位專業的台股分析師。請分析 {name} ({code})。
    【技術數據】
    - 現價: {price:.2f}
    - MA20 (月線): {ma20:.2f}
    - MA60 (季線): {ma60:.2f}
    - RSI (14): {rsi:.1f}
    - 成交量: {vol_latest}
    - 均線趨勢: {trend}

    請**嚴格依照以下格式**輸出內容 (不要有開場白，直接輸出)：

    # 建議：[強力買進 / 拉回買進 / 觀望 / 減碼] (請選一個最適合的)

    ### 📈 技術分析
    * (請分析均線支撐壓力、RSI 是否過熱或背離)
    * (判斷目前股價的位階與動能)

    ### ⚖️ 量能與籌碼判斷
    * (根據成交量判斷是否有人氣，或是否量價背離)
    * (推測主力或市場目前的心態)

    ### 💡 操作建議
    * (給出具體的「支撐位」與「壓力位」價格)
    * (說明適合的進場點與停損點)
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=600
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI 連線失敗: {e}"

# ==========================================
# 3. 初始化 Session State
# ==========================================
if 'current_stock' not in st.session_state:
    st.session_state['current_stock'] = None

# ==========================================
# 4. 側邊欄 UI (維持原樣)
# ==========================================
st.sidebar.title("📂 戰情室資料庫")
if st.sidebar.button("🔄 重新讀取"):
    st.rerun()

db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    if db:
        first_item = next(iter(db.values()))
        st.sidebar.caption(f"上次更新: {first_item.get('update_time', '未知')}")
    else:
        st.sidebar.warning("資料庫為空")
except:
    st.sidebar.error("讀取資料庫失敗")

red_list = [v for k,v in db.items() if v.get('status') == 'RED']
green_list = [v for k,v in db.items() if v.get('status') == 'GREEN']
yellow_list = [v for k,v in db.items() if v.get('status') == 'YELLOW']

with st.sidebar:
    with st.expander(f"🔴 強力關注 ({len(red_list)})", expanded=True):
        for item in red_list:
            c = item.get('pct_change', 0)
            if st.button(f"{item['code']} {item['name']} ${item['price']} ({c}%)", key=f"btn_{item['code']}"):
                st.session_state['current_stock'] = item['code']

    with st.expander(f"🟢 避雷/賣出 ({len(green_list)})"):
        for item in green_list:
            if st.button(f"{item['code']} {item['name']}", key=f"btn_{item['code']}"):
                st.session_state['current_stock'] = item['code']

    with st.expander(f"🟡 觀望持有 ({len(yellow_list)})"):
        for item in yellow_list:
            if st.button(f"{item['code']} {item['name']}", key=f"btn_{item['code']}"):
                st.session_state['current_stock'] = item['code']

    st.sidebar.markdown("---")
    st.sidebar.write("輸入代號或中文股名")
    search_query = st.sidebar.text_input("Search", label_visibility="collapsed")
    if st.sidebar.button("🚀 AI 深度分析", type="primary", use_container_width=True):
        if search_query:
            resolved_code, _, _ = resolve_stock_code(search_query)
            if resolved_code:
                st.session_state['current_stock'] = resolved_code
            else:
                st.sidebar.error("❌ 找不到該股票")

# ==========================================
# 5. 主畫面 UI (美化版)
# ==========================================
st.title("📈 台股 AI 全方位戰情室")

target = st.session_state['current_stock']

if target:
    code, suffix, name = resolve_stock_code(target)
    
    if code:
        try:
            # 1. 抓取資料
            ticker = yf.Ticker(f"{code}{suffix}")
            df = ticker.history(period="6mo")
            
            if len(df) < 5:
                st.error("無法取得該股資料")
            else:
                # 計算即時漲跌
                latest_price = df['Close'].iloc[-1]
                prev_price = df['Close'].iloc[-2]
                change = latest_price - prev_price
                pct = (change / prev_price) * 100
                color = "red" if change > 0 else "green"
                
                # 顯示大標題
                st.markdown(f"## {name} ({code})")
                st.markdown(f"### <span style='color:{color}'>${latest_price:.2f} ({pct:+.2f}%)</span>", unsafe_allow_html=True)

                # 2. 繪圖
                df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
                df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
                
                fig = go.Figure(data=[
                    go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="K線"),
                    go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1), name="MA20"),
                    go.Scatter(x=df.index, y=df['MA60'], line=dict(color='green', width=1), name="MA60")
                ])
                fig.update_layout(xaxis_rangeslider_visible=False, height=400, margin=dict(t=0, b=0))
                st.plotly_chart(fig, use_container_width=True)

                # 3. AI 分析 (UI 美化核心區)
                st.markdown("---")
                with st.chat_message("assistant"):
                    with st.spinner(f"AI 正在根據 {name} 的技術面與籌碼進行推演..."):
                        full_analysis = get_ai_analysis(code, name, df)
                        
                        # 🔥 這裡做「字串切割」，把標題和內容分開
                        try:
                            parts = full_analysis.split('\n', 1) # 切割第一行
                            header = parts[0].replace('#', '').strip() # 這是「建議：買進」
                            body = parts[1].strip() if len(parts) > 1 else ""
                            
                            # 🎨 根據建議顯示不同顏色的橫幅 (模仿參考圖)
                            if "買進" in header:
                                st.error(f"### {header}") # 紅色 (台股多頭代表色)
                            elif "觀望" in header or "持有" in header:
                                st.warning(f"### {header}") # 黃色
                            else:
                                st.success(f"### {header}") # 綠色 (空頭)
                                
                            # 顯示剩下的內容
                            st.markdown(body)
                            
                        except:
                            # 萬一 AI 格式跑掉，就直接印出來
                            st.markdown(full_analysis)
                        
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            st.write(e) # 印出詳細錯誤方便除錯
    else:
        st.error("無效的股票代號")
else:
    st.info("👈 請從左側選擇股票，或輸入代號搜尋。")