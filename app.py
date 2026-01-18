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
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 頁面設定 ---
st.set_page_config(page_title="台股 AI 戰情室", layout="wide", initial_sidebar_state="expanded")
st.title("📈 台股 AI 全方位戰情室 (籌碼升級版)")

# --- 讀取本地資料庫 ---
def load_database():
    if os.path.exists("stock_database.json"):
        with open("stock_database.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

db = load_database()

# 初始化 Session
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

    user_input = st.text_input("輸入代號或名稱", value=st.session_state.ticker)
    run_clicked = st.button("🚀 AI 深度分析", type="primary", use_container_width=True)
    should_run = run_clicked or st.session_state.auto_run

# --- 3. 核心函數 ---

def get_google_news(symbol):
    """取得新聞標題清單"""
    clean_symbol = symbol.split(' ')[0].replace('.TW', '').replace('.TWO', '')
    rss_url = f"https://news.google.com/rss/search?q={clean_symbol}+tw+stock&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(rss_url)
    return feed.entries[:5] 

# 🔥 新增：抓取籌碼面數據 (FinMind)
def get_chip_data(stock_id):
    try:
        dl = DataLoader()
        # 抓取過去 15 天數據，確保有足夠資料
        start_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
        
        # 下載三大法人數據
        df = dl.taiwan_stock_institutional_investors_buy_sell(
            data_id=stock_id,
            start_date=start_date
        )
        
        if df.empty:
            return "無籌碼資料"

        # 整理最近 5 日累積買賣超
        df['date'] = pd.to_datetime(df['date'])
        recent_df = df.sort_values('date').tail(15) # 取最後幾筆
        
        # 計算外資、投信、自營商的近5日累計
        summary = recent_df.groupby('name')['buy_sell'].sum()
        
        foreign = summary.get('Foreign_Investor', 0) // 1000 # 換算成張數
        trust = summary.get('Investment_Trust', 0) // 1000
        dealer = summary.get('Dealer', 0) // 1000
        
        # 產生描述字串
        chip_desc = f"""
        - 外資 (Foreign Inv): 近期累積買賣超 {int(foreign)} 張
        - 投信 (Inv Trust): 近期累積買賣超 {int(trust)} 張
        - 自營商 (Dealer): 近期累積買賣超 {int(dealer)} 張
        """
        return chip_desc
    except Exception as e:
        return f"籌碼資料讀取失敗: {e}"

def get_stock_data(input_query):
    # 智慧代號判斷
    display_name = input_query
    # 為了 FinMind，我們需要純數字代號
    stock_id_only = input_query 
    
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
        
        # 指標計算
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        
        return df, stock, display_name, fundamentals, stock_id_only
    except:
        return None, None, None, None, None

def check_risk_status(latest_row):
    if latest_row['Volume'] < 50:
        return "DANGER", f"⚠️ 流動性枯竭 ({int(latest_row['Volume'])} 張)"
    if latest_row['PctChange'] <= -9.5 and latest_row['Close'] == latest_row['Low']:
        return "DANGER", "🔴 跌停鎖死"
    return "NORMAL", ""

def plot_chart(df, symbol):
    plot_df = df.tail(120) 
    
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        subplot_titles=(f"{symbol} 走勢", "成交量", "RSI"), 
        row_heights=[0.5, 0.2, 0.3]
    )
    
    fig.add_trace(go.Candlestick(
        x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], 
        low=plot_df['Low'], close=plot_df['Close'], name="K線"
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['MA20'], line=dict(color='orange', width=1), name="月線"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['MA60'], line=dict(color='blue', width=1), name="季線"), row=1, col=1)
    
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in plot_df.iterrows()]
    fig.add_trace(go.Bar(
        x=plot_df.index, y=plot_df['Volume'], 
        marker_color=colors, name="成交量"
    ), row=2, col=1)

    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['RSI'], line=dict(color='purple', width=2), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
    
    fig.update_layout(xaxis_rangeslider_visible=False, height=700, margin=dict(l=10, r=10, t=30, b=10), showlegend=False, dragmode='pan')
    return fig

