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
import requests  # 👈 關鍵：使用輕量級 requests 抓籌碼
from datetime import datetime, timedelta

# --- 1. 頁面設定 ---
st.set_page_config(page_title="台股 AI 戰情室", layout="wide", initial_sidebar_state="expanded")
st.title("📈 台股 AI 全方位戰情室 (專業版 v3.1)")

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

# --- 2. 側邊欄導航 ---
with st.sidebar:
    st.header("🗂️ 戰情室資料庫")
    
    if st.button("🔄 重新讀取檔案"):
        st.cache_data.clear()
        st.rerun()

    # 分類顯示
    red_list = [v for k, v in db.items() if v['status'] == 'RED']
    green_list = [v for k, v in db.items() if v['status'] == 'GREEN']
    yellow_list = [v for k, v in db.items() if v['status'] == 'YELLOW']

    st.caption(f"上次更新: {list(db.values())[0]['update_time'] if db else '無資料'}")

    with st.expander(f"🔴 強力關注 ({len(red_list)})", expanded=True):
        for item in red_list:
            # 按鈕點擊後更新 Session State 並觸發重跑
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
    
    # API Key 管理
    if "GROQ_API_KEY" in st.secrets:
        api_key = st.secrets["GROQ_API_KEY"]
    else:
        api_key = st.text_input("輸入 Groq API Key", type="password")

    # 手動輸入區
    user_input = st.text_input("輸入代號或名稱", value=st.session_state.ticker)
    run_clicked = st.button("🚀 AI 深度分析", type="primary", use_container_width=True)
    should_run = run_clicked or st.session_state.auto_run

# --- 3. 核心函數庫 ---

def get_google_news(symbol):
    """取得新聞標題"""
    clean_symbol = symbol.split(' ')[0].replace('.TW', '').replace('.TWO', '')
    rss_url = f"https://news.google.com/rss/search?q={clean_symbol}+tw+stock&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(rss_url)
    return feed.entries[:5] 

def get_chip_data(stock_id):
    """取得籌碼面數據 (API 直連版，不依賴 FinMind 套件)"""
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        start_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
        parameter = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": stock_id,
            "start_date": start_date,
            "token": "" # 公開資料不需 Token
        }
        
        r = requests.get(url, params=parameter)
        data = r.json()
        
        if "data" not in data or not data["data"]:
            return "無籌碼資料 (可能為 ETF 或資料來源異常)"
            
        df = pd.DataFrame(data["data"])
        
        # 整理數據
        df['buy'] = df['buy'].astype(int)
        df['sell'] = df['sell'].astype(int)
        df['buy_sell'] = df['buy'] - df['sell']
        
        # 取最近 10 筆合併計算
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
    except Exception as e:
        return f"籌碼資料讀取失敗: {e}"

def get_stock_data(input_query):
    """取得股價與基本面"""
    display_name = input_query
    stock_id_only = input_query 
    
    # 智慧代號轉換
    if input_query.isdigit() and input_query in twstock.codes:
        display_name = f"{twstock.codes[input_query].name} ({input_query})"
        stock_id_only = input_query
    
    suffix = ".TW"
    if input_query.isdigit() and input_query in twstock.codes:
        if twstock.codes[input_query].market == "上櫃":
            suffix = ".TWO"
            
    symbol = f"{input_query}{suffix}" if input_query.isdigit() else f"{input_query}.TW"
    
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
        
        # 技術指標計算
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        
        return df, stock, display_name, fundamentals, stock_id_only
    except:
        return None, None, None, None, None

def check_risk_status(latest_row):
    """簡易風險檢查"""
    if latest_row['Volume'] < 50:
        return "DANGER", f"⚠️ 流動性枯竭 ({int(latest_row['Volume'])} 張)"
    if latest_row['PctChange'] <= -9.5 and latest_row['Close'] == latest_row['Low']:
        return "DANGER", "🔴 跌停鎖死"
    return "NORMAL", ""

