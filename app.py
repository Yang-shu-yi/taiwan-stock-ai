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
# 2. 數據獲取與計算
# ==========================================
def get_finmind_data(dataset, code, days=90):
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        parameter = {
            "dataset": dataset,
            "data_id": code,
            "start_date": start_date
        }
        r = requests.get(url, params=parameter, timeout=5)
        data = r.json()
        if data['msg'] == 'success' and data['data']:
            return pd.DataFrame(data['data'])
        return None
    except: return None

def get_chip_data(code):
    df = get_finmind_data("TaiwanStockInstitutionalInvestorBuySell", code, days=60)
    if df is not None:
        df['name'] = df['name'].map({
            'Foreign_Investor': '外資', 'Investment_Trust': '投信',
            'Dealer_Self': '自營商(自行)', 'Dealer_Hedging': '自營商(避險)'
        })
        df['date'] = pd.to_datetime(df['date'])
        return df.pivot_table(index='date', columns='name', values='buy_sell', aggfunc='sum').fillna(0)
    return None

def get_fundamental_data(code, ticker):
    data = {"pe": 0, "pb": 0, "yield": 0, "source": "None"}
    # 1. FinMind
    df = get_finmind_data("TaiwanStockPER", code, days=90)
    if df is not None and not df.empty:
        latest = df.iloc[-1]
        data["pe"] = latest.get('PER', 0)
        data["pb"] = latest.get('PBR', 0)
        data["yield"] = latest.get('dividend_yield', 0)
        data["source"] = "FinMind"
    # 2. Yahoo Fallback
    if data["pe"] == 0 and data["yield"] == 0:
        try:
            info = ticker.info
            data["pe"] = info.get('trailingPE', 0)
            data["pb"] = info.get('priceToBook', 0)
            y_val = info.get('dividendYield', 0)
            data["yield"] = y_val * 100 if y_val else 0
            data["source"] = "Yahoo"
        except: pass
    return data

def calculate_technicals(df):
    """🔥 新增：計算 KD, MACD, RSI"""
    close = df['Close']
    
    # RSI
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]
    
    # MACD
    macd = ta.trend.MACD(close)
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]
    macd_hist = macd.macd_diff().iloc[-1] # 柱狀圖 (正=多頭增強, 負=空頭)
    
    # KD (Stochastic)
    stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], close, window=9, smooth_window=3)
    k = stoch.stoch().iloc[-1]
    d = stoch.stoch_signal().iloc[-1]
    
    # MA
    ma20 = ta.trend.sma_indicator(close, 20).iloc[-1]
    ma60 = ta.trend.sma_indicator(close, 60).iloc[-1]
    
    return {
        "RSI": rsi,
        "MACD_Hist": macd_hist,
        "K": k,
        "D": d,
        "MA20": ma20,
        "MA60": ma60,
        "Trend": "多頭" if close.iloc[-1] > ma60 else "空頭"
    }

# ==========================================
# 3. 量化評分 (加入動能權重)
# ==========================================
def calculate_quant_score(df_tech, df_chip, fundamentals, techs):
    scores = {}
    
    # 1. 技術面 (加入 KD/MACD 判斷)
    tech_score = 50
    if techs['Trend'] == "多頭": tech_score += 10
    if techs['MACD_Hist'] > 0: tech_score += 10 # 動能向上
    if techs['K'] > techs['D']: tech_score += 10 # 黃金交叉狀態
    if techs['RSI'] > 80: tech_score -= 10 # 過熱
    elif techs['RSI'] < 20: tech_score += 10 # 超賣反彈機會
    scores['技術'] = min(max(tech_score, 0), 100)

    # 2. 籌碼面
    chip_score = 50
    if df_chip is not None:
        try:
            f = df_chip['外資'].tail(5).sum() if '外資' in df_chip else 0
            t = df_chip['投信'].tail(5).sum() if '投信' in df_chip else 0
            if t > 0: chip_score += 20
            if f < -5000: chip_score -= 20
            elif f > 0: chip_score += 10
        except: pass
    scores['籌碼'] = min(max(chip_score, 0), 100)

    # 3. 價值面 (更嚴格)
    val_score = 50
    pe = fundamentals['pe']
    pb = fundamentals['pb']
    
    if pb > 0 and pb < 1.0: val_score += 20
    if pe > 0 and pe < 15: val_score += 20
    
    # 🔥 價值陷阱扣分：如果便宜但趨勢是空頭，分數要打折
    if techs['Trend'] == "空頭" and val_score > 60:
        val_score -= 20 
        
    scores['價值'] = min(max(val_score, 0), 100)
    
    # 4. 股息
    dy = fundamentals['yield']
    scores['股息'] = min(max(50 + (dy - 3)*10, 0), 100) if dy else 50

    return scores