# --- 🚀 AI 分析優化：加入籌碼面 ---
def ask_llama(df, symbol, key, fundamentals, risk_status, scan_status, news_list, chip_data):
    client = Groq(api_key=key)
    latest = df.iloc[-1]
    
    news_text = "無重大新聞"
    if news_list:
        news_text = "\n".join([f"- {n.title}" for n in news_list])

    # 技術位置計算
    high_60d = df['Close'].tail(60).max()
    low_60d = df['Close'].tail(60).min()
    price_pos = (latest['Close'] - low_60d) / (high_60d - low_60d) * 100 
    
    trend_desc = ""
    if price_pos > 90: trend_desc = "股價處於近一季高點，強勢但需注意回檔"
    elif price_pos < 10: trend_desc = "股價處於近一季低點，弱勢探底中"
    else: trend_desc = "股價處於區間震盪整理"

    # 量能計算
    avg_vol = df['Volume'].tail(20).mean()
    curr_vol = latest['Volume']
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0
    
    vol_desc = ""
    if vol_ratio > 2.0: vol_desc = "今日爆出兩倍以上巨量"
    elif vol_ratio > 1.3: vol_desc = "成交量溫和放大"
    elif vol_ratio < 0.6: vol_desc = "成交量急凍"
    else: vol_desc = "成交量正常"

    # Prompt 組合
    prompt = f"""
    角色：你是一位精通技術面與籌碼面的台股操盤手。
    目標：分析 {symbol}。

    【📊 市場情報】
    1. 系統掃描：{scan_status} (RED=多頭, GREEN=空頭)
    2. 新聞頭條：
    {news_text}
    
    【🏛️ 籌碼面數據 (法人動向)】
    {chip_data}
    *解釋：外資通常代表長期趨勢，投信代表波段行情。若外資投信同步買超為最強訊號。

    【📈 技術型態】
    - 價格位置：{trend_desc} (近60日位置: {price_pos:.0f}%)
    - 量能狀態：{vol_desc} (量比: {vol_ratio:.1f}倍)
    - RSI 指標：{latest['RSI']:.0f} (若>75過熱, <30超賣)
    - 均線：股價{"站上" if latest['Close'] > latest['MA20'] else "跌破"}月線，{"站上" if latest['Close'] > latest['MA60'] else "跌破"}季線。

    【⚠️ 決策邏輯要求】
    1. **籌碼優先**：如果技術面轉弱(例如跌破月線)，但「外資」或「投信」呈現大買超，請解讀為「籌碼沉澱/洗盤」，建議觀望而非直接賣出。
    2. **量價配合**：如果是「價漲量增」且「法人買超」，請給予強力買進評價。
    3. **口語化**：像老手帶新手一樣講解。

    【輸出格式】
    第一行：[建議：強力買進] 或 [建議：拉回買進] 或 [建議：觀望持有] 或 [建議：分批賣出]
    
    第二行開始內文：
    1. 🏛️ 籌碼解讀 (分析外資投信動向)
    2. 🎯 技術與量價分析
    3. 📰 新聞與市場情緒
    4. 💡 操盤手叮嚀
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=1000 
        )
        return completion.choices[0].message.content
    except: return "Error: AI 連線失敗"

# --- 4. 主程式執行 ---
if should_run:
    st.session_state.auto_run = False
    
    with st.spinner(f"🔍 正在調閱 '{user_input}' 的圖表、新聞與法人籌碼..."):
        df, stock, symbol, fundamentals, stock_id_only = get_stock_data(user_input)
        news_entries = get_google_news(user_input) 
        
        # 取得籌碼資料
        chip_data_text = "無籌碼資料 (可能為 ETF 或資料來源異常)"
        if stock_id_only:
             chip_data_text = get_chip_data(stock_id_only)

    if df is not None:
        df['PctChange'] = df['Close'].pct_change() * 100
        latest_row = df.iloc[-1]
        risk_level, risk_msg = check_risk_status(latest_row)
        
        scan_status = "未知"
        if user_input in db:
            scan_status = db[user_input]['status']

        st.subheader(f"{symbol}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("股價", f"{latest_row['Close']:.1f}", f"{latest_row['PctChange']:.2f}%")
        c2.metric("成交量", f"{int(latest_row['Volume']):,} 張")
        c3.metric("RSI", f"{latest_row['RSI']:.1f}")
        c4.metric("系統掃描", scan_status)

        if risk_level == "DANGER": st.error(risk_msg)

        tab1, tab2 = st.tabs(["📊 綜合戰情分析", "📰 歷史新聞存檔"])
        
        with tab1:
            st.plotly_chart(plot_chart(df, symbol), use_container_width=True)
            
            if api_key:
                # 傳入 chip_data_text 給 AI
                ai_response = ask_llama(df, symbol, api_key, fundamentals, (risk_level, risk_msg), scan_status, news_entries, chip_data_text)
                
                lines = ai_response.split('\n')
                verdict = lines[0]
                analysis_body = '\n'.join(lines[1:])
                
                if "強力買進" in verdict or "拉回買進" in verdict:
                    st.markdown(f"""<div style="padding: 15px; background-color: #ffe6e6; border-left: 6px solid #ff4b4b; border-radius: 5px; margin-bottom: 15px;"><h3 style="color: #ff4b4b; margin:0;">🚀 {verdict.replace('[', '').replace(']', '')}</h3></div>""", unsafe_allow_html=True)
                elif "賣出" in verdict:
                    st.markdown(f"""<div style="padding: 15px; background-color: #e6ffe6; border-left: 6px solid #28a745; border-radius: 5px; margin-bottom: 15px;"><h3 style="color: #28a745; margin:0;">🛡️ {verdict.replace('[', '').replace(']', '')}</h3></div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div style="padding: 15px; background-color: #fff3cd; border-left: 6px solid #ffc107; border-radius: 5px; margin-bottom: 15px;"><h3 style="color: #d39e00; margin:0;">👀 {verdict.replace('[', '').replace(']', '')}</h3></div>""", unsafe_allow_html=True)
                
                st.markdown(analysis_body)
            else:
                st.warning("請輸入 API Key 以啟用 AI 分析")

        with tab2:
            for n in news_entries:
                st.markdown(f"- [{n.title}]({n.link})")
    else:
        st.error("查無資料，請確認代號或上市櫃狀態。")