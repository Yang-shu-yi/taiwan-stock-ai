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
from news_scraper import fetch_all_news
from market_data import get_all_market_data
from report_generator import generate_report

try:
    import gspread
except Exception:
    gspread = None

# ==========================================
# 1. 設定與金鑰
# ==========================================
st.set_page_config(page_title="台股 AI 戰情室", layout="wide", page_icon="📈")
try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

try:
    WATCHLIST_SPREADSHEET_ID = st.secrets["WATCHLIST_SPREADSHEET_ID"]
except:
    WATCHLIST_SPREADSHEET_ID = os.environ.get("WATCHLIST_SPREADSHEET_ID")

try:
    SERVICE_ACCOUNT_INFO = st.secrets["gcp_service_account"]
except:
    SERVICE_ACCOUNT_INFO = None

WATCHLIST_SHEET_NAME = os.environ.get("WATCHLIST_SHEET_NAME", "watchlist")


# ==========================================
# 2. 數據獲取與計算
# ==========================================
def get_finmind_data(dataset, code, days=90):
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        parameter = {"dataset": dataset, "data_id": code, "start_date": start_date}
        r = requests.get(url, params=parameter, timeout=5)
        data = r.json()
        if data["msg"] == "success" and data["data"]:
            return pd.DataFrame(data["data"])
        return None
    except:
        return None


def load_watchlist_from_sheet():
    if not gspread or not WATCHLIST_SPREADSHEET_ID:
        return []
    try:
        if SERVICE_ACCOUNT_INFO:
            gc = gspread.service_account_from_dict(SERVICE_ACCOUNT_INFO)
        else:
            creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
            if not creds_path or not os.path.exists(creds_path):
                return []
            gc = gspread.service_account(filename=creds_path)
        sh = gc.open_by_key(WATCHLIST_SPREADSHEET_ID)
        ws = sh.worksheet(WATCHLIST_SHEET_NAME)
        values = ws.col_values(1)
        return [v.strip() for v in values if v.strip().isdigit()]
    except:
        return []


def get_chip_data(code):
    df = get_finmind_data("TaiwanStockInstitutionalInvestorBuySell", code, days=60)
    if df is not None:
        df["name"] = df["name"].map(
            {
                "Foreign_Investor": "外資",
                "Investment_Trust": "投信",
                "Dealer_Self": "自營商(自行)",
                "Dealer_Hedging": "自營商(避險)",
            }
        )
        df["date"] = pd.to_datetime(df["date"])
        return df.pivot_table(
            index="date", columns="name", values="buy_sell", aggfunc="sum"
        ).fillna(0)
    return None


def get_fundamental_data(code, ticker):
    data = {"pe": 0, "pb": 0, "yield": 0, "source": "None"}
    # 1. FinMind
    df = get_finmind_data("TaiwanStockPER", code, days=90)
    if df is not None and not df.empty:
        latest = df.iloc[-1]
        data["pe"] = latest.get("PER", 0)
        data["pb"] = latest.get("PBR", 0)
        data["yield"] = latest.get("dividend_yield", 0)
        data["source"] = "FinMind"
    # 2. Yahoo Fallback
    if data["pe"] == 0 and data["yield"] == 0:
        try:
            info = ticker.info
            data["pe"] = info.get("trailingPE", 0)
            data["pb"] = info.get("priceToBook", 0)
            y_val = info.get("dividendYield", 0)
            data["yield"] = y_val * 100 if y_val else 0
            data["source"] = "Yahoo"
        except:
            pass
    return data


def calculate_technicals(df):
    """計算 KD, MACD, RSI"""
    close = df["Close"]

    # RSI
    rsi = ta.momentum.rsi(close, window=14).iloc[-1]

    # MACD
    macd = ta.trend.MACD(close)
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]
    macd_hist = macd.macd_diff().iloc[-1]

    # KD
    stoch = ta.momentum.StochasticOscillator(
        df["High"], df["Low"], close, window=9, smooth_window=3
    )
    k = stoch.stoch().iloc[-1]
    d = stoch.stoch_signal().iloc[-1]

    # MA
    ma20 = ta.trend.sma_indicator(close, 20).iloc[-1]
    ma60 = ta.trend.sma_indicator(close, 60).iloc[-1]
    ma5 = ta.trend.sma_indicator(close, 5).iloc[-1]
    ma10 = ta.trend.sma_indicator(close, 10).iloc[-1]

    return {
        "RSI": rsi,
        "MACD_Hist": macd_hist,
        "K": k,
        "D": d,
        "MA20": ma20,
        "MA60": ma60,
        "MA5": ma5,
        "MA10": ma10,
        "Bias5": (close.iloc[-1] - ma5) / ma5 * 100,
        "Bias10": (close.iloc[-1] - ma10) / ma10 * 100,
        "Bias20": (close.iloc[-1] - ma20) / ma20 * 100,
        "Trend": "多頭" if close.iloc[-1] > ma60 else "空頭",
    }