def plot_chart(df, symbol):
    """繪製互動式圖表"""
    plot_df = df.tail(120) 
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        subplot_titles=(f"{symbol} 走勢", "成交量", "RSI"), 
        row_heights=[0.5, 0.2, 0.3]
    )
    
    # K線
    fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], name="K線"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['MA20'], line=dict(color='orange', width=1), name="月線"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['MA60'], line=dict(color='blue', width=1), name="季線"), row=1, col=1)
    
    # 成交量
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in plot_df.iterrows()]
    fig.add_trace(go.Bar(x=plot_df.index, y=plot_df['Volume'], marker_color=colors, name="成交量"), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['RSI'], line=dict(color='purple', width=2), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
    
    fig.update_layout(xaxis_rangeslider_visible=False, height=700, margin=dict(l=10, r=10, t=30, b=10), showlegend=False, dragmode='pan')
    return fig

# 🔥 AI 分析優化：加入 Emoji 排版指令
def ask_llama(df, symbol, key, fundamentals, risk_status, scan_status, news_list, chip_data):
    client = Groq(api_key=key)
    latest = df.iloc[-1]
    
    news_text = "無重大新聞"
    if news_list:
        news_text = "\n".join([f"- {n.title}" for n in news_list])

    # 輔助計算
    high_60d = df['Close'].tail(60).max()
    low_60d = df['Close'].tail(60).min()
    price_pos = (latest['Close'] - low_60d) / (high_60d - low_60d) * 100 
    
    trend_desc = "區間震盪"
    if price_pos > 85: trend_desc = "波段高點"
    elif price_pos < 15: trend_desc = "波段低點"

    avg_vol = df['Volume'].tail(20).mean()
    vol_ratio = latest['Volume'] / avg_vol if avg_vol > 0 else 0
    vol_desc = "量能放大" if vol_ratio > 1.3 else "量能正常"

    prompt = f"""
    角色：你是一位精通技術面與籌碼面的台股操盤手，擅長將複雜數據化為簡單易讀的報告。
    目標：分析 {symbol}。

    【📊 市場情報】
    1. 系統掃描：{scan_status} (RED=多頭, GREEN=空頭, YELLOW=盤整)
    2. 新聞頭條：{news_text}
    
    【🏛️ 籌碼數據】
    {chip_data}

    【📈 技術指標】
    - 位置：{trend_desc} (Pos: {price_pos:.0f}%)
    - 量能：{vol_desc} (量比: {vol_ratio:.1f}倍)
    - RSI：{latest['RSI']:.0f} (若>75過熱, <30超賣)
    - 均線：股價{"站上" if latest['Close'] > latest['MA20'] else "跌破"}月線。

    【⚠️ 嚴格輸出排版要求】
    請不要寫成一大段文章。務必使用以下 Emoji 作為標題，並以「條列式 (Bullet Points)」呈現重點：

    第一行：[建議：強力買進 / 拉回買進 / 觀望持有 / 分批賣出] (四選一)

    (空一行)

    🏛️ **法人籌碼解讀**
    - (請在此列出外資、投信的動向，並解讀是大戶進場還是出貨)

    📰 **新聞與基本面**
    - (請在此整合新聞利多/利空與EPS等數據)

    📈 **技術與量價分析**
    - (請解讀RSI、均線與成交量的關係，特別注意是否過熱或背離)

    💡 **操盤手叮嚀**
    - (給出明確的操作區間或停損停利建議)
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=1200 
        )
        return completion.choices[0].message.content
    except: return "Error: AI 連線失敗"

# --- 4. 主程式執行邏輯 ---
if should_run:
    st.session_state.auto_run = False
    
    with st.spinner(f"🔍 正在調閱 '{user_input}' 的圖表、新聞與籌碼..."):
        df, stock, symbol, fundamentals, stock_id_only = get_stock_data(user_input)
        news_entries = get_google_news(user_input) 
        
        chip_data_text = "無籌碼資料"
        if stock_id_only:
             chip_data_text = get_chip_data(stock_id_only)

    if df is not None:
        df['PctChange'] = df['Close'].pct_change() * 100
        latest_row = df.iloc[-1]
        risk_level, risk_msg = check_risk_status(latest_row)
        scan_status = db.get(user_input, {}).get('status', '未知')

        st.subheader(f"{symbol}")
        
        # 關鍵數據指標
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("股價", f"{latest_row['Close']:.1f}", f"{latest_row['PctChange']:.2f}%")
        c2.metric("成交量", f"{int(latest_row['Volume']):,} 張")
        c3.metric("RSI", f"{latest_row['RSI']:.1f}")
        c4.metric("系統掃描", scan_status)

        if risk_level == "DANGER": st.error(risk_msg)

        # 頁籤分類
        tab1, tab2 = st.tabs(["📊 綜合戰情分析", "📰 歷史新聞"])
        
        with tab1:
            st.plotly_chart(plot_chart(df, symbol), use_container_width=True)
            
            if api_key:
                ai_response = ask_llama(df, symbol, api_key, fundamentals, (risk_level, risk_msg), scan_status, news_entries, chip_data_text)
                st.info(ai_response)
            else:
                st.warning("請輸入 API Key 以啟用 AI 分析")

        with tab2:
            for n in news_entries:
                st.markdown(f"- [{n.title}]({n.link})")
    else:
        st.error("查無資料，請確認代號或上市櫃狀態。")