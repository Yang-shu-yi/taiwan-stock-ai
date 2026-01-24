import streamlit as st
import yfinance as yf
import pandas as pd
import twstock
import ta
import json
import os
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from groq import Groq
from datetime import datetime, timedelta

# ==========================================
# 1. 設定與金鑰
# ==========================================
st.set_page_config(page_title="台股 AI 戰情室", layout="wide", page_icon="📈")

try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ==========================================
# 2. 核心功能：FinMind 籌碼 (輕量 API 版)
# ==========================================
def get_chip_data(code):
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        parameter = {
            "dataset": "TaiwanStockInstitutionalInvestorBuySell",
            "data_id": code,
            "start_date": start_date
        }
        r = requests.get(url, params=parameter, timeout=5)
        data = r.json()
        
        if data['msg'] != 'success' or not data['data']:
            return None
            
        df = pd.DataFrame(data['data'])
        df['name'] = df['name'].map({
            'Foreign_Investor': '外資', 'Investment_Trust': '投信',
            'Dealer_Self': '自營商(自行)', 'Dealer_Hedging': '自營商(避險)'
        })
        
        df['date'] = pd.to_datetime(df['date'])
        df_pivot = df.pivot_table(index='date', columns='name', values='buy_sell', aggfunc='sum').fillna(0)
        return df_pivot
    except:
        return None

# ==========================================
# 3. 功能函數
# ==========================================
def resolve_stock_code(query):
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

def get_ai_analysis(code, name, df_tech, df_chip):
    if not GROQ_API_KEY:
        return "⚠️ 請先設定 GROQ_API_KEY"
    
    close = df_tech['Close']
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]
    ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
    ma60 = ta.trend.sma_indicator(close, window=60).iloc[-1]
    price = close.iloc[-1]
    vol = df_tech['Volume'].iloc[-1]
    
    if df_chip is not None and not df_chip.empty:
        try:
            f_sum = df_chip['外資'].tail(5).sum() if '外資' in df_chip else 0
            t_sum = df_chip['投信'].tail(5).sum() if '投信' in df_chip else 0
            chip_msg = f"近5日外資累計{int(f_sum/1000)}張，投信累計{int(t_sum/1000)}張。"
            if t_sum > 0: chip_msg += " (投信買超)"
            elif f_sum < -5000: chip_msg += " (外資調節)"
        except:
            chip_msg = "籌碼數據中性。"
    else:
        chip_msg = "無籌碼數據。"

    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""
    你是一位專業操盤手。分析 {name} ({code})。
    【數據】價{price:.2f}/MA20 {ma20:.2f}/MA60 {ma60:.2f}/RSI {rsi:.1f}/量 {vol}
    【籌碼】{chip_msg}
    請嚴格依照 Markdown 格式輸出：
    # 建議：[強力買進 / 拉回買進 / 觀望 / 減碼]
    ### 📈 技術分析
    * (重點分析)
    ### ⚖️ 籌碼與量能
    * (重點分析)
    ### 💡 操作建議
    * (支撐/壓力/停損)
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=650
        )
        return completion.choices[0].message.content
    except Exception as e: return f"AI Error: {e}"

# ==========================================
# 4. 初始化 Session
# ==========================================
if 'current_stock' not in st.session_state:
    st.session_state['current_stock'] = None

# ==========================================
# 5. 側邊欄 UI
# ==========================================
st.sidebar.title("📂 戰情室資料庫")
if st.sidebar.button("🔄 重新讀取"): st.rerun()

db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    if db: st.sidebar.caption(f"上次更新: {next(iter(db.values())).get('update_time', '未知')}")
except: pass

red_list = [v for k,v in db.items() if v.get('status') == 'RED']
green_list = [v for k,v in db.items() if v.get('status') == 'GREEN']
yellow_list = [v for k,v in db.items() if v.get('status') == 'YELLOW']

with st.sidebar:
    with st.expander(f"🔴 強力關注 ({len(red_list)})", expanded=True):
        for item in red_list:
            if st.button(f"{item['code']} {item['name']} ${item['price']}", key=f"r_{item['code']}"):
                st.session_state['current_stock'] = item['code']
    with st.expander(f"🟢 避雷區 ({len(green_list)})"):
        for item in green_list:
            if st.button(f"{item['code']} {item['name']}", key=f"g_{item['code']}"):
                st.session_state['current_stock'] = item['code']
    with st.expander(f"🟡 觀望持有 ({len(yellow_list)})"):
        for item in yellow_list:
            if st.button(f"{item['code']} {item['name']}", key=f"y_{item['code']}"):
                st.session_state['current_stock'] = item['code']
    
    st.markdown("---")
    q = st.text_input("搜尋代號/名稱", label_visibility="collapsed")
    if st.button("🚀 分析", type="primary", use_container_width=True) and q:
        c, _, _ = resolve_stock_code(q)
        if c: st.session_state['current_stock'] = c