# ==========================================
# 3. 量化評分 (加入動能權重)
# ==========================================
def calculate_quant_score(df_tech, df_chip, fundamentals, techs):
    scores = {}

    # 1. 技術面
    tech_score = 50
    if techs["Trend"] == "多頭":
        tech_score += 10
    if techs["MACD_Hist"] > 0:
        tech_score += 10
    if techs["K"] > techs["D"]:
        tech_score += 10
    if techs["RSI"] > 80:
        tech_score -= 10
    elif techs["RSI"] < 20:
        tech_score += 10
    scores["技術"] = min(max(tech_score, 0), 100)

    # 2. 籌碼面
    chip_score = 50
    if df_chip is not None:
        try:
            f = df_chip["外資"].tail(5).sum() if "外資" in df_chip else 0
            t = df_chip["投信"].tail(5).sum() if "投信" in df_chip else 0
            if t > 0:
                chip_score += 20
            if f < -5000:
                chip_score -= 20
            elif f > 0:
                chip_score += 10
        except:
            pass
    scores["籌碼"] = min(max(chip_score, 0), 100)

    # 3. 價值面 (更嚴格)
    val_score = 50
    pe = fundamentals["pe"]
    pb = fundamentals["pb"]

    if pb > 0 and pb < 1.0:
        val_score += 20
    if pe > 0 and pe < 15:
        val_score += 20
    if techs["Trend"] == "空頭" and val_score > 60:  # 價值陷阱扣分
        val_score -= 20

    scores["價值"] = min(max(val_score, 0), 100)

    # 4. 股息
    dy = fundamentals["yield"]
    scores["股息"] = min(max(50 + (dy - 3) * 10, 0), 100) if dy else 50

    return scores


