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
# 2. 數據獲取
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
    except:
        return None

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
    """抓取 PE (本益比), PB (股價淨值比), Yield (殖利率)"""
    data = {
        "pe_ratio": 0,
        "pb_ratio": 0,
        "yield": 0,
        "source": "None"
    }

    # 1. FinMind
    df = get_finmind_data("TaiwanStockPER", code, days=90)
    if df is not None and not df.empty:
        latest = df.iloc[-1]
        data["pe_ratio"] = latest.get('PER', 0)
        data["pb_ratio"] = latest.get('PBR', 0)
        data["yield"] = latest.get('dividend_yield', 0)
        data["source"] = "FinMind"

    # 2. Yahoo Fallback
    if data["pe_ratio"] == 0 and data["yield"] == 0:
        try:
            info = ticker.info
            data["pe_ratio"] = info.get('trailingPE', 0)
            data["pb_ratio"] = info.get('priceToBook', 0)
            y_val = info.get('dividendYield', 0)
            data["yield"] = y_val * 100 if y_val else 0
            data["source"] = "Yahoo"
        except: pass
            
    return data

# ==========================================
# 3. 量化評分引擎 (加入 PBR 權重)
# ==========================================
def calculate_quant_score(df_tech, df_chip, fundamentals):
    scores = {}
    
    # 1. 技術面
    close = df_tech['Close']
    ma20 = ta.trend.sma_indicator(close, 20).iloc[-1]
    ma60 = ta.trend.sma_indicator(close, 60).iloc[-1]
    rsi = ta.momentum.rsi(close, 14).iloc[-1]
    
    tech_score = 50 
    if close.iloc[-1] > ma20: tech_score += 15
    if ma20 > ma60: tech_score += 15
    if 50 < rsi < 75: tech_score += 20 
    elif rsi >= 75: tech_score += 10
    elif rsi < 30: tech_score -= 10
    scores['技術'] = min(max(tech_score, 0), 100)

    # 2. 籌碼面
    chip_score = 50
    if df_chip is not None:
        try:
            f_sum = df_chip['外資'].tail(5).sum() if '外資' in df_chip else 0
            t_sum = df_chip['投信'].tail(5).sum() if '投信' in df_chip else 0
            if f_sum > 0: chip_score += 10
            if t_sum > 0: chip_score += 20
            if t_sum > 1000: chip_score += 10
            if f_sum < -5000: chip_score -= 20
        except: pass
    scores['籌碼'] = min(max(chip_score, 0), 100)

    # 3. 價值面 (PE & PBR)
    val_score = 50
    pe = fundamentals.get('pe_ratio', 0)
    pbr = fundamentals.get('pb_ratio', 0)
    
    # PE 評分
    if pe > 0:
        if pe < 12: val_score += 20
        elif pe > 30: val_score -= 10
    
    # PBR 評分 (這裡很重要，尤其是景氣循環股)
    if pbr > 0:
        if pbr < 0.8: val_score += 30   # 股價低於淨值很多 -> 極便宜
        elif pbr < 1.0: val_score += 20 # 股價低於淨值 -> 便宜
        elif pbr > 4.0: val_score -= 10 # 太貴
        
    scores['價值'] = min(max(val_score, 0), 100)

    # 4. 股息面
    div_score = 50
    dy = fundamentals.get('yield', 0) 
    if dy > 5: div_score += 30
    elif dy > 3: div_score += 10
    elif dy < 1: div_score -= 10
    scores['股息'] = min(max(div_score, 0), 100)
    
    return scores

# ==========================================
# 4. 輔助函數
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