# ==========================================
# 6. 主畫面 UI (儀表板升級版)
# ==========================================
st.title("📈 台股 AI 戰情室")

target = st.session_state['current_stock']

if target:
    code, suffix, name = resolve_stock_code(target)
    
    if code:
        try:
            # 1. 抓取資料
            ticker = yf.Ticker(f"{code}{suffix}")
            df_tech = ticker.history(period="6mo")
            df_chip = get_chip_data(code)
            
            if len(df_tech) < 5:
                st.error("❌ 無法取得數據")
            else:
                # --- 🔥 重點修改區：儀表板 UI ---
                st.markdown(f"## {name} ({code})")

                # 計算關鍵指標
                close = df_tech['Close']
                latest_price = close.iloc[-1]
                prev_price = close.iloc[-2]
                change = latest_price - prev_price
                pct_change = (change / prev_price) * 100
                
                vol = df_tech['Volume'].iloc[-1]
                rsi = ta.momentum.rsi(close, window=14).iloc[-1]
                
                # 設定顏色 (台股：漲紅跌綠)
                color = "#ff2b2b" if change > 0 else "#2dc937"
                sign = "+" if change > 0 else ""
                bg_color = "rgba(255, 43, 43, 0.1)" if change > 0 else "rgba(45, 201, 55, 0.1)"
                
                # 建立三欄排版
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("##### 股價")
                    st.markdown(f"<h2 style='margin:0; color:{color}'>${latest_price:.2f}</h2>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color:{color}; background-color:{bg_color}; padding: 4px 8px; border-radius: 5px; font-weight:bold'>{sign}{pct_change:.2f}%</span>", unsafe_allow_html=True)

                with col2:
                    st.markdown("##### 成交量")
                    st.markdown(f"<h2 style='margin:0'>{int(vol):,} 張</h2>", unsafe_allow_html=True)
                    st.caption("昨日成交量")

                with col3:
                    st.markdown("##### RSI (14)")
                    st.markdown(f"<h2 style='margin:0'>{rsi:.1f}</h2>", unsafe_allow_html=True)
                    st.caption("相對強弱指標")
                
                st.markdown("---")
                # -------------------------------

                # 2. 繪製圖表
                df_tech['MA20'] = ta.trend.sma_indicator(df_tech['Close'], 20)
                df_tech['MA60'] = ta.trend.sma_indicator(df_tech['Close'], 60)
                
                has_chip = (df_chip is not None and not df_chip.empty)
                
                if has_chip:
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                                        subplot_titles=("技術走勢", "法人籌碼"))
                else:
                    fig = make_subplots(rows=1, cols=1, subplot_titles=("技術走勢",))

                # K線圖
                fig.add_trace(go.Candlestick(x=df_tech.index, open=df_tech['Open'], high=df_tech['High'], 
                                             low=df_tech['Low'], close=df_tech['Close'], name="K線"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_tech.index, y=df_tech['MA20'], line=dict(color='orange', width=1), name="MA20"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_tech.index, y=df_tech['MA60'], line=dict(color='green', width=1), name="MA60"), row=1, col=1)

                # 籌碼圖
                if has_chip:
                    df_chip = df_chip.reindex(df_tech.index).fillna(0)
                    fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['外資'], name="外資", marker_color='blue'), row=2, col=1)
                    fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['投信'], name="投信", marker_color='red'), row=2, col=1)

                fig.update_layout(xaxis_rangeslider_visible=False, height=600 if has_chip else 500, margin=dict(t=0, b=0))
                st.plotly_chart(fig, use_container_width=True)

                # 3. AI 分析
                st.markdown("---")
                with st.chat_message("assistant"):
                    with st.spinner("AI 正在分析..."):
                        full_analysis = get_ai_analysis(code, name, df_tech, df_chip)
                        try:
                            parts = full_analysis.split('\n', 1)
                            header = parts[0].replace('#', '').strip()
                            body = parts[1].strip() if len(parts) > 1 else ""
                            if "買進" in header: st.error(f"### {header}")
                            elif "觀望" in header or "持有" in header: st.warning(f"### {header}")
                            else: st.success(f"### {header}")
                            st.markdown(body)
                        except:
                            st.markdown(full_analysis)
                        
        except Exception as e:
            st.error(f"發生錯誤: {e}")
else:
    st.info("👈 請從左側選擇股票，或輸入代號搜尋。")