# ==========================================
# 4. AI 分析 (注入靈魂)
# ==========================================
def get_ai_analysis(code, name, price, techs, quant, fund, chip_msg):
    if not GROQ_API_KEY: return "⚠️ 請設定 API Key"
    
    # 轉換技術指標為白話文
    kd_status = "黃金交叉(偏多)" if techs['K'] > techs['D'] else "死亡交叉(偏空)"
    macd_status = "紅柱(動能強)" if techs['MACD_Hist'] > 0 else "綠柱(動能弱)"
    ma_status = "站上季線(長多)" if price > techs['MA60'] else "跌破季線(長空)"
    
    prompt = f"""
    角色：嚴格的避險基金操盤手。分析 {name} ({code})。
    目標：不要只看價值，要看「動能」與「陷阱」。
    
    【市場數據】
    - 股價: {price:.2f}
    - 趨勢: {ma_status}
    - KD指標: K={techs['K']:.1f}, D={techs['D']:.1f} -> {kd_status}
    - MACD動能: {macd_status}
    - RSI: {techs['RSI']:.1f}
    
    【基本面估值】
    - PE: {fund['pe']:.1f}倍 / PB: {fund['pb']:.2f}倍 / 殖利率: {fund['yield']:.1f}%
    - 警告：若趨勢為空頭且 PB < 1，可能是「價值陷阱」，請勿盲目推薦買進。
    
    【籌碼】{chip_msg}
    
    請依照 Markdown 輸出：
    # 決策：[強力買進 / 拉回布局 / 觀望 / 反彈減碼 / 放空] (請選最嚴格的一個)
    
    ### ⚔️ 技術動能判讀 (最重要)
    * **KD 與 MACD 解析**：(解讀目前的動能是增強還是減弱？KD 是金叉還是死叉？)
    * **趨勢確認**：(確認股價與季線 MA60 的關係，這是多空分水嶺)。
    
    ### 🏢 估值陷阱檢測
    * (若 PB 低但技術面弱，請直言「可能是價值陷阱，不宜過早接刀」)。
    * (若基本面佳且技術面轉強，才可稱為「價值浮現」)。
    
    ### 💡 實戰操作策略
    * **關鍵點位**：(給出支撐與壓力)。
    * **進場條件**：(例如：需等待 MACD 翻紅，或站回月線才可進場)。
    """
    
    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=850
        )
        return completion.choices[0].message.content
    except Exception as e: return f"Error: {e}"

# ==========================================
# 5. 主程式
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

if 'current_stock' not in st.session_state: st.session_state['current_stock'] = None

st.sidebar.title("📂 戰情室")
q = st.sidebar.text_input("搜尋代號/名稱")
if st.sidebar.button("🚀 分析") and q:
    c, _, _ = resolve_stock_code(q)
    if c: st.session_state['current_stock'] = c

st.title("📈 台股 AI 戰情室 (v7.0 動能戰術版)")

target = st.session_state['current_stock']

if target:
    code, suffix, name = resolve_stock_code(target)
    if code:
        try:
            ticker = yf.Ticker(f"{code}{suffix}")
            df_tech = ticker.history(period="6mo")
            
            if len(df_tech) < 20:
                st.error("❌ 資料不足")
            else:
                # 計算
                df_chip = get_chip_data(code)
                fund = get_fundamental_data(code, ticker)
                techs = calculate_technicals(df_tech) # 🔥 算出 KD, MACD
                quant = calculate_quant_score(df_tech, df_chip, fund, techs)
                
                # 準備 AI 訊息
                chip_msg = "籌碼中性"
                if df_chip is not None:
                    f = df_chip['外資'].tail(5).sum() if '外資' in df_chip else 0
                    t = df_chip['投信'].tail(5).sum() if '投信' in df_chip else 0
                    chip_msg = f"近5日外資{int(f/1000)}張/投信{int(t/1000)}張"

                # UI 顯示
                latest = df_tech['Close'].iloc[-1]
                chg = latest - df_tech['Close'].iloc[-2]
                color = "#ff2b2b" if chg > 0 else "#2dc937"
                
                st.markdown(f"## {name} ({code})")
                c1, c2, c3, c4 = st.columns(4)
                c1.markdown(f"#### 股價\n<h2 style='color:{color}'>${latest:.2f}</h2>", unsafe_allow_html=True)
                c2.markdown(f"#### KD指標\n### K{techs['K']:.0f} / D{techs['D']:.0f}")
                c3.markdown(f"#### MACD\n### {'🟥翻紅' if techs['MACD_Hist']>0 else '🟩翻黑'}")
                c4.markdown(f"#### 總分\n<h2 style='color:orange'>{int(sum(quant.values())/4)}</h2>", unsafe_allow_html=True)
                
                st.markdown("---")
                
                # 圖表
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                df_tech['MA20'] = techs['MA20']
                df_tech['MA60'] = techs['MA60']
                
                fig.add_trace(go.Candlestick(x=df_tech.index, open=df_tech['Open'], high=df_tech['High'], low=df_tech['Low'], close=df_tech['Close'], name="K線"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_tech.index, y=df_tech['MA60'], line=dict(color='green', width=1), name="季線"), row=1, col=1)
                
                # 下方改畫 MACD 或是 籌碼
                if df_chip is not None:
                    df_chip = df_chip.reindex(df_tech.index).fillna(0)
                    fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['投信'], marker_color='red', name='投信'), row=2, col=1)
                
                st.plotly_chart(fig, use_container_width=True)
                
                # AI
                with st.chat_message("assistant"):
                    with st.spinner("AI 正在進行多空動能審查..."):
                        analysis = get_ai_analysis(code, name, latest, techs, quant, fund, chip_msg)
                        
                        # 標題變色邏輯
                        parts = analysis.split('\n', 1)
                        header = parts[0].replace('#', '').strip()
                        body = parts[1] if len(parts)>1 else ""
                        
                        if "買進" in header: st.error(f"### {header}")
                        elif "放空" in header or "減碼" in header: st.success(f"### {header}") # 綠色
                        else: st.warning(f"### {header}") # 黃色觀望
                        
                        st.markdown(body)

        except Exception as e: st.error(f"Err: {e}")