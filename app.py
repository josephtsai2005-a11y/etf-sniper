"""
app.py
Streamlit 看板 — 讀取 Google Sheets 顯示狙擊名單與分析圖表
執行：streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import os
from datetime import datetime

# ── 頁面設定 ────────────────────────────────────────────────
st.set_page_config(
    page_title="投信主力狙擊系統",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_SNIPER   = "狙擊名單"
SHEET_ANALYSIS = "籌碼分析庫"
SHEET_HISTORY  = "歷史回測庫"
SHEET_RAW      = "盤後原始數據庫"


# ── Google Sheets 連線（支援 Streamlit Secrets） ──────────────
@st.cache_resource
def get_gspread_client():
    try:
        # Streamlit Cloud：從 st.secrets 讀取
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        # 本機：從檔案讀取
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "secrets/gcp-sa.json")
        creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_data(ttl=300)  # 5 分鐘快取
def load_sheet(sheet_name: str) -> pd.DataFrame:
    client = get_gspread_client()
    spreadsheet_id = (
        st.secrets.get("SPREADSHEET_ID", "")
        or os.environ.get("SPREADSHEET_ID", "")
    )
    try:
        ss = client.open_by_key(spreadsheet_id)
        ws = ss.worksheet(sheet_name)
        data = ws.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"無法載入 {sheet_name}: {e}")
        return pd.DataFrame()


def score_color(score):
    if score >= 7: return "🟢"
    if score >= 5: return "🟡"
    if score >= 3: return "🟠"
    return "🔴"


# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ 狙擊系統")
    st.caption("投信主力追蹤 · 每日盤後更新")
    st.divider()
    page = st.radio("頁面", ["今日狙擊名單", "個股深度分析", "ETF 覆蓋熱圖", "歷史績效"])
    st.divider()
    min_score = st.slider("最低狙擊分數", 0, 8, 5)
    if st.button("🔄 重新整理資料", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"最後刷新：{datetime.now().strftime('%H:%M:%S')}")


# ══════════════════════════════════════════════════════════════
# 頁面 1：今日狙擊名單
# ══════════════════════════════════════════════════════════════
if page == "今日狙擊名單":
    st.title("⚡ 今日狙擊名單")

    df = load_sheet(SHEET_SNIPER)

    if df.empty:
        st.warning("尚無資料，請確認 Cloud Run Job 已執行或今日是否為交易日")
        st.stop()

    # 過濾第一行（可能是標題描述行）
    if "sniper_score" in df.columns:
        df["sniper_score"] = pd.to_numeric(df["sniper_score"], errors="coerce").fillna(0)
        df = df[df["sniper_score"] >= min_score]

    # 統計摘要
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("符合標的", f"{len(df)} 檔")
    c2.metric("滿分 (8/8)", f"{(df.get('sniper_score', pd.Series()) == 8).sum()} 檔")
    c3.metric("高分 (≥7)", f"{(df.get('sniper_score', pd.Series()) >= 7).sum()} 檔")
    c4.metric("連續建倉", f"{df.get('label', pd.Series('', index=df.index)).str.contains('🔥').sum()} 檔")

    st.divider()

    # 主表格
    display_cols = {
        "排名": "排名",
        "股票代號": "代號",
        "股票名稱": "名稱",
        "sniper_score": "分數",
        "label": "標籤",
        "etf_count": "ETF數",
        "consec_buy_days": "連買天",
        "trust_cum_5d": "5日累買(張)",
        "above_ma20": "站月線",
        "close": "收盤價",
    }
    available = {k: v for k, v in display_cols.items() if k in df.columns}
    view = df[list(available.keys())].rename(columns=available)

    # 加上顏色指示
    if "分數" in view.columns:
        view.insert(3, "強度", view["分數"].apply(score_color))

    st.dataframe(
        view,
        use_container_width=True,
        height=500,
        hide_index=True,
    )

    # 分數分布長條圖
    if "sniper_score" in df.columns and not df.empty:
        st.subheader("籌碼分數分布")
        score_dist = df["sniper_score"].value_counts().sort_index(ascending=False)
        fig = px.bar(
            x=score_dist.index,
            y=score_dist.values,
            labels={"x": "狙擊分數", "y": "股票數量"},
            color=score_dist.index,
            color_continuous_scale=["#E24B4A", "#EF9F27", "#1D9E75"],
        )
        fig.update_layout(
            showlegend=False,
            height=280,
            margin=dict(t=10, b=10),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# 頁面 2：個股深度分析
# ══════════════════════════════════════════════════════════════
elif page == "個股深度分析":
    st.title("🔍 個股深度分析")

    analysis_df = load_sheet(SHEET_ANALYSIS)

    if analysis_df.empty:
        st.warning("分析庫尚無資料")
        st.stop()

    stocks = analysis_df["股票代號"].dropna().unique().tolist() if "股票代號" in analysis_df.columns else []

    if not stocks:
        st.info("分析庫中尚無股票資料")
        st.stop()

    selected = st.selectbox("選擇股票", stocks)
    stock_df = analysis_df[analysis_df["股票代號"] == selected]

    if stock_df.empty:
        st.info("尚無此股票資料")
        st.stop()

    latest = stock_df.iloc[-1]
    name = latest.get("股票名稱", selected)

    st.subheader(f"{selected} {name}")

    # 8 點雷達圖
    score_cols = ["s1_trust_cum","s2_consec_buy","s3_above_ma20","s4_amount",
                  "s5_vol_ratio","s6_amplitude","s7_fund_growth","s8_weight"]
    score_labels = ["投信累買","連買趨勢","站月線","成交量","量能比","震幅","資金增幅","權重偵測"]

    scores = [float(latest.get(c, 0)) for c in score_cols]

    fig_radar = go.Figure(go.Scatterpolar(
        r=scores + [scores[0]],
        theta=score_labels + [score_labels[0]],
        fill="toself",
        fillcolor="rgba(29,158,117,0.2)",
        line=dict(color="#1D9E75", width=2),
    ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        height=350,
        margin=dict(t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_radar, use_container_width=True)

    # 各指標詳細
    c1, c2 = st.columns(2)
    with c1:
        st.metric("狙擊總分", f"{int(latest.get('sniper_score', 0))} / 8")
        st.metric("連續買超天數", f"{int(latest.get('consec_buy_days', 0))} 天")
        st.metric("5日累計買超", f"{int(latest.get('trust_cum_5d', 0)):,} 張")
    with c2:
        st.metric("站上月線", "✅ 是" if latest.get("above_ma20") else "❌ 否")
        st.metric("量能比", f"{float(latest.get('volume_ratio', 0)):.2f} 倍")
        st.metric("被幾檔ETF持有", f"{int(latest.get('etf_count', 0))} 檔")

    # 被哪些 ETF 持有
    if "ETF代碼" in stock_df.columns:
        etfs = stock_df["ETF代碼"].unique().tolist()
        st.caption(f"持有此股的 ETF：{' · '.join(etfs)}")


# ══════════════════════════════════════════════════════════════
# 頁面 3：ETF 覆蓋熱圖
# ══════════════════════════════════════════════════════════════
elif page == "ETF 覆蓋熱圖":
    st.title("🗺️ ETF 持股覆蓋熱圖")
    st.caption("同時被多檔 ETF 持有的股票 → 主力集中度最高")

    raw_df = load_sheet(SHEET_RAW)

    if raw_df.empty:
        st.warning("原始資料庫尚無資料")
        st.stop()

    if "股票代號" not in raw_df.columns or "ETF代碼" not in raw_df.columns:
        st.warning("資料欄位不符，請確認原始庫格式")
        st.stop()

    # 找出被最多 ETF 持有的股票
    coverage = (
        raw_df.groupby("股票代號")["ETF代碼"]
        .nunique()
        .reset_index()
        .rename(columns={"ETF代碼": "ETF涵蓋數"})
        .sort_values("ETF涵蓋數", ascending=False)
        .head(30)
    )

    if "股票名稱" in raw_df.columns:
        name_map = raw_df.drop_duplicates("股票代號")[["股票代號", "股票名稱"]]
        coverage = coverage.merge(name_map, on="股票代號", how="left")

    fig = px.bar(
        coverage,
        x="股票代號",
        y="ETF涵蓋數",
        color="ETF涵蓋數",
        color_continuous_scale=["#E6F1FB", "#1D9E75"],
        hover_data=["股票名稱"] if "股票名稱" in coverage.columns else None,
        labels={"ETF涵蓋數": "持有該股的ETF數量"},
    )
    fig.update_layout(
        height=400,
        xaxis_tickangle=-45,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(coverage, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# 頁面 4：歷史績效
# ══════════════════════════════════════════════════════════════
elif page == "歷史績效":
    st.title("📈 歷史績效追蹤")

    hist_df = load_sheet(SHEET_HISTORY)

    if hist_df.empty:
        st.warning("歷史庫尚無資料（需累積幾日資料才能顯示趨勢）")
        st.stop()

    if "抓取日期" in hist_df.columns:
        dates = sorted(hist_df["抓取日期"].unique(), reverse=True)
        st.caption(f"資料涵蓋日期：{dates[-1]} ～ {dates[0]}，共 {len(dates)} 個交易日")

    # 每日高分標的數量趨勢
    if "sniper_score" in hist_df.columns and "抓取日期" in hist_df.columns:
        hist_df["sniper_score"] = pd.to_numeric(hist_df["sniper_score"], errors="coerce").fillna(0)
        daily_count = (
            hist_df[hist_df["sniper_score"] >= 5]
            .groupby("抓取日期")
            .size()
            .reset_index(name="高分標的數")
        )
        fig = px.line(
            daily_count,
            x="抓取日期",
            y="高分標的數",
            markers=True,
            title="每日 5分以上標的數量趨勢",
        )
        fig.update_traces(line_color="#1D9E75")
        fig.update_layout(
            height=300,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # 歷史明細表
    display_cols = ["抓取日期","股票代號","股票名稱","sniper_score","label","close"]
    available = [c for c in display_cols if c in hist_df.columns]
    st.dataframe(hist_df[available].sort_values("抓取日期", ascending=False),
                 use_container_width=True, hide_index=True)
