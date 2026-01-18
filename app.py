import streamlit as st
import yfinance as yf
import ta
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from groq import Groq
import feedparser
import twstock
import json
import os
import requests
from datetime import datetime, timedelta

# --- 1. 頁面設定 ---
st.set_page_config(page_title="台股 AI 戰情室", layout="wide", initial_sidebar_state="expanded")
st.title("📈 台股 AI 全方位戰情室 (v3.2 中文搜尋優化版)")

# --- 讀取本地資料庫 ---
def load_database():
    if os.path.exists("stock_database.json"):
        with open("stock_database.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

db = load_database()

if "ticker" not in st.session_state:
    st.session_state.ticker = "2330"
if "auto_run" not in st.session_state:
    st.session_state.auto_run = False

# --- 2. 側邊欄 ---
with st.sidebar:
    st.header("🗂️ 戰情室資料庫")
    
    if st.button("🔄 重新讀取檔案"):
        st.cache_data.clear()
        st.rerun()

    red_list = [v for k, v in db.items() if v['status'] == 'RED']
    green_list = [v for k, v in db.items() if v['status'] == 'GREEN']
    yellow_list = [v for k, v in db.items() if v['status'] == 'YELLOW']

    st.caption(f"上次更新: {list(db.values())[0]['update_time'] if db else '無資料'}")

    with st.expander(f"🔴 強力關注 ({len(red_list)})", expanded=True):
        for item in red_list:
            if st.button(f"{item['code']} {item['name']} ${item['price']} ({item['pct_change']}%)", key=f"btn_{item['code']}"):
                st.session_state.ticker = item['code']
                st.session_state.auto_run = True

    with st.expander(f"🟢 避雷/賣出 ({len(green_list)})", expanded=True):
        for item in green_list:
            if st.button(f"{item['code']} {item['name']} ${item['price']} ({item['pct_change']}%)", key=f"btn_{item['code']}"):
                st.session_state.ticker = item['code']
                st.session_state.auto_run = True

    with st.expander(f"🟡 觀望持有 ({len(yellow_list)})", expanded=False):
        for item in yellow_list:
            if st.button(f"{item['code']} {item['name']}", key=f"btn_{item['code']}"):
                st.session_state.ticker = item['code']
                st.session_state.auto_run = True
    
    st.divider()
    
    if "GROQ_API_KEY" in st.secrets:
        api_key = st.secrets["GROQ_API_KEY"]
    else:
        api_key = st.text_input("輸入 Groq API Key", type="password")

    # 搜尋框提示改得更明確
    user_input = st.text_input("輸入代號或中文股名 (如: 鴻海)", value=st.session_state.ticker)
    run_clicked = st.button("🚀 AI 深度分析", type="primary", use_container_width=True)
    should_run = run_clicked or st.session_state.auto_run

# --- 3. 核心函數庫 ---

def get_google_news(symbol):
    clean_symbol = symbol.split(' ')[0].replace('.TW', '').replace('.TWO', '')
    rss_url = f"https://news.google.com/rss/search?q={clean_symbol}+tw+stock&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(rss_url)
    return feed.entries[:5] 

def get_chip_data(stock_id):
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        start_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
        parameter = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": stock_id,
            "start_date": start_date,
            "token": "" 
        }
        r = requests.get(url, params=parameter)
        data = r.json()
        if "data" not in data or not data["data"]: return "無籌碼資料"
        df = pd.DataFrame(data["data"])
        df['buy'] = df['buy'].astype(int)
        df['sell'] = df['sell'].astype(int)
        df['buy_sell'] = df['buy'] - df['sell']
        recent_df = df.tail(10)
        summary = recent_df.groupby('name')['buy_sell'].sum()
        foreign = summary.get('Foreign_Investor', 0) // 1000
        trust = summary.get('Investment_Trust', 0) // 1000
        dealer = summary.get('Dealer', 0) // 1000
        chip_desc = f"""
        - 外資 (Foreign Inv): 近10日累積買賣超 {int(foreign)} 張
        - 投信 (Inv Trust): 近10日累積買賣超 {int(trust)} 張
        - 自營商 (Dealer): 近10日累積買賣超 {int(dealer)} 張
        """
        return chip_desc
    except Exception as e: return f"籌碼讀取失敗: {e}"

