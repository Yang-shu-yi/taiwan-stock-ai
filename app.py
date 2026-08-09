import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from alert_store import read_recent_alerts
from message_formatter import format_market_report
from signal_tracker import summarize_performance
from stock_analyzer import analyze_tw_stock, search_tw_stocks


SNAPSHOT_FILE = Path(os.getenv("DAILY_CANDIDATES_FILE", "runtime/daily_candidates.json"))
SAMPLE_SNAPSHOT_FILE = Path("tests/fixtures/sample_daily_candidates.json")
ALERTS_FILE = Path(os.getenv("ALERTS_FILE", "alerts.jsonl"))
LOCAL_TZ = ZoneInfo("Asia/Taipei")


st.set_page_config(
    page_title="台股 AI 戰情室",
    page_icon="📈",
    layout="wide",
)


st.markdown(
    """
    <style>
    :root {
        --bg: #f4f1e8;
        --panel: #fffdf8;
        --ink: #000000;
        --muted: #000000;
        --line: rgba(32, 35, 48, 0.10);
        --accent: #d95f43;
        --accent-soft: rgba(217, 95, 67, 0.12);
        --good: #228b5a;
        --bad: #b24343;
        --warn: #b18122;
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(217, 95, 67, 0.09), transparent 28%),
            linear-gradient(180deg, #faf8f2 0%, var(--bg) 100%);
        color: var(--ink);
    }

    .hero {
        background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(250,244,233,0.96));
        border: 1px solid var(--line);
        border-radius: 28px;
        padding: 28px 30px 24px;
        box-shadow: 0 18px 50px rgba(32, 35, 48, 0.08);
        margin-bottom: 20px;
    }

    .hero-title {
        font-size: 3rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        margin: 0;
        color: var(--ink);
    }

    .hero-subtitle {
        margin-top: 8px;
        font-size: 1rem;
        color: var(--muted);
    }

    .pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 18px;
    }

    .pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.86);
        font-size: 0.92rem;
        color: var(--ink);
    }

    .pill-accent {
        background: var(--accent-soft);
        border-color: rgba(217, 95, 67, 0.18);
        color: #000000;
    }

    .section-note {
        color: var(--muted);
        margin-bottom: 10px;
    }

    .theme-card {
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .theme-name {
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--ink);
    }

    .theme-score {
        color: var(--ink);
        font-weight: 700;
        margin-top: 6px;
    }

    .theme-leaders {
        color: var(--muted);
        margin-top: 8px;
        line-height: 1.55;
    }

    .news-card, .alert-card {
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 18px;
        height: 100%;
    }

    .small-title {
        font-size: 0.88rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .sidebar-block {
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 14px;
        margin-bottom: 12px;
    }

    html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        color: #000000 !important;
    }

    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"],
    [data-testid="stMetricDelta"],
    [data-testid="stMarkdownContainer"],
    [data-testid="stCaptionContainer"],
    [data-testid="stTextInput"] label,
    [data-baseweb="tab"] {
        color: #000000 !important;
    }

    div[data-baseweb="tab-list"] {
        gap: 8px;
    }

    div[data-baseweb="tab"] {
        color: #000000 !important;
        border-color: rgba(32, 35, 48, 0.12) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _to_float(value: object) -> float | None:
    try:
        return float(str(value).replace("%", "").replace("+", "").replace(",", ""))
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(ttl=60)
def load_snapshot(path_str: str) -> dict | None:
    path = Path(path_str)
    if not path.exists() and SAMPLE_SNAPSHOT_FILE.exists():
        path = SAMPLE_SNAPSHOT_FILE
    elif not path.exists():
        return None
    try:
        return _load_json(path)
    except Exception:
        return None


@st.cache_data(ttl=30)
def load_alerts(path_str: str, limit: int) -> list[dict]:
    return read_recent_alerts(limit=limit, path=path_str)


@st.cache_data(ttl=600)
def load_stock_analysis(code: str) -> dict:
    return analyze_tw_stock(code)


def parse_updated_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    except Exception:
        return None


def freshness_label(updated_at: datetime | None) -> tuple[str, str]:
    if not updated_at:
        return ("無資料", "pill")
    age = datetime.now(LOCAL_TZ) - updated_at
    minutes = int(age.total_seconds() // 60)
    if minutes < 30:
        return (f"{minutes} 分鐘前更新", "pill")
    if minutes < 180:
        return (f"{minutes // 60} 小時前更新", "pill")
    return (f"{minutes // 60} 小時前更新", "pill pill-accent")


def format_index_delta(item: dict) -> str:
    pct = item.get("pct", "N/A")
    chg = item.get("chg", "N/A")
    return f"{chg} / {pct}%"


def build_candidate_frame(
    snapshot: dict,
    key: str = "tw_candidates",
    rank_key: str = "rank",
) -> pd.DataFrame:
    rows = []
    for item in snapshot.get(key, []):
        plan = item.get("entry_plan") or {}
        rows.append(
            {
                "排名": item.get(rank_key),
                "代碼": item.get("code"),
                "名稱": item.get("name"),
                "主題": item.get("theme"),
                "分數": item.get("score"),
                "進場分數": item.get("entry_score"),
                "狀態": item.get("entry_status_label"),
                "建議": item.get("entry_action"),
                "規劃停損": plan.get("stop_price"),
                "風險報酬": plan.get("reward_risk_ratio"),
                "1日%": item.get("pct_1d"),
                "5日%": item.get("pct_5d"),
                "RSI": item.get("rsi"),
                "量比": item.get("vol_ratio"),
                "來源": "中小雷達" if item.get("source") == "small_mid_radar" else "核心候選",
                "理由": "、".join(item.get("reasons", [])[:3]),
            }
        )
    return pd.DataFrame(rows)


def build_small_mid_frame(snapshot: dict) -> pd.DataFrame:
    rows = []
    for item in snapshot.get("small_mid_candidates", []):
        rows.append(
            {
                "排名": item.get("small_mid_rank"),
                "代碼": item.get("code"),
                "名稱": item.get("name"),
                "主題": item.get("theme"),
                "分數": item.get("small_mid_score", item.get("score")),
                "品質": item.get("quality_score"),
                "估值": item.get("valuation_score"),
                "技術": item.get("technical_score"),
                "市值(B)": item.get("market_cap_billion"),
                "均成交值(百萬)": item.get("avg_turnover_million"),
                "股價": item.get("price"),
                "20日%": item.get("pct_20d"),
                "PE": item.get("trailing_pe"),
                "PB": item.get("price_to_book"),
                "殖利率%": item.get("dividend_yield_pct"),
                "風險": "、".join(item.get("risk_flags", [])[:2]),
                "理由": "、".join(item.get("reasons", [])[:3]),
            }
        )
    return pd.DataFrame(rows)


def build_alert_frame(alerts: list[dict]) -> pd.DataFrame:
    rows = []
    for item in reversed(alerts):
        ts = item.get("ts")
        ts_label = "N/A"
        if ts:
            ts_label = datetime.fromtimestamp(ts, tz=LOCAL_TZ).strftime("%m-%d %H:%M")
        rows.append(
            {
                "時間": ts_label,
                "代碼": item.get("code", ""),
                "名稱": item.get("name", ""),
                "狀態": item.get("status", ""),
                "漲跌%": item.get("pct"),
                "RSI": item.get("rsi"),
                "量比": item.get("vol_ratio"),
                "內容": item.get("message", ""),
            }
        )
    return pd.DataFrame(rows)


def build_data_status_frame(snapshot: dict) -> pd.DataFrame:
    rows = []
    for key, item in (snapshot.get("data_status") or {}).items():
        rows.append(
            {
                "資料源": key,
                "狀態": "正常" if item.get("ok") and not item.get("cached") else "降級/快取",
                "來源": item.get("source", "N/A"),
                "更新時間": item.get("updated_at", "N/A"),
                "交易日": item.get("trading_date", "N/A"),
                "資料時間": item.get("as_of", "N/A"),
                "Fallback": item.get("fallback_used", False),
                "過期原因": item.get("stale_reason", ""),
                "TTL(分)": item.get("ttl_minutes", "N/A"),
                "錯誤": item.get("error", ""),
            }
        )
    return pd.DataFrame(rows)


def build_performance_frame(summary: dict) -> pd.DataFrame:
    rows = []
    for horizon, item in (summary.get("by_horizon") or {}).items():
        rows.append(
            {
                "天期": f"{horizon}日",
                "樣本": item.get("count"),
                "訊號日": item.get("signal_dates"),
                "毛報酬%": item.get("gross_avg_return_pct"),
                "淨報酬%": item.get("net_avg_return_pct"),
                "淨超額期望%": item.get("net_excess_expectancy_pct"),
                "勝率(次要)": item.get("win_rate"),
                "Profit factor": item.get("profit_factor"),
            }
        )
    return pd.DataFrame(rows)


def candidate_chart(frame: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if frame.empty:
        figure.update_layout(height=320, margin=dict(l=0, r=0, t=20, b=0))
        return figure

    figure.add_trace(
        go.Bar(
            x=frame["名稱"],
            y=frame["1日%"],
            marker_color="rgba(0,0,0,0.86)",
            text=[f"{value:+.2f}%" for value in frame["1日%"]],
            textposition="outside",
            hovertemplate="%{x}<br>單日漲跌 %{y:+.2f}%<extra></extra>",
        )
    )
    figure.update_layout(
        height=360,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="1日漲跌幅",
        xaxis_title="",
    )
    figure.update_yaxes(gridcolor="rgba(32,35,48,0.10)", zerolinecolor="rgba(32,35,48,0.18)")
    return figure


def stock_price_chart(history: pd.DataFrame, name: str) -> go.Figure:
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.72, 0.28],
    )
    figure.add_trace(
        go.Candlestick(
            x=history.index,
            open=history["Open"],
            high=history["High"],
            low=history["Low"],
            close=history["Close"],
            name=name,
            increasing_line_color="#000000",
            increasing_fillcolor="rgba(0,0,0,0.82)",
            decreasing_line_color="#000000",
            decreasing_fillcolor="rgba(0,0,0,0.38)",
        ),
        row=1,
        col=1,
    )
    for line_name, color in [
        ("MA20", "#000000"),
        ("MA60", "rgba(0,0,0,0.72)"),
        ("MA120", "rgba(0,0,0,0.48)"),
    ]:
        figure.add_trace(
            go.Scatter(
                x=history.index,
                y=history[line_name],
                mode="lines",
                line=dict(color=color, width=2),
                name=line_name,
            ),
            row=1,
            col=1,
        )

    figure.add_trace(
        go.Bar(
            x=history.index,
            y=history["Volume"],
            marker_color="rgba(0,0,0,0.30)",
            name="Volume",
        ),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=history.index,
            y=history["VOL20"],
            mode="lines",
            line=dict(color="#000000", width=1.8),
            name="VOL20",
        ),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=620,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    figure.update_yaxes(gridcolor="rgba(32,35,48,0.10)")
    return figure


def score_chart(scores: dict[str, float]) -> go.Figure:
    score_items = [(key, value) for key, value in scores.items() if key != "總分"]
    figure = go.Figure(
        go.Bar(
            x=[value for _, value in score_items],
            y=[key for key, _ in score_items],
            orientation="h",
            marker=dict(
                color=[value for _, value in score_items],
                colorscale=[
                    [0.0, "rgba(0,0,0,0.40)"],
                    [0.5, "rgba(0,0,0,0.65)"],
                    [1.0, "rgba(0,0,0,0.90)"],
                ],
                cmin=0,
                cmax=100,
            ),
            text=[f"{value:.0f}" for _, value in score_items],
            textposition="outside",
            hovertemplate="%{y}: %{x:.0f}<extra></extra>",
        )
    )
    figure.update_layout(
        height=300,
        margin=dict(l=0, r=20, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="分數",
        yaxis_title="",
    )
    figure.update_xaxes(range=[0, 100], gridcolor="rgba(32,35,48,0.10)")
    return figure


def render_theme_cards(theme_summary: list[dict]) -> None:
    if not theme_summary:
        st.info("目前沒有主軸資料。")
        return
    for item in theme_summary[:3]:
        leaders = "、".join(item.get("leaders", [])[:3]) or "暫無代表股"
        st.markdown(
            f"""
            <div class="theme-card">
                <div class="theme-name">{item.get("theme", "未分類")}</div>
                <div class="theme-score">強度 {item.get("score", 0):.1f}</div>
                <div class="theme-leaders">代表股：{leaders}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_news_block(title: str, items: list[str]) -> None:
    rendered_items = []
    for item in items[:5]:
        if isinstance(item, dict):
            source = item.get("source") or "來源未標示"
            news_title = item.get("title") or "無標題"
            rendered_items.append(f"<li><strong>{source}</strong>: {news_title}</li>")
        else:
            rendered_items.append(f"<li>{item}</li>")
    lines = "".join(rendered_items) or "<li>暫無資料</li>"
    st.markdown(
        f"""
        <div class="news-card">
            <div class="small-title">{title}</div>
            <ul>{lines}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


snapshot = load_snapshot(str(SNAPSHOT_FILE))

with st.sidebar:
    st.markdown("## 戰情室導覽")
    if st.button("重新讀取資料", width="stretch"):
        load_snapshot.clear()
        load_alerts.clear()
        load_stock_analysis.clear()
        st.rerun()

    st.markdown(
        f"""
        <div class="sidebar-block">
            <div class="small-title">快照路徑</div>
            <div>{SNAPSHOT_FILE}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if snapshot:
        updated_at = parse_updated_at(snapshot.get("updated_at"))
        freshness_text, freshness_class = freshness_label(updated_at)
        st.markdown(
            f"""
            <div class="sidebar-block">
                <div class="small-title">資料狀態</div>
                <div class="{freshness_class}" style="margin-top:10px;">{freshness_text}</div>
                <div style="margin-top:10px;">模式：{snapshot.get("mode", "N/A")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        focus_names = [
            f"{item.get('code')} {item.get('name')}"
            for item in snapshot.get("tw_candidates", [])[:5]
        ]
        st.markdown(
            f"""
            <div class="sidebar-block">
                <div class="small-title">今日焦點</div>
                <div style="margin-top:10px; line-height:1.7;">{"<br>".join(focus_names) or "暫無資料"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        institutional_total = (
            snapshot.get("market", {})
            .get("institutional", {})
            .get("total", "N/A")
        )
        if institutional_total == "N/A":
            st.warning("三大法人資料目前仍是 N/A，這段資料源還沒修復。")


if not snapshot:
    st.error("找不到可用的 runtime 快照。先執行 `python rpi_main.py` 產生 `runtime/daily_candidates.json`。")
    st.stop()

if "stock_query" not in st.session_state:
    st.session_state["stock_query"] = (
        snapshot.get("tw_candidates", [{}])[0].get("code") or "2330"
    )


updated_at = parse_updated_at(snapshot.get("updated_at"))
freshness_text, freshness_class = freshness_label(updated_at)
report_text = format_market_report(snapshot)
market = snapshot.get("market", {})
tw_index = market.get("tw_index", {})
forex = market.get("forex", {})
us_indices = market.get("us_indices", {})
candidate_frame = build_candidate_frame(snapshot)
actionable_frame = build_candidate_frame(
    snapshot,
    "actionable_candidates",
    "actionable_rank",
)
early_watch_frame = build_candidate_frame(
    snapshot,
    "early_watch_candidates",
    "early_watch_rank",
)
small_mid_frame = build_small_mid_frame(snapshot)
alert_frame = build_alert_frame(load_alerts(str(ALERTS_FILE), limit=50))
data_status_frame = build_data_status_frame(snapshot)
embedded_performance = snapshot.get("performance_summary") or {}
performance_summary = (
    embedded_performance
    if embedded_performance.get("schema_version") == 2
    else summarize_performance()
)
performance_frame = build_performance_frame(performance_summary)
shadow_performance_summary = snapshot.get("shadow_performance_summary") or {}
portfolio_risk = snapshot.get("portfolio_risk") or {}
model_research = snapshot.get("model_research") or {}
theme_summary = snapshot.get("theme_summary", [])
news_summary = snapshot.get("news_summary", {})


st.markdown(
    f"""
    <div class="hero">
        <h1 class="hero-title">台股 AI 戰情室</h1>
        <div class="hero-subtitle">
            目前 Streamlit 改為唯讀監控台，只顯示候選股、主軸、報告預覽與警示紀錄。
        </div>
        <div class="pill-row">
            <div class="pill pill-accent">模式 {snapshot.get("mode", "N/A")}</div>
            <div class="pill">更新時間 {snapshot.get("updated_at", "N/A")}</div>
            <div class="{freshness_class}">{freshness_text}</div>
            <div class="pill">焦點股 {len(snapshot.get("tw_candidates", []))} 檔</div>
            <div class="pill">即時警示 {len(alert_frame.index)} 則</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


overview_tab, small_mid_tab, analysis_tab, performance_tab, report_tab, alerts_tab, raw_tab = st.tabs(
    ["市場總覽", "中小雷達", "個股解析", "訊號成效", "報告預覽", "警示紀錄", "原始資料"]
)


with overview_tab:
    st.markdown("### 今日市場總覽")
    st.caption("先看大盤與脈絡，再看主軸和候選股，不在這裡做手動加股。")

    metric_cols = st.columns(4)
    metric_cols[0].metric(
        "台股加權",
        tw_index.get("price", "N/A"),
        f"{tw_index.get('pct', 'N/A')}%",
    )
    metric_cols[1].metric("成交值", tw_index.get("turnover", "N/A"))
    metric_cols[2].metric(
        "USD/TWD",
        forex.get("rate", "N/A"),
        forex.get("chg", "N/A"),
        delta_color="inverse",
    )
    metric_cols[3].metric(
        "三大法人合計",
        market.get("institutional", {}).get("total", "N/A"),
    )

    action_col, radar_col = st.columns(2, gap="large")
    with action_col:
        st.markdown("### 可執行名單")
        st.caption("只有同時通過乖離、停損距離與風險報酬門檻者，才列為可分批布局。")
        if actionable_frame.empty:
            st.info("今日沒有通過完整進場門檻的股票；空手等待也是有效決策。")
        else:
            st.dataframe(
                actionable_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "分數": st.column_config.ProgressColumn("趨勢強度", min_value=0, max_value=100),
                    "進場分數": st.column_config.ProgressColumn("進場可行性", min_value=0, max_value=100),
                },
            )
    with radar_col:
        st.markdown("### 提前雷達")
        st.caption("捕捉剛轉強型態，容許較多誤報，績效與正式訊號分開記錄。")
        if early_watch_frame.empty:
            st.info("目前沒有新的轉強型態進入提前雷達。")
        else:
            st.dataframe(
                early_watch_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "分數": st.column_config.ProgressColumn("趨勢強度", min_value=0, max_value=100),
                    "進場分數": st.column_config.ProgressColumn("進場可行性", min_value=0, max_value=100),
                },
            )

    st.markdown("### 美股與波動脈絡")
    us_cols = st.columns(5)
    for col, label in zip(
        us_cols,
        ["S&P500", "道瓊", "那斯達克", "費半", "VIX"],
        strict=False,
    ):
        item = us_indices.get(label, {})
        delta = format_index_delta(item) if item else "N/A"
        col.metric(label, item.get("price", "N/A"), delta)

    left_col, right_col = st.columns([0.95, 1.25], gap="large")
    with left_col:
        st.markdown("### 今日主軸")
        st.markdown(
            "主軸判讀不是只看前 5 檔，而是用全部候選股強度加權後排序。",
            help="主軸來自候選股整體分數、漲跌幅與主題映射。",
        )
        render_theme_cards(theme_summary)

    with right_col:
        st.markdown("### 焦點股強弱")
        if candidate_frame.empty:
            st.info("目前沒有候選股資料。")
        else:
            st.plotly_chart(candidate_chart(candidate_frame.head(8)), width="stretch")

        st.markdown("### 候選股名單")
        st.dataframe(
            candidate_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "分數": st.column_config.ProgressColumn("分數", min_value=0, max_value=100),
                "進場分數": st.column_config.ProgressColumn("進場可行性", min_value=0, max_value=100),
                "1日%": st.column_config.NumberColumn("1日%", format="%.2f%%"),
                "5日%": st.column_config.NumberColumn("5日%", format="%.2f%%"),
                "RSI": st.column_config.NumberColumn("RSI", format="%.1f"),
                "量比": st.column_config.NumberColumn("量比", format="%.2f"),
            },
        )

    news_col1, news_col2 = st.columns(2, gap="large")
    with news_col1:
        st.markdown("### 台股新聞")
        render_news_block("TW News", news_summary.get("tw_top_titles", []))
    with news_col2:
        st.markdown("### 美股新聞")
        render_news_block("US News", news_summary.get("us_top_titles", []))

    st.markdown("### 資料狀態")
    if data_status_frame.empty:
        st.info("目前快照沒有資料狀態紀錄。")
    else:
        st.dataframe(data_status_frame, width="stretch", hide_index=True)


with small_mid_tab:
    st.markdown("### 中小型優質股雷達")
    st.caption("Shadow mode：只記錄與驗證，不會併入核心主推名單，也不影響正式策略 KPI。")

    if small_mid_frame.empty:
        st.info("目前沒有符合流動性、價格與品質條件的中小型股。可調整 SMALL_MID_CODES 或等待下一次資料更新。")
    else:
        metric_cols = st.columns(4)
        metric_cols[0].metric("雷達候選", f"{len(small_mid_frame.index)} 檔")
        metric_cols[1].metric("最高分", f"{small_mid_frame['分數'].max():.0f}")
        metric_cols[2].metric("均市值", f"{small_mid_frame['市值(B)'].dropna().mean():.1f}B")
        metric_cols[3].metric("均成交值", f"{small_mid_frame['均成交值(百萬)'].dropna().mean():.0f} 百萬")

        st.dataframe(
            small_mid_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "分數": st.column_config.ProgressColumn("分數", min_value=0, max_value=100),
                "品質": st.column_config.ProgressColumn("品質", min_value=0, max_value=100),
                "估值": st.column_config.ProgressColumn("估值", min_value=0, max_value=100),
                "技術": st.column_config.ProgressColumn("技術", min_value=0, max_value=100),
                "市值(B)": st.column_config.NumberColumn("市值(B)", format="%.1f"),
                "均成交值(百萬)": st.column_config.NumberColumn("均成交值(百萬)", format="%.0f"),
                "股價": st.column_config.NumberColumn("股價", format="%.2f"),
                "20日%": st.column_config.NumberColumn("20日%", format="%.2f%%"),
                "PE": st.column_config.NumberColumn("PE", format="%.1f"),
                "PB": st.column_config.NumberColumn("PB", format="%.1f"),
                "殖利率%": st.column_config.NumberColumn("殖利率%", format="%.2f%%"),
            },
        )

        st.markdown("#### 使用規則")
        st.markdown("- 優先看 A 級分數股是否同步具備成交值、估值合理與 MA20/MA60 結構。")
        st.markdown("- 成交值低於 8000 萬或 RSI 過熱者，只列觀察，不追價。")
        st.markdown("- 若隔日跌破 MA20 或成交值沒有放大，先移出優先觀察。")


with analysis_tab:
    st.markdown("### 台股個股解析")
    st.caption("輸入代號或中文名稱，分析邏輯以趨勢、量能、相對大盤強弱與月營收動能為主。")

    query = st.text_input(
        "輸入代號或中文名稱",
        key="stock_query",
        placeholder="例如 2330 / 台積電 / 2454 / 聯發科",
    )
    matches = search_tw_stocks(query)

    if not query.strip():
        st.info("輸入台股代號或中文名稱後，這裡會顯示圖表與詳細判讀。")
    elif not matches:
        st.warning("找不到符合的台股股票，請改用完整代號或更接近的中文名稱。")
    else:
        selected_options = {
            f"{item.code} {item.name} / {item.group}": item.code for item in matches
        }
        selected_label = st.selectbox(
            "搜尋結果",
            list(selected_options.keys()),
            label_visibility="collapsed",
        )
        selected_code = selected_options[selected_label]

        try:
            stock_analysis = load_stock_analysis(selected_code)
        except Exception as exc:
            st.error(f"個股分析失敗: {exc}")
        else:
            focus_item = next(
                (
                    item
                    for item in [
                        *snapshot.get("actionable_candidates", []),
                        *snapshot.get("early_watch_candidates", []),
                        *snapshot.get("tw_candidates", []),
                    ]
                    if item.get("code") == selected_code
                ),
                None,
            )
            scores = stock_analysis["scores"]
            price = stock_analysis["price"]
            revenue = stock_analysis["revenue"]
            relative_strength = stock_analysis["relative_strength"]
            analysis = stock_analysis["analysis"]
            entry_opportunity = stock_analysis.get("entry_opportunity") or {}
            company_assessment = stock_analysis.get("company_assessment") or {}

            st.markdown(
                f"""
                <div class="theme-card">
                    <div class="theme-name">{stock_analysis['code']} {stock_analysis['name']}</div>
                    <div class="theme-leaders">
                        產業：{stock_analysis['industry_group']}<br>
                        主題：{stock_analysis['theme']}<br>
                        判讀：{analysis['bias']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            metric_cols = st.columns(6)
            metric_cols[0].metric(
                "最新價",
                f"{price['close']:.2f}",
                f"{price['pct_1d']:+.2f}%",
            )
            metric_cols[1].metric(
                "20日漲跌",
                "N/A" if price["pct_20d"] is None else f"{price['pct_20d']:+.2f}%",
            )
            metric_cols[2].metric(
                "相對大盤20日",
                "N/A"
                if relative_strength["rs_20d"] is None
                else f"{relative_strength['rs_20d']:+.2f}%",
            )
            metric_cols[3].metric(
                "量比",
                "N/A"
                if stock_analysis["indicators"]["vol_ratio"] is None
                else f"{stock_analysis['indicators']['vol_ratio']:.2f}x",
            )
            metric_cols[4].metric(
                "月營收年增",
                "N/A"
                if revenue.get("yoy_pct") is None
                else f"{revenue['yoy_pct']:+.2f}%",
            )
            metric_cols[5].metric(
                "進場可行性",
                f"{entry_opportunity.get('entry_score', 0):.0f}",
                entry_opportunity.get("entry_status_label", "等待確認"),
            )

            assessment_cols = st.columns(4)
            quality_score = company_assessment.get("company_quality_score")
            valuation_score = company_assessment.get("valuation_attractiveness_score")
            timing_score = company_assessment.get("entry_timing_score")
            assessment_cols[0].metric(
                "公司品質",
                "N/A" if quality_score is None else f"{quality_score:.0f}",
                company_assessment.get("company_quality_confidence", "資料不足"),
            )
            assessment_cols[1].metric(
                "估值吸引力",
                "N/A" if valuation_score is None else f"{valuation_score:.0f}",
            )
            assessment_cols[2].metric(
                "進場時機",
                "N/A" if timing_score is None else f"{timing_score:.0f}",
            )
            assessment_cols[3].metric(
                "事件風險",
                company_assessment.get("event_risk_level", "待確認"),
            )
            st.info(
                f"{company_assessment.get('opportunity_label', '持續觀察')}｜"
                f"{company_assessment.get('plain_language_advice', '等待資料補齊後再判讀。')}"
            )
            st.caption(
                f"基本面：{company_assessment.get('fundamental_summary', '資料不足')}｜"
                f"估值：{company_assessment.get('valuation_summary', '資料不足')}｜"
                f"事件：{company_assessment.get('event_risk_summary', '待確認')}"
            )

            left_col, right_col = st.columns([1.35, 0.95], gap="large")
            with left_col:
                st.plotly_chart(
                    stock_price_chart(stock_analysis["history"], stock_analysis["name"]),
                    width="stretch",
                )

            with right_col:
                st.metric("分析總分", f"{scores['總分']:.0f}")
                st.plotly_chart(score_chart(scores), width="stretch")
                plan = entry_opportunity.get("entry_plan") or {}
                if plan:
                    st.caption(
                        f"規劃停損 {plan.get('stop_price', 'N/A')}｜"
                        f"評估目標 {plan.get('target_price', 'N/A')}｜"
                        f"風險報酬 {plan.get('reward_risk_ratio', 'N/A')}"
                    )

                if revenue:
                    revenue_cols = st.columns(2)
                    revenue_cols[0].metric(
                        "最新月營收",
                        "N/A"
                        if revenue.get("month_revenue_billion") is None
                        else f"{revenue['month_revenue_billion']:.1f} 億",
                    )
                    revenue_cols[1].metric(
                        "累計營收年增",
                        "N/A"
                        if revenue.get("cumulative_yoy_pct") is None
                        else f"{revenue['cumulative_yoy_pct']:+.2f}%",
                    )

                support_text = "、".join(
                    f"{level:.1f}" for level in analysis["support_levels"][:3]
                ) or "N/A"
                resistance_text = "、".join(
                    f"{level:.1f}" for level in analysis["resistance_levels"][:3]
                ) or "N/A"
                st.markdown(f"**支撐觀察**: {support_text}")
                st.markdown(f"**壓力觀察**: {resistance_text}")

                if focus_item:
                    st.success(
                        f"目前也在候選股名單中: 排名 {focus_item.get('rank')} / 分數 {focus_item.get('score')}"
                    )

            insight_col, risk_col = st.columns(2, gap="large")
            with insight_col:
                st.markdown("#### 結構判讀")
                st.markdown(f"**操作結論**: {analysis['action']}")
                for line in analysis["indicator_checks"]:
                    st.markdown(f"- {line}")

            with risk_col:
                st.markdown("#### 風險提醒")
                for line in analysis["risk_flags"]:
                    st.markdown(f"- {line}")

            detail_cols = st.columns(4)
            detail_cols[0].metric(
                "距 MA20",
                "N/A"
                if price["distance_to_ma20"] is None
                else f"{price['distance_to_ma20']:+.2f}%",
            )
            detail_cols[1].metric(
                "距 MA60",
                "N/A"
                if price["distance_to_ma60"] is None
                else f"{price['distance_to_ma60']:+.2f}%",
            )
            detail_cols[2].metric(
                "距 20日高點",
                "N/A"
                if price["breakout_gap_20"] is None
                else f"{price['breakout_gap_20']:+.2f}%",
            )
            detail_cols[3].metric(
                "RSI 14",
                f"{stock_analysis['indicators']['rsi14']:.1f}",
                f"MACD {stock_analysis['indicators']['macd_hist']:+.2f}",
            )


with performance_tab:
    st.markdown("### 訊號成效")
    st.caption(
        f"正式口徑：live / primary / {performance_summary.get('strategy_version', 'N/A')}；"
        f"主評估天期 {performance_summary.get('primary_horizon', 'N/A')} 日。勝率只作次要指標。"
    )
    metric_cols = st.columns(6)
    metric_cols[0].metric("樣本數", performance_summary.get("count", 0))
    metric_cols[1].metric(
        "訊號日",
        performance_summary.get("signal_dates", 0),
    )
    metric_cols[2].metric(
        "淨超額期望",
        "N/A"
        if performance_summary.get("net_excess_expectancy_pct") is None
        else f"{performance_summary['net_excess_expectancy_pct']:+.2f}%",
    )
    metric_cols[3].metric(
        "淨平均報酬",
        "N/A"
        if performance_summary.get("net_avg_return_pct") is None
        else f"{performance_summary['net_avg_return_pct']:+.2f}%",
    )
    metric_cols[4].metric(
        "最大回撤",
        "N/A"
        if performance_summary.get("max_drawdown_pct") is None
        else f"{performance_summary['max_drawdown_pct']:+.2f}%",
    )
    metric_cols[5].metric(
        "勝率（次要）",
        "N/A"
        if performance_summary.get("win_rate") is None
        else f"{performance_summary['win_rate']:.0%}",
    )

    if performance_frame.empty:
        st.info("尚未累積足夠的訊號績效資料。執行幾天盤前/盤後流程後會逐步補上。")
    else:
        st.dataframe(
            performance_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "毛報酬%": st.column_config.NumberColumn("毛報酬%", format="%.2f%%"),
                "淨報酬%": st.column_config.NumberColumn("淨報酬%", format="%.2f%%"),
                "淨超額期望%": st.column_config.NumberColumn("淨超額期望%", format="%.2f%%"),
                "勝率(次要)": st.column_config.NumberColumn("勝率(次要)", format="%.0%%"),
            },
        )
    cost_assumptions = performance_summary.get("cost_assumptions") or {}
    if cost_assumptions:
        st.caption(
            "成本假設：平價往返約 "
            f"{cost_assumptions.get('round_trip_cost_at_flat_price_pct', 0):.3f}%；"
            "含雙邊手續費、賣出證交稅與雙邊滑價，均可由環境變數覆寫。"
        )
    equity_curve = performance_summary.get("equity_curve") or []
    if equity_curve:
        st.markdown("#### 非重疊等權 Cohort 資金曲線")
        equity_frame = pd.DataFrame(equity_curve)
        st.line_chart(equity_frame, x="exit_date", y="equity")
        st.caption(
            "回撤由可重建資金曲線計算；同一持有期間不重複投入資本，避免把單筆最差報酬冒充最大回撤。"
        )

    theme_performance = performance_summary.get("theme_performance") or {}
    if theme_performance:
        st.markdown("#### 主題淨績效")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "主題": theme,
                        "樣本": stats.get("count"),
                        "淨超額期望%": stats.get("net_excess_expectancy_pct"),
                        "勝率(次要)": stats.get("win_rate"),
                    }
                    for theme, stats in theme_performance.items()
                ]
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "淨超額期望%": st.column_config.NumberColumn("淨超額期望%", format="%.2f%%"),
                "勝率(次要)": st.column_config.NumberColumn("勝率(次要)", format="%.0%%"),
            },
        )

    st.markdown("#### 投組風控")
    risk_cols = st.columns(4)
    risk_cols[0].metric("風控狀態", portfolio_risk.get("status", "N/A"))
    risk_cols[1].metric(
        "最大主題權重",
        "N/A" if not portfolio_risk.get("max_theme") else f"{portfolio_risk['max_theme']['weight']:.0%}",
    )
    risk_cols[2].metric(
        "單向換手",
        "N/A" if portfolio_risk.get("one_way_turnover") is None else f"{portfolio_risk['one_way_turnover']:.0%}",
    )
    risk_cols[3].metric("風控違規", len(portfolio_risk.get("breaches") or []))
    if portfolio_risk.get("breaches"):
        st.warning("；".join(portfolio_risk["breaches"]))

    with st.expander("研究模型與 Shadow 雷達狀態"):
        st.write(
            {
                "model_status": model_research.get("status", "N/A"),
                "model_observations": model_research.get("observations", 0),
                "walk_forward_folds": model_research.get("folds", 0),
                "ready_for_selection": model_research.get("ready_for_selection", False),
                "shadow_signal_count": shadow_performance_summary.get("count", 0),
                "shadow_net_excess_expectancy_pct": shadow_performance_summary.get(
                    "net_excess_expectancy_pct"
                ),
            }
        )
        shadow_ranking = model_research.get("shadow_ranking") or []
        if shadow_ranking:
            st.dataframe(pd.DataFrame(shadow_ranking), width="stretch", hide_index=True)


with report_tab:
    st.markdown("### 報告預覽")
    st.caption("這裡只預覽最新快照會產出的訊息內容，不會從 Streamlit 直接發 Telegram。")
    st.text_area(
        "盤前 / 盤後報告文字",
        report_text,
        height=520,
        label_visibility="collapsed",
    )


with alerts_tab:
    st.markdown("### 即時警示紀錄")
    st.caption("盤中警示只顯示最近紀錄，方便從手機或桌面快速回看。")
    if alert_frame.empty:
        st.info("目前沒有 `alerts.jsonl` 內容。盤中輪詢有發訊號後，這裡才會出現紀錄。")
    else:
        st.dataframe(
            alert_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "漲跌%": st.column_config.NumberColumn("漲跌%", format="%.2f%%"),
                "RSI": st.column_config.NumberColumn("RSI", format="%.1f"),
                "量比": st.column_config.NumberColumn("量比", format="%.2f"),
            },
        )


with raw_tab:
    st.markdown("### 原始快照")
    st.caption("需要除錯時再看這頁，平常判讀以市場總覽和報告預覽為主。")
    st.json(snapshot, expanded=False)
