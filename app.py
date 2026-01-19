import streamlit as st
import yfinance as yf
import pandas as pd
import twstock
import ta
import json
import os
import requests  # 👈 用這個輕量套件取代 FinMind
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
    """
    使用 Requests 直接呼叫 FinMind API，不需安裝套件
    """
    try:
        # 設定 API 網址
        url = "https://api.finmindtrade.com/api/v4/data"
        
        # 設定抓取範圍 (過去 40 天，確保有足夠的 K 線對應)
        start_date = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')
        
        parameter = {
            "dataset": "TaiwanStockInstitutionalInvestorBuySell",
            "data_id": code,
            "start_date": start_date
        }
        
        # 發送請求
        r = requests.get(url, params=parameter)
        data = r.json()
        
        if data['msg'] != 'success' or not data['data']:
            return None, "無籌碼資料"
            
        # 轉成 DataFrame
        df = pd.DataFrame(data['data'])
        
        # 資料整理：將三大法人轉成 Columns
        df['name'] = df['name'].map({
            'Foreign_Investor': '外資',
            'Investment_Trust': '投信',
            'Dealer_Self': '自營商(自行)',
            'Dealer_Hedging': '自營商(避險)'
        })
        
        # 只留需要的欄位並轉置
        # Pivot table: Index=date, Columns=name, Values=buy_sell
        df['date'] = pd.to_datetime(df['date'])
        df_pivot = df.pivot_table(index='date', columns='name', values='buy_sell', aggfunc='sum').fillna(0)
        
        return df_pivot, "Success"
        
    except Exception as e:
        return None, f"API 連線錯誤: {str(e)}"

# ==========================================
# 3. 其他功能函數
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
    
    # 準備技術數據
    close = df_tech['Close']
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]
    ma20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
    price = close.iloc[-1]
    
    # 準備籌碼數據
    chip_msg = "無籌碼數據 (可能為剛上市或資料源延遲)"
    if df_chip is not None:
        # 取得最近 5 筆資料 (因為 API 可能有空值，要小心處理)
        try:
            foreign_5d = df_chip['外資'].tail(5).sum() if '外資' in df_chip.columns else 0
            trust_5d = df_chip['投信'].tail(5).sum() if '投信' in df_chip.columns else 0
            chip_msg = f"近5日外資累計買賣超 {int(foreign_5d/1000)} 張，投信累計買賣超 {int(trust_5d/1000)} 張"
        except:
            pass

    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"""
    你是一位專業操盤手。分析 {name} ({code})。
    【技術面】
    - 現價: {price:.2f}
    - MA20: {ma20:.2f}
    - RSI: {rsi:.1f}
    【籌碼面 (關鍵數據)】
    - {chip_msg}
    (判讀邏輯：投信連續買超為強勢訊號，外資大賣需警覺)

    請嚴格依照格式輸出 (不要廢話)：
    # 建議：[強力買進 / 拉回買進 / 觀望 / 減碼]
    ### 📈 技術分析
    * ...
    ### ⚖️ 籌碼透視
    * (請根據上面的外資/投信數據，分析主力心態)
    ### 💡 操作建議
    * ...
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=600
        )
        return completion.choices[0].message.content
    except Exception as e: return f"AI Error: {e}"

# ==========================================
# 4. 初始化
# ==========================================
if 'current_stock' not in st.session_state:
    st.session_state['current_stock'] = None

# ==========================================
# 5. 側邊欄
# ==========================================
st.sidebar.title("📂 戰情室資料庫")
if st.sidebar.button("🔄 重新讀取"): st.rerun()

db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    if db: st.sidebar.caption(f"上次更新: {next(iter(db.values())).get('update_time', '未知')}")
except: st.sidebar.warning("資料庫為空")

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
    
    st.markdown("---")
    q = st.text_input("搜尋代號/名稱", label_visibility="collapsed")
    if st.button("🚀 分析", type="primary", use_container_width=True) and q:
        c, _, _ = resolve_stock_code(q)
        if c: st.session_state['current_stock'] = c

# ==========================================
# 6. 主畫面
# ==========================================
st.title("📈 台股 AI 戰情室 (API 輕量版)")

target = st.session_state['current_stock']

if target:
    code, suffix, name = resolve_stock_code(target)
    
    if code:
        try:
            # 1. 抓股價 (Yahoo)
            ticker = yf.Ticker(f"{code}{suffix}")
            df_tech = ticker.history(period="6mo")
            
            # 2. 抓籌碼 (API)
            df_chip, chip_status = get_chip_data(code)
            
            if len(df_tech) < 5:
                st.error("資料不足")
            else:
                # 顯示標題
                latest = df_tech['Close'].iloc[-1]
                pct = (latest - df_tech['Close'].iloc[-2]) / df_tech['Close'].iloc[-2] * 100
                color = "red" if pct > 0 else "green"
                st.markdown(f"## {name} ({code})")
                st.markdown(f"### <span style='color:{color}'>${latest:.2f} ({pct:+.2f}%)</span>", unsafe_allow_html=True)

                # 3. 繪製雙圖表
                df_tech['MA20'] = ta.trend.sma_indicator(df_tech['Close'], 20)
                df_tech['MA60'] = ta.trend.sma_indicator(df_tech['Close'], 60)
                
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                    vertical_spacing=0.05, row_heights=[0.7, 0.3],
                                    subplot_titles=("股價走勢", "法人籌碼動向"))

                # 上圖：K線
                fig.add_trace(go.Candlestick(x=df_tech.index, open=df_tech['Open'], high=df_tech['High'], 
                                             low=df_tech['Low'], close=df_tech['Close'], name="K線"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_tech.index, y=df_tech['MA20'], line=dict(color='orange', width=1), name="月線"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_tech.index, y=df_tech['MA60'], line=dict(color='green', width=1), name="季線"), row=1, col=1)

                # 下圖：籌碼 (API 資料)
                if df_chip is not None and not df_chip.empty:
                    # 轉換索引為 datetime 格式以對齊
                    df_chip.index = pd.to_datetime(df_chip.index)
                    
                    fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['外資'], name="外資", marker_color='blue'), row=2, col=1)
                    fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['投信'], name="投信", marker_color='red'), row=2, col=1)
                else:
                    fig.add_annotation(text="無籌碼資料 (FinMind API)", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, row=2, col=1)

                fig.update_layout(xaxis_rangeslider_visible=False, height=600, margin=dict(t=0, b=0))
                st.plotly_chart(fig, use_container_width=True)

                # 4. AI 分析
                st.markdown("---")
                with st.chat_message("assistant"):
                    with st.spinner("AI 正在解讀法人籌碼..."):
                        full_analysis = get_ai_analysis(code, name, df_tech, df_chip)
                        try:
                            parts = full_analysis.split('\n', 1)
                            header = parts[0].replace('#', '').strip()
                            body = parts[1].strip() if len(parts) > 1 else ""
                            if "買進" in header: st.error(f"### {header}")
                            elif "觀望" in header: st.warning(f"### {header}")
                            else: st.success(f"### {header}")
                            st.markdown(body)
                        except: st.markdown(full_analysis)
                        
        except Exception as e: st.error(f"Error: {e}")
else:
    st.info("👈 請選擇股票")