def get_ai_analysis(code, name, df_tech, df_chip, quant_scores, fundamentals):
    if not GROQ_API_KEY: return "⚠️ 請先設定 GROQ_API_KEY"
    
    price = df_tech['Close'].iloc[-1]
    
    # 籌碼摘要
    chip_msg = "籌碼數據不明(需持續追蹤)"
    if df_chip is not None:
        f = df_chip['外資'].tail(5).sum() if '外資' in df_chip else 0
        t = df_chip['投信'].tail(5).sum() if '投信' in df_chip else 0
        chip_msg = f"近5日外資{int(f/1000)}張 / 投信{int(t/1000)}張"

    # 基本面摘要
    pe = fundamentals.get('pe_ratio', 0)
    pbr = fundamentals.get('pb_ratio', 0)
    dy = fundamentals.get('yield', 0)
    
    pe_str = f"{pe:.1f}倍" if pe > 0 else "N/A"
    pbr_str = f"{pbr:.2f}倍" if pbr > 0 else "N/A"
    dy_str = f"{dy:.1f}%"

    client = Groq(api_key=GROQ_API_KEY)
    
    # 🔥 重構 Prompt：強調「盤後策略」與「產業邏輯」
    prompt = f"""
    你是一位專業的「盤後策略分析師」。請分析 {name} ({code})。
    這是一份「盤後分析報告」，請不要提供盤中即時建議，而是提供明日或波段的策略思維。

    【基本數據】
    - 股價: {price:.2f}
    - 本益比 (PE): {pe_str}
    - 股價淨值比 (PBR): {pbr_str} (若 < 1 代表股價低於淨值)
    - 殖利率: {dy_str}
    
    【籌碼數據】
    - {chip_msg}
    - 若籌碼不明，請強調「需等待法人動向確認」，不可盲目進場。

    【量化評分】技術{quant_scores['技術']}/籌碼{quant_scores['籌碼']}/價值{quant_scores['價值']}/股息{quant_scores['股息']} (滿分100)
    
    請嚴格依照 Markdown 格式輸出：

    # 策略觀點：[價值低估 / 順勢操作 / 區間震盪 / 風險規避] (請選一個)

    ### 🏢 基本面與估值 (關鍵)
    * **PBR 與 PE 解讀**：(若 PBR < 1，請提及股價低於淨值，可能具價值支撐，但需留意產業景氣是否低迷)。
    * **殖利率評估**：(分析配息是否具備長線保護短線的效果)。
    * **產業視角**：(請運用你對該股產業的知識，例如水泥、半導體、航運的景氣循環，配合數據解讀)。

    ### ⚖️ 技術與籌碼現況
    * **趨勢判斷**：(若技術指標無明顯方向，請直說「方向不明」或「盤整」，不要硬找理由)。
    * **籌碼驗證**：(強調技術面需搭配籌碼驗證，若籌碼不明則視為風險)。

    ### 💡 盤後操作策略
    * **長線思維**：(針對價值投資者的建議)。
    * **短線應對**：(針對技術面操作的關鍵價位)。
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=800
        )
        return completion.choices[0].message.content
    except Exception as e: return f"AI Error: {e}"

# ==========================================
# 5. UI 初始化
# ==========================================
if 'current_stock' not in st.session_state:
    st.session_state['current_stock'] = None

st.sidebar.title("📂 戰情室資料庫")
if st.sidebar.button("🔄 重新讀取"): st.rerun()

db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    if db: st.sidebar.caption(f"上次更新: {next(iter(db.values())).get('update_time', '未知')}")
except: pass

red = [v for k,v in db.items() if v.get('status') == 'RED']
green = [v for k,v in db.items() if v.get('status') == 'GREEN']
yellow = [v for k,v in db.items() if v.get('status') == 'YELLOW']

with st.sidebar:
    with st.expander(f"🔴 強力關注 ({len(red)})", expanded=True):
        for i in red:
            if st.button(f"{i['code']} {i['name']} ${i['price']}", key=f"r_{i['code']}"): st.session_state['current_stock'] = i['code']
    with st.expander(f"🟢 避雷區 ({len(green)})"):
        for i in green:
            if st.button(f"{i['code']} {i['name']}", key=f"g_{i['code']}"): st.session_state['current_stock'] = i['code']
    with st.expander(f"🟡 觀望區 ({len(yellow)})"):
        for i in yellow:
            if st.button(f"{i['code']} {i['name']}", key=f"y_{i['code']}"): st.session_state['current_stock'] = i['code']
    
    st.markdown("---")
    q = st.text_input("搜尋代號/名稱", label_visibility="collapsed")
    if st.button("🚀 分析", type="primary", use_container_width=True) and q:
        c, _, _ = resolve_stock_code(q)
        if c: st.session_state['current_stock'] = c

# ==========================================
# 6. 主畫面 UI
# ==========================================
st.title("📈 台股 AI 戰情室 (策略版)")

target = st.session_state['current_stock']

if target:
    code, suffix, name = resolve_stock_code(target)
    
    if code:
        try:
            ticker = yf.Ticker(f"{code}{suffix}")
            df_tech = ticker.history(period="6mo")
            df_chip = get_chip_data(code)
            fundamentals = get_fundamental_data(code, ticker) 
            
            if len(df_tech) < 5:
                st.error("❌ 無法取得數據")
            else:
                quant_scores = calculate_quant_score(df_tech, df_chip, fundamentals)
                
                latest = df_tech['Close'].iloc[-1]
                change = latest - df_tech['Close'].iloc[-2]
                color = "#ff2b2b" if change > 0 else "#2dc937"
                
                st.markdown(f"## {name} ({code})")
                
                # 🔥 新增 PBR 顯示欄位
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.markdown("##### 股價")
                    st.markdown(f"<h3 style='color:{color}'>${latest:.2f}</h3>", unsafe_allow_html=True)
                with col2:
                    st.markdown("##### 本益比 (PE)")
                    pe = fundamentals.get('pe_ratio', 0)
                    st.markdown(f"### {pe:.1f}" if pe > 0 else "### -")
                with col3:
                    st.markdown("##### 股價淨值比 (PB)") # 新增
                    pbr = fundamentals.get('pb_ratio', 0)
                    st.markdown(f"### {pbr:.2f}" if pbr > 0 else "### -")
                with col4:
                    st.markdown("##### 殖利率")
                    dy = fundamentals.get('yield', 0)
                    st.markdown(f"### {dy:.1f}%" if dy > 0 else "-")
                with col5:
                    st.markdown("##### 量化總分")
                    avg_score = sum(quant_scores.values()) / len(quant_scores)
                    score_color = "#ff2b2b" if avg_score > 70 else "orange"
                    st.markdown(f"<h3 style='color:{score_color}'>{int(avg_score)}</h3>", unsafe_allow_html=True)

                st.markdown("---")

                chart_col, radar_col = st.columns([2, 1])
                
                with chart_col:
                    st.subheader("📊 技術與籌碼")
                    has_chip = (df_chip is not None and not df_chip.empty)
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                    
                    df_tech['MA20'] = ta.trend.sma_indicator(df_tech['Close'], 20)
                    fig.add_trace(go.Candlestick(x=df_tech.index, open=df_tech['Open'], high=df_tech['High'], 
                                                 low=df_tech['Low'], close=df_tech['Close'], name="K線"), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df_tech.index, y=df_tech['MA20'], line=dict(color='orange', width=1), name="MA20"), row=1, col=1)
                    
                    if has_chip:
                        df_chip = df_chip.reindex(df_tech.index).fillna(0)
                        fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['外資'], name="外資", marker_color='blue'), row=2, col=1)
                        fig.add_trace(go.Bar(x=df_chip.index, y=df_chip['投信'], name="投信", marker_color='red'), row=2, col=1)
                    
                    fig.update_layout(xaxis_rangeslider_visible=False, height=500, margin=dict(t=0, b=0, l=0, r=0))
                    st.plotly_chart(fig, use_container_width=True)

                with radar_col:
                    st.subheader("🕸️ 策略雷達")
                    categories = list(quant_scores.keys())
                    values = list(quant_scores.values())
                    fig_radar = go.Figure()
                    fig_radar.add_trace(go.Scatterpolar(
                        r=values, theta=categories, fill='toself', name=name,
                        line=dict(color='#ff2b2b' if avg_score > 65 else '#2dc937')
                    ))
                    fig_radar.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                        showlegend=False, height=400, margin=dict(t=20, b=20, l=30, r=30)
                    )
                    st.plotly_chart(fig_radar, use_container_width=True)

                st.markdown("---")
                with st.chat_message("assistant"):
                    with st.spinner("AI 策略分析師正在撰寫報告..."):
                        full_analysis = get_ai_analysis(code, name, df_tech, df_chip, quant_scores, fundamentals)
                        try:
                            parts = full_analysis.split('\n', 1)
                            header = parts[0].replace('#', '').strip()
                            body = parts[1].strip() if len(parts) > 1 else ""
                            if "順勢" in header: st.error(f"### {header}")
                            elif "價值" in header: st.info(f"### {header}") # 價值投資用藍色/綠色
                            else: st.warning(f"### {header}")
                            st.markdown(body)
                        except: st.markdown(full_analysis)
                        
        except Exception as e: st.error(f"發生錯誤: {e}")
else:
    st.info("👈 請選擇股票")