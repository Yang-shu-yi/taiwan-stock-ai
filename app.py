import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alert_store import read_recent_alerts
from message_formatter import format_market_report


SNAPSHOT_FILE = Path(os.getenv("DAILY_CANDIDATES_FILE", "daily_candidates.json"))
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
        --ink: #202330;
        --muted: #68707f;
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
        color: #883d2b;
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
        color: var(--accent);
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
    if not path.exists():
        return None
    try:
        return _load_json(path)
    except Exception:
        return None


@st.cache_data(ttl=30)
def load_alerts(path_str: str, limit: int) -> list[dict]:
    return read_recent_alerts(limit=limit, path=path_str)


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


def build_candidate_frame(snapshot: dict) -> pd.DataFrame:
    rows = []
    for item in snapshot.get("tw_candidates", []):
        rows.append(
            {
                "排名": item.get("rank"),
                "代碼": item.get("code"),
                "名稱": item.get("name"),
                "主題": item.get("theme"),
                "分數": item.get("score"),
                "1日%": item.get("pct_1d"),
                "5日%": item.get("pct_5d"),
                "RSI": item.get("rsi"),
                "量比": item.get("vol_ratio"),
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


def candidate_chart(frame: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if frame.empty:
        figure.update_layout(height=320, margin=dict(l=0, r=0, t=20, b=0))
        return figure

    colors = ["#228b5a" if value >= 0 else "#b24343" for value in frame["1日%"]]
    figure.add_trace(
        go.Bar(
            x=frame["名稱"],
            y=frame["1日%"],
            marker_color=colors,
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
    lines = "".join(f"<li>{item}</li>" for item in items[:5]) or "<li>暫無資料</li>"
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
    st.error("找不到可用的 `daily_candidates.json`。先執行 `python rpi_main.py` 產生最新快照。")
    st.stop()


updated_at = parse_updated_at(snapshot.get("updated_at"))
freshness_text, freshness_class = freshness_label(updated_at)
report_text = format_market_report(snapshot)
market = snapshot.get("market", {})
tw_index = market.get("tw_index", {})
forex = market.get("forex", {})
us_indices = market.get("us_indices", {})
candidate_frame = build_candidate_frame(snapshot)
alert_frame = build_alert_frame(load_alerts(str(ALERTS_FILE), limit=50))
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


overview_tab, report_tab, alerts_tab, raw_tab = st.tabs(
    ["市場總覽", "報告預覽", "警示紀錄", "原始資料"]
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