# ==========================================
# 4. AI 分析 (v7.0 戰術動能版)
# ==========================================
def get_ai_analysis(code, name, price, techs, quant, fund, chip_msg):
    if not GROQ_API_KEY:
        return "⚠️ 請設定 API Key"

    kd_status = "黃金交叉(偏多)" if techs["K"] > techs["D"] else "死亡交叉(偏空)"
    macd_status = "紅柱(動能強)" if techs["MACD_Hist"] > 0 else "綠柱(動能弱)"
    ma_status = "站上季線(長多)" if price > techs["MA60"] else "跌破季線(長空)"

    prompt = f"""
    角色：嚴格的避險基金操盤手。分析 {name} ({code})。
    目標：不要只看價值，要看「動能」與「陷阱」。

    【市場數據】
    - 股價: {price:.2f}
    - 趨勢: {ma_status}
    - KD指標: K={techs["K"]:.1f}, D={techs["D"]:.1f} -> {kd_status}
    - MACD動能: {macd_status}
    - RSI: {techs["RSI"]:.1f}

    【基本面估值】
    - PE: {fund["pe"]:.1f}倍 / PB: {fund["pb"]:.2f}倍 / 殖利率: {fund["yield"]:.1f}%
    - 警告：若趨勢為空頭且 PB < 1，可能是「價值陷阱」，請勿盲目推薦買進。

    【籌碼】{chip_msg}

    請依照 Markdown 輸出：
    # 決策：[強力買進 / 拉回布局 / 觀望 / 反彈減碼 / 放空] (請選最嚴格的一個)

    ### ⚔️ 技術動能判讀 (最重要)
    * **KD 與 MACD 解析**：(解讀目前的動能是增強還是減弱？)
    * **趨勢確認**：(確認股價與季線 MA60 的關係)。

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
            temperature=0.3,
            max_tokens=850,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"


# ==========================================
# 5. 主程式 (UI 回歸版)
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


if "current_stock" not in st.session_state:
    st.session_state["current_stock"] = None

for key in ["market_data", "news_tw", "news_us", "daily_report", "daily_report_time"]:
    if key not in st.session_state:
        st.session_state[key] = None

# --- 🟢 這裡把側邊欄邏輯找回來了！ ---
st.sidebar.title("📂 戰情室資料庫")
if st.sidebar.button("🔄 重新讀取"):
    st.rerun()

db = {}
try:
    with open("stock_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)
    if db:
        st.sidebar.caption(
            f"上次更新: {next(iter(db.values())).get('update_time', '未知')}"
        )
except:
    st.sidebar.warning("尚未讀取到資料庫 (請等待 GitHub Actions 執行)")

watchlist_codes = load_watchlist_from_sheet()
if not watchlist_codes:
    if os.path.exists("watchlist.json"):
        try:
            with open("watchlist.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                watchlist_codes = [c for c in data if isinstance(c, str)]
        except:
            watchlist_codes = []
if not watchlist_codes:
    env_watchlist = os.environ.get("WATCHLIST_CODES", "")
    if env_watchlist.strip():
        watchlist_codes = [c.strip() for c in env_watchlist.split(",") if c.strip()]

red_list = [v for k, v in db.items() if v.get("status") == "RED"]
green_list = [v for k, v in db.items() if v.get("status") == "GREEN"]
yellow_list = [v for k, v in db.items() if v.get("status") == "YELLOW"]

red_top = sorted(red_list, key=lambda x: x.get("pct_change", 0), reverse=True)[:10]
green_top = sorted(green_list, key=lambda x: x.get("pct_change", 0))[:10]

with st.sidebar:
    with st.expander("🔴 強勢 Top10", expanded=True):
        for item in red_top:
            # 這裡用 pct_change 防呆
            c = item.get("pct_change", 0)
            if st.button(
                f"{item['code']} {item['name']} ${item['price']} ({c}%)",
                key=f"r_{item['code']}",
            ):
                st.session_state["current_stock"] = item["code"]

    with st.expander("🟢 弱勢 Top10"):
        for item in green_top:
            if st.button(f"{item['code']} {item['name']}", key=f"g_{item['code']}"):
                st.session_state["current_stock"] = item["code"]

    with st.expander("🟡 監控中"):
        if not watchlist_codes:
            st.caption("尚未設定監控清單")
        for code in watchlist_codes:
            item = db.get(code)
            label = f"{code}"
            if item:
                label = f"{item['code']} {item['name']} ${item['price']}"
            elif code in twstock.codes:
                label = f"{code} {twstock.codes[code].name}"
            if st.button(label, key=f"w_{code}"):
                st.session_state["current_stock"] = code

    st.markdown("---")
    # 搜尋框放在選單下面
    q = st.text_input("搜尋代號/名稱", label_visibility="collapsed")
    if st.button("🚀 AI 深度分析", type="primary", use_container_width=True) and q:
        c, _, _ = resolve_stock_code(q)
        if c:
            st.session_state["current_stock"] = c

st.sidebar.markdown("---")
st.sidebar.caption("v8.0 | 模組化架構")


@st.cache_data(ttl=600)
def get_latest_news_cached():
    return fetch_all_news(max_per_source=5, fetch_content=False)


def _to_float(val):
    try:
        return float(str(val).replace("+", "").replace("%", "").replace(",", ""))
    except Exception:
        return None


st.title("📈 台股 AI 戰情室 (v8.0)")
tab1, tab2, tab3 = st.tabs(["🌐 市場總覽", "📋 每日報告", "📈 個股分析"])

with tab1:
    st.subheader("🌐 市場總覽")
    current_hour = datetime.now().hour
    mode = "POST" if current_hour >= 14 else "PRE"

    if st.button("🔄 更新數據", key="refresh_market_data"):
        with st.spinner("更新市場與新聞資料中..."):
            st.session_state["market_data"] = get_all_market_data(mode)
            tw_news, us_news = get_latest_news_cached()
            st.session_state["news_tw"] = tw_news
            st.session_state["news_us"] = us_news

    if st.session_state.get("market_data") is None:
        st.session_state["market_data"] = get_all_market_data(mode)

    if (
        st.session_state.get("news_tw") is None
        or st.session_state.get("news_us") is None
    ):
        tw_news, us_news = get_latest_news_cached()
        st.session_state["news_tw"] = tw_news
        st.session_state["news_us"] = us_news

    market = st.session_state.get("market_data") or {}
    tw_index = market.get("tw_index", {})
    us_indices = market.get("us_indices", {})
    forex = market.get("forex", {})
    institutional = market.get("institutional", {})
    margin = market.get("margin", {})

    m1, m2, m3, m4 = st.columns(4)

    tw_pct = _to_float(tw_index.get("pct", "0"))
    tw_color = "#ff2b2b" if (tw_pct is not None and tw_pct >= 0) else "#2dc937"
    m1.markdown(
        f"台股加權\n<h3 style='color:{tw_color}'>{tw_index.get('price', 'N/A')}</h3>"
        f"<div>漲跌: {tw_index.get('pct', 'N/A')}%</div>"
        f"<div>成交值: {tw_index.get('turnover', 'N/A')}</div>",
        unsafe_allow_html=True,
    )

    m2.metric("USD/TWD", forex.get("rate", "N/A"), forex.get("chg", "N/A"))

    vix_raw = us_indices.get("VIX", {}).get("price", "N/A")
    vix_val = _to_float(vix_raw)
    vix_color = "#ffffff"
    if vix_val is not None and vix_val > 30:
        vix_color = "#ff2b2b"
    elif vix_val is not None and vix_val > 20:
        vix_color = "#ffa500"
    m3.markdown(
        f"VIX\n<h3 style='color:{vix_color}'>{vix_raw}</h3>",
        unsafe_allow_html=True,
    )

    total_inst = institutional.get("total", "待開盤")
    inst_color = "#ff2b2b" if str(total_inst).startswith("+") else "#2dc937"
    if total_inst == "待開盤":
        inst_color = "#ffffff"
    m4.markdown(
        f"三大法人合計\n<h3 style='color:{inst_color}'>{total_inst}</h3>",
        unsafe_allow_html=True,
    )

    st.markdown("---")
    ui1, ui2, ui3, ui4 = st.columns(4)
    ui1.metric(
        "S&P500",
        us_indices.get("S&P500", {}).get("price", "N/A"),
        us_indices.get("S&P500", {}).get("pct", "N/A"),
    )
    ui2.metric(
        "道瓊",
        us_indices.get("道瓊", {}).get("price", "N/A"),
        us_indices.get("道瓊", {}).get("pct", "N/A"),
    )
    ui3.metric(
        "那斯達克",
        us_indices.get("那斯達克", {}).get("price", "N/A"),
        us_indices.get("那斯達克", {}).get("pct", "N/A"),
    )
    ui4.metric(
        "費半",
        us_indices.get("費半", {}).get("price", "N/A"),
        us_indices.get("費半", {}).get("pct", "N/A"),
    )

    st.markdown("---")
    st.caption("🏦 法人明細")
    fi1, fi2, fi3 = st.columns(3)
    fi1.metric("外資", institutional.get("foreign", "待開盤"))
    fi2.metric("投信", institutional.get("trust", "待開盤"))
    fi3.metric("自營商", institutional.get("dealer", "待開盤"))

    st.caption("📊 融資融券")
    mg1, mg2 = st.columns(2)
    mg1.metric("融資餘額", margin.get("margin_buy", "待開盤"))
    mg2.metric("融券餘額", margin.get("short_sell", "待開盤"))

    st.markdown("---")
    st.subheader("📰 最新新聞")
    tw_news = st.session_state.get("news_tw") or []
    us_news = st.session_state.get("news_us") or []

    with st.expander("台股新聞", expanded=True):
        if tw_news:
            for art in tw_news:
                st.markdown(f"• [{art['source']}] {art['title']}")
        else:
            st.caption("目前沒有台股新聞")

    with st.expander("國際新聞", expanded=True):
        if us_news:
            for art in us_news:
                st.markdown(f"• [{art['source']}] {art['title']}")
        else:
            st.caption("目前沒有國際新聞")

with tab2:
    st.subheader("📋 AI 每日報告")
    report_mode = st.radio(
        "報告類型", ["盤前報告 (PRE)", "盤後報告 (POST)"], horizontal=True
    )
    mode = "PRE" if "PRE" in report_mode else "POST"

    if st.button("🤖 生成 AI 報告", type="primary", use_container_width=True):
        with st.spinner("🤖 AI 正在分析市場，請稍候約 30 秒..."):
            tw_news, us_news = fetch_all_news(max_per_source=8, fetch_content=True)
            market = get_all_market_data(mode=mode)
            watchlist = watchlist_codes
            report = generate_report(
                mode, tw_news, us_news, market, watchlist, GROQ_API_KEY, None
            )
            st.session_state["daily_report"] = report
            st.session_state["daily_report_time"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )

    if st.session_state.get("daily_report"):
        st.caption(f"生成時間: {st.session_state.get('daily_report_time', '')}")
        st.text(st.session_state["daily_report"])

with tab3:
    target = st.session_state["current_stock"]

    if target:
        code, suffix, name = resolve_stock_code(target)
        if code:
            try:
                ticker = yf.Ticker(f"{code}{suffix}")
                df_tech = ticker.history(period="6mo")

                if len(df_tech) < 20:
                    st.error("❌ 資料不足")
                else:
                    # 執行 v7.0 的核心計算
                    df_chip = get_chip_data(code)
                    fund = get_fundamental_data(code, ticker)
                    techs = calculate_technicals(df_tech)  # 包含 KD, MACD
                    quant = calculate_quant_score(df_tech, df_chip, fund, techs)

                    # 準備 AI 訊息
                    chip_msg = "籌碼中性"
                    if df_chip is not None:
                        f = df_chip["外資"].tail(5).sum() if "外資" in df_chip else 0
                        t = df_chip["投信"].tail(5).sum() if "投信" in df_chip else 0
                        chip_msg = f"近5日外資{int(f / 1000)}張/投信{int(t / 1000)}張"

                    # UI 顯示
                    latest = df_tech["Close"].iloc[-1]
                    chg = latest - df_tech["Close"].iloc[-2]
                    color = "#ff2b2b" if chg > 0 else "#2dc937"
                    k_val = float(techs["K"])
                    d_val = float(techs["D"])
                    macd_hist_val = float(techs["MACD_Hist"])
                    rsi_val = float(techs["RSI"])

                    st.markdown(f"## {name} ({code})")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.markdown(
                        f"#### 股價\n<h2 style='color:{color}'>${latest:.2f}</h2>",
                        unsafe_allow_html=True,
                    )
                    c2.markdown(f"#### KD指標\n### K{k_val:.0f} / D{d_val:.0f}")
                    c3.markdown(
                        f"#### MACD\n### {'🟥翻紅' if macd_hist_val > 0 else '🟩翻黑'}"
                    )
                    c4.markdown(
                        f"#### 總分\n<h2 style='color:orange'>{int(sum(quant.values()) / 4)}</h2>",
                        unsafe_allow_html=True,
                    )

                    ma5_val = techs["MA5"]
                    ma10_val = techs["MA10"]
                    ma20_val = techs["MA20"]
                    ma60_val = techs["MA60"]
                    if ma5_val > ma10_val > ma20_val > ma60_val:
                        alignment = "🟢 多頭排列"
                    elif ma5_val < ma10_val < ma20_val < ma60_val:
                        alignment = "🔴 空頭排列"
                    else:
                        alignment = "🟡 糾結整理"

                    avg_score = int(sum(quant.values()) / len(quant))
                    if avg_score >= 75:
                        badge = "🟢 偏多操作"
                    elif avg_score >= 50:
                        badge = "🟡 觀望為主"
                    else:
                        badge = "🔴 防禦減碼"

                    d1, d2, d3 = st.columns(3)
                    d1.metric("均線排列", alignment)
                    d2.metric("決策徽章", badge)
                    d3.metric("量化均分", avg_score)

                    st.markdown("---")
                    st.subheader("📐 乖離率分析")
                    bc1, bc2, bc3 = st.columns(3)
                    bias5 = float(techs["Bias5"])
                    bias10 = float(techs["Bias10"])
                    bias20 = float(techs["Bias20"])

                    def bias_color(b):
                        if b > 5:
                            return "#ff2b2b"
                        elif b < -5:
                            return "#2dc937"
                        else:
                            return "#ffa500"

                    bc1.markdown(
                        f"5日乖離\n<h3 style='color:{bias_color(bias5)}'>{bias5:.2f}%</h3>",
                        unsafe_allow_html=True,
                    )
                    bc2.markdown(
                        f"10日乖離\n<h3 style='color:{bias_color(bias10)}'>{bias10:.2f}%</h3>",
                        unsafe_allow_html=True,
                    )
                    bc3.markdown(
                        f"20日乖離\n<h3 style='color:{bias_color(bias20)}'>{bias20:.2f}%</h3>",
                        unsafe_allow_html=True,
                    )
                    if abs(bias5) > 8 or abs(bias10) > 8:
                        st.warning("⚠️ 乖離率過大，注意回歸均值風險！")

                    st.markdown("---")
                    st.subheader("📋 技術面檢查清單")
                    checklist = []
                    price_now = latest
                    checklist.append(
                        ("✅" if price_now > techs["MA20"] else "❌")
                        + " 站上月線 (MA20)"
                    )
                    checklist.append(
                        ("✅" if price_now > techs["MA60"] else "❌")
                        + " 站上季線 (MA60)"
                    )
                    checklist.append(("✅" if k_val > d_val else "❌") + " KD 黃金交叉")
                    checklist.append(
                        ("✅" if macd_hist_val > 0 else "❌") + " MACD 紅柱"
                    )
                    if rsi_val > 80:
                        checklist.append("⚠️ RSI 過熱 (>80)")
                    elif rsi_val < 20:
                        checklist.append("⚠️ RSI 過冷 (<20)")
                    else:
                        checklist.append("✅ RSI 正常範圍")
                    if abs(bias5) > 8:
                        checklist.append("❌ 乖離率過大 (>8%)")
                    else:
                        checklist.append("✅ 乖離率正常")
                    for item in checklist:
                        st.markdown(item)

                    st.markdown("---")

                    # 圖表
                    fig = make_subplots(
                        rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3]
                    )
                    df_tech["MA20"] = techs["MA20"]
                    df_tech["MA60"] = techs["MA60"]

                    fig.add_trace(
                        go.Candlestick(
                            x=df_tech.index,
                            open=df_tech["Open"],
                            high=df_tech["High"],
                            low=df_tech["Low"],
                            close=df_tech["Close"],
                            name="K線",
                        ),
                        row=1,
                        col=1,
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=df_tech.index,
                            y=df_tech["MA60"],
                            line=dict(color="green", width=1),
                            name="季線",
                        ),
                        row=1,
                        col=1,
                    )

                    if df_chip is not None:
                        df_chip = df_chip.reindex(df_tech.index).fillna(0)
                        fig.add_trace(
                            go.Bar(
                                x=df_chip.index,
                                y=df_chip["投信"],
                                marker_color="red",
                                name="投信",
                            ),
                            row=2,
                            col=1,
                        )

                    st.plotly_chart(fig, use_container_width=True)

                    # AI
                    with st.chat_message("assistant"):
                        with st.spinner("AI 正在進行多空動能審查..."):
                            analysis = get_ai_analysis(
                                code, name, latest, techs, quant, fund, chip_msg
                            )

                            parts = analysis.split("\n", 1)
                            header = parts[0].replace("#", "").strip()
                            body = parts[1] if len(parts) > 1 else ""

                            if "買進" in header:
                                st.error(f"### {header}")
                            elif "放空" in header or "減碼" in header:
                                st.success(f"### {header}")
                            else:
                                st.warning(f"### {header}")

                            st.markdown(body)

                    st.markdown("---")
                    st.subheader("📰 相關新聞")
                    all_news = (st.session_state.get("news_tw") or []) + (
                        st.session_state.get("news_us") or []
                    )
                    related = [
                        n for n in all_news if code in n["title"] or name in n["title"]
                    ]
                    if related:
                        for n in related[:5]:
                            st.markdown(f"• [{n['source']}] {n['title']}")
                    else:
                        st.caption("未找到直接相關新聞（請先在「市場總覽」更新新聞）")

            except Exception as e:
                st.error(f"Err: {e}")
    else:
        st.info("請從左側資料庫或搜尋欄選擇個股")