# 🔥 新增：中文轉代碼功能
def convert_to_stock_id(query):
    # 如果已經是數字，直接回傳
    if query.isdigit():
        return query
    
    # 如果是中文，去 twstock 裡面撈
    # 這裡做一個簡單的模糊搜尋
    for code, info in twstock.codes.items():
        if query == info.name: # 完全符合 (例如: 台積電)
            return code
    
    # 如果完全符合找不到，試試看包含 (例如輸入 "台積" 找到 "台積電")
    for code, info in twstock.codes.items():
        if query in info.name:
            return code
            
    return query # 真的找不到就回傳原本的，讓後續報錯

def get_stock_data(input_query):
    # 先嘗試轉換中文名稱 -> 代號
    stock_id = convert_to_stock_id(input_query)
    
    # 預設名稱
    display_name = stock_id
    stock_id_only = stock_id
    
    # 取得詳細名稱 (如果是有效代碼)
    if stock_id in twstock.codes:
        display_name = f"{twstock.codes[stock_id].name} ({stock_id})"
    
    # 判斷上市(.TW) 或 上櫃(.TWO)
    suffix = ".TW"
    if stock_id in twstock.codes:
        if twstock.codes[stock_id].market == "上櫃":
            suffix = ".TWO"
            
    symbol = f"{stock_id}{suffix}"
    
    try:
        stock = yf.Ticker(symbol)
        df = stock.history(period="1y")
        if df.empty: return None, None, None, None, None
        
        info = stock.info
        fundamentals = {
            "PE": info.get('trailingPE', 'N/A'),
            "EPS": info.get('trailingEps', 'N/A'),
            "Yield": info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0, 
        }
        
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        
        return df, stock, display_name, fundamentals, stock_id_only
    except:
        return None, None, None, None, None

def check_risk_status(latest_row):
    if latest_row['Volume'] < 50: return "DANGER", f"⚠️ 流動性枯竭"
    if latest_row['PctChange'] <= -9.5 and latest_row['Close'] == latest_row['Low']: return "DANGER", "🔴 跌停鎖死"
    return "NORMAL", ""

def plot_chart(df, symbol):
    plot_df = df.tail(120) 
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, subplot_titles=(f"{symbol} 走勢", "成交量", "RSI"), row_heights=[0.5, 0.2, 0.3])
    fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], name="K線"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['MA20'], line=dict(color='orange', width=1), name="月線"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['MA60'], line=dict(color='blue', width=1), name="季線"), row=1, col=1)
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in plot_df.iterrows()]
    fig.add_trace(go.Bar(x=plot_df.index, y=plot_df['Volume'], marker_color=colors, name="成交量"), row=2, col=1)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['RSI'], line=dict(color='purple', width=2), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False, height=700, margin=dict(l=10, r=10, t=30, b=10), showlegend=False, dragmode='pan')
    return fig

# 🔥 AI 分析優化：加入「具體價位」指令
def ask_llama(df, symbol, key, fundamentals, risk_status, scan_status, news_list, chip_data):
    client = Groq(api_key=key)
    latest = df.iloc[-1]
    news_text = "無重大新聞"
    if news_list: news_text = "\n".join([f"- {n.title}" for n in news_list])

    # 計算技術數據供 AI 參考
    high_60d = df['Close'].tail(60).max()
    low_60d = df['Close'].tail(60).min()
    price_pos = (latest['Close'] - low_60d) / (high_60d - low_60d) * 100 
    
    trend_desc = "區間震盪"
    if price_pos > 85: trend_desc = "波段高點"
    elif price_pos < 15: trend_desc = "波段低點"

    avg_vol = df['Volume'].tail(20).mean()
    vol_ratio = latest['Volume'] / avg_vol if avg_vol > 0 else 0
    vol_desc = "量能放大" if vol_ratio > 1.3 else "量能正常"

    # 組合 Prompt
    prompt = f"""
    角色：台股操盤手。目標：分析 {symbol}。
    
    【📊 情報】
    系統掃描：{scan_status}
    新聞：{news_text}
    籌碼：{chip_data}

    【📈 數據】
    現價：{latest['Close']:.2f}
    位置：{trend_desc} (Pos: {price_pos:.0f}%)
    量能：{vol_desc}
    RSI：{latest['RSI']:.0f}
    均線：{"站上" if latest['Close'] > latest['MA20'] else "跌破"}月線 (MA20: {latest['MA20']:.2f})，{"站上" if latest['Close'] > latest['MA60'] else "跌破"}季線 (MA60: {latest['MA60']:.2f})。
    前高/前低：近60日高點 {high_60d:.2f} / 低點 {low_60d:.2f}

    【⚠️ 嚴格格式】
    第一行：[建議：強力買進 / 拉回買進 / 觀望持有 / 分批賣出] (四選一)
    (空一行)
    🏛️ **法人籌碼**
    - 重點1
    📰 **新聞基本面**
    - 重點2
    📈 **技術分析**
    - 重點3
    💡 **操作建議 (務必包含數值)**
    - 請明確給出「支撐價位」與「壓力價位」的預估數值（例如：支撐看 50.5 元，壓力看 55 元）。
    - 結合 MA20、MA60 或前高前低給出具體操作區間。
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=1000 
        )
        return completion.choices[0].message.content
    except: return "Error: AI 連線失敗"

if should_run:
    st.session_state.auto_run = False
    with st.spinner(f"🔍 正在搜尋 '{user_input}'..."):
        df, stock, symbol, fundamentals, stock_id_only = get_stock_data(user_input)
        news_entries = get_google_news(user_input) 
        chip_data_text = "無籌碼資料"
        if stock_id_only: chip_data_text = get_chip_data(stock_id_only)

    if df is not None:
        df['PctChange'] = df['Close'].pct_change() * 100
        latest_row = df.iloc[-1]
        risk_level, risk_msg = check_risk_status(latest_row)
        scan_status = db.get(user_input, {}).get('status', '未知')

        st.subheader(f"{symbol}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("股價", f"{latest_row['Close']:.1f}", f"{latest_row['PctChange']:.2f}%")
        c2.metric("成交量", f"{int(latest_row['Volume']):,} 張")
        c3.metric("RSI", f"{latest_row['RSI']:.1f}")
        c4.metric("系統掃描", scan_status)

        if risk_level == "DANGER": st.error(risk_msg)

        tab1, tab2 = st.tabs(["📊 綜合戰情分析", "📰 歷史新聞"])
        with tab1:
            st.plotly_chart(plot_chart(df, symbol), use_container_width=True)
            if api_key:
                ai_response = ask_llama(df, symbol, api_key, fundamentals, (risk_level, risk_msg), scan_status, news_entries, chip_data_text)
                
                # 🔥 視覺化優化：拆解 AI 回覆，強調標題 🔥
                if ai_response and "Error" not in ai_response:
                    lines = ai_response.split('\n')
                    title = lines[0] # 第一行是建議
                    body = '\n'.join(lines[1:]) # 剩下是內文
                    
                    # 根據建議內容決定顏色 (台股: 紅漲綠跌)
                    if "買進" in title:
                        box_color = "#ffe6e6" # 淺紅背景
                        border_color = "#ff4b4b" # 深紅邊框
                        text_color = "#ff4b4b"
                    elif "賣出" in title:
                        box_color = "#e6ffe6" # 淺綠背景
                        border_color = "#28a745" # 深綠邊框
                        text_color = "#28a745"
                    else:
                        box_color = "#fff3cd" # 淺黃背景
                        border_color = "#ffc107" # 深黃邊框
                        text_color = "#d39e00"
                    
                    # 使用 HTML 渲染漂亮的標題方塊
                    st.markdown(f"""
                    <div style="
                        padding: 15px; 
                        background-color: {box_color}; 
                        border-left: 6px solid {border_color}; 
                        border-radius: 5px; 
                        margin-bottom: 20px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    ">
                        <h3 style="color: {text_color}; margin:0; font-weight: 700;">{title.replace('[','').replace(']','')}</h3>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.markdown(body)
                else:
                    st.error(ai_response)
            else: st.warning("請輸入 API Key")

        with tab2:
            for n in news_entries: st.markdown(f"- [{n.title}]({n.link})")
    else:
        st.error(f"找不到 '{user_input}'，請確認輸入正確 (支援中文股名，如: 長榮)。")