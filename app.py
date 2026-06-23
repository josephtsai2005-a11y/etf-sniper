"""
app.py — ETF 狙擊系統 Streamlit 看板
資料來源：Google Sheets（由 Cloud Run Job 每日更新）
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import os
from datetime import datetime

st.set_page_config(
    page_title="ETF 狙擊系統",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_SMART  = "聰明錢名單"
SHEET_RAW    = "盤後原始數據庫"


# ── Google Sheets 連線 ───────────────────────────────────────
@st.cache_resource
def get_client():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "secrets/gcp-sa.json")
        creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_data(ttl=300)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    try:
        client = get_client()
        spreadsheet_id = (
            st.secrets.get("SPREADSHEET_ID", "")
            or os.environ.get("SPREADSHEET_ID", "")
        )
        ss = client.open_by_key(spreadsheet_id)
        ws = ss.worksheet(sheet_name)
        all_values = ws.get_all_values()

        if not all_values or len(all_values) < 2:
            return pd.DataFrame()

        # 找欄位標題行（含「排名」或「股票代號」的那行）
        header_idx = 0
        for i, row in enumerate(all_values[:5]):
            row_text = " ".join(str(c) for c in row)
            if any(k in row_text for k in ["排名", "股票代號", "股票名稱", "代號"]):
                header_idx = i
                break

        headers = all_values[header_idx]
        data_rows = all_values[header_idx + 1:]
        if not data_rows:
            return pd.DataFrame()

        df = pd.DataFrame(data_rows, columns=headers)
        # 移除全空行
        df = df[df.apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)]
        return df

    except Exception as e:
        st.error(f"無法載入 {sheet_name}: {e}")
        return pd.DataFrame()


def get_update_time(sheet_name: str) -> str:
    """從分頁第一行取得更新時間"""
    try:
        client = get_client()
        spreadsheet_id = (
            st.secrets.get("SPREADSHEET_ID", "")
            or os.environ.get("SPREADSHEET_ID", "")
        )
        ss = client.open_by_key(spreadsheet_id)
        ws = ss.worksheet(sheet_name)
        first_row = ws.row_values(1)
        return first_row[0] if first_row else ""
    except:
        return ""


# ── Sidebar ─────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ 狙擊系統")
    st.caption("投信主力追蹤 · 每日盤後更新")
    st.divider()

    page = st.radio("頁面", [
        "🎯 今日聰明錢名單",
        "📊 ETF 覆蓋分析",
        "📈 個股查詢",
        "🗂️ 原始持股庫",
    ])

    st.divider()

    if st.button("🔄 重新整理", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    update_time = get_update_time(SHEET_SMART)
    if update_time:
        st.caption(f"📅 {update_time}")


# ══════════════════════════════════════════════════════════════
# 頁面 1：今日聰明錢名單
# ══════════════════════════════════════════════════════════════
if page == "🎯 今日聰明錢名單":
    st.title("🎯 今日聰明錢名單")
    st.caption("被最多主動式ETF同時持有的股票 = 專業法人高度共識標的")

    df = load_sheet(SHEET_SMART)

    if df.empty:
        st.warning("尚無資料，請確認 Cloud Run Job 已執行")
        st.stop()

    # 數字欄轉換
    for col in ["持有ETF數", "平均權重%", "排名"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 篩選器
    col1, col2 = st.columns([1, 3])
    with col1:
        min_etf = st.slider("最少被幾檔ETF持有", 1, 20, 3)

    filtered = df[df["持有ETF數"] >= min_etf].copy() if "持有ETF數" in df.columns else df

    # 摘要指標
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("符合標的", f"{len(filtered)} 檔")
    if "持有ETF數" in filtered.columns:
        c2.metric("超高集中 (≥10檔)", f"{(filtered['持有ETF數'] >= 10).sum()} 檔")
        c3.metric("高度共識 (≥5檔)", f"{(filtered['持有ETF數'] >= 5).sum()} 檔")
        c4.metric("多方認同 (≥3檔)", f"{(filtered['持有ETF數'] >= 3).sum()} 檔")

    st.divider()

    # 主表格
    display_cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "平均權重%", "訊號"]
    available = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[available].reset_index(drop=True),
        use_container_width=True,
        height=520,
        hide_index=True,
        column_config={
            "持有ETF數": st.column_config.ProgressColumn(
                "持有ETF數", min_value=0, max_value=34, format="%d 檔"
            ),
            "平均權重%": st.column_config.NumberColumn("平均權重%", format="%.2f%%"),
        }
    )

    # 長條圖：Top 20
    if "持有ETF數" in filtered.columns and "股票名稱" in filtered.columns:
        st.subheader("Top 20 聰明錢集中度")
        top20 = filtered.head(20).copy()
        top20["標籤"] = top20["股票代號"].astype(str) + " " + top20["股票名稱"].astype(str)

        fig = px.bar(
            top20,
            x="持有ETF數",
            y="標籤",
            orientation="h",
            color="持有ETF數",
            color_continuous_scale=["#FFF3CD", "#FF8C00", "#1D9E75"],
            labels={"持有ETF數": "持有該股的ETF數量", "標籤": ""},
        )
        fig.update_layout(
            height=520,
            yaxis={"categoryorder": "total ascending"},
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=150, r=20, t=20, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# 頁面 2：ETF 覆蓋分析
# ══════════════════════════════════════════════════════════════
elif page == "📊 ETF 覆蓋分析":
    st.title("📊 ETF 覆蓋分析")
    st.caption("哪些股票被最多主動式ETF同時納入持股")

    df = load_sheet(SHEET_SMART)
    if df.empty:
        st.warning("尚無資料")
        st.stop()

    for col in ["持有ETF數", "平均權重%"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "持有ETF數" not in df.columns:
        st.warning("資料欄位不符")
        st.stop()

    # 分布圖
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("持有ETF數分布")
        dist = df["持有ETF數"].value_counts().sort_index(ascending=False).head(15)
        fig1 = px.bar(
            x=dist.index, y=dist.values,
            labels={"x": "持有ETF數", "y": "股票數量"},
            color=dist.index,
            color_continuous_scale=["#E6F1FB", "#1D9E75"],
        )
        fig1.update_layout(
            showlegend=False, height=350,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        st.subheader("訊號分布")
        if "訊號" in df.columns:
            signal_counts = df["訊號"].value_counts()
            fig2 = px.pie(
                values=signal_counts.values,
                names=signal_counts.index,
                color_discrete_sequence=["#1D9E75", "#FF8C00", "#185FA5", "#888780"],
                hole=0.5,
            )
            fig2.update_layout(height=350, paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

    # 持有ETF清單展開
    if "持有ETF清單" in df.columns:
        st.subheader("個股被哪些ETF持有")
        top10 = df.head(10).copy()
        for _, row in top10.iterrows():
            code = row.get("股票代號", "")
            name = row.get("股票名稱", "")
            n = int(row.get("持有ETF數", 0))
            etfs = row.get("持有ETF清單", "")
            with st.expander(f"{code} {name}　— 被 {n} 檔ETF持有"):
                st.write(etfs)


# ══════════════════════════════════════════════════════════════
# 頁面 3：個股查詢
# ══════════════════════════════════════════════════════════════
elif page == "📈 個股查詢":
    st.title("📈 個股查詢")

    df = load_sheet(SHEET_SMART)
    raw_df = load_sheet(SHEET_RAW)

    if df.empty:
        st.warning("尚無資料")
        st.stop()

    # 搜尋
    search = st.text_input("輸入股票代號或名稱", placeholder="例如：2330 或 台積電")

    if search:
        mask = (
            df.get("股票代號", pd.Series()).astype(str).str.contains(search) |
            df.get("股票名稱", pd.Series()).astype(str).str.contains(search)
        )
        result = df[mask]
    else:
        result = df.head(20)

    if result.empty:
        st.info("找不到符合的股票")
        st.stop()

    # 顯示結果
    for col in ["持有ETF數", "平均權重%"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    display_cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "平均權重%", "訊號", "持有ETF清單"]
    available = [c for c in display_cols if c in result.columns]
    st.dataframe(result[available].reset_index(drop=True), use_container_width=True, hide_index=True)

    # 個股在各ETF的權重
    if not raw_df.empty and search and "股票代號" in raw_df.columns:
        stock_data = raw_df[raw_df["股票代號"].astype(str).str.contains(search)]
        if not stock_data.empty and "權重%" in stock_data.columns and "ETF代碼" in stock_data.columns:
            st.subheader(f"各ETF中的持股權重")
            stock_data["權重%"] = pd.to_numeric(stock_data["權重%"], errors="coerce")
            fig = px.bar(
                stock_data.sort_values("權重%", ascending=False),
                x="ETF代碼", y="權重%",
                color="權重%",
                color_continuous_scale=["#E6F1FB", "#1D9E75"],
            )
            fig.update_layout(
                height=350,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# 頁面 4：原始持股庫
# ══════════════════════════════════════════════════════════════
elif page == "🗂️ 原始持股庫":
    st.title("🗂️ 原始持股庫")
    st.caption("34 檔主動式ETF完整持股明細")

    raw_df = load_sheet(SHEET_RAW)

    if raw_df.empty:
        st.warning("尚無原始資料")
        st.stop()

    # 篩選器
    col1, col2 = st.columns(2)
    with col1:
        if "ETF代碼" in raw_df.columns:
            etf_list = ["全部"] + sorted(raw_df["ETF代碼"].dropna().unique().tolist())
            selected_etf = st.selectbox("選擇ETF", etf_list)
    with col2:
        search_stock = st.text_input("搜尋股票", placeholder="代號或名稱")

    filtered = raw_df.copy()
    if "ETF代碼" in filtered.columns and selected_etf != "全部":
        filtered = filtered[filtered["ETF代碼"] == selected_etf]
    if search_stock and "股票代號" in filtered.columns:
        mask = (
            filtered["股票代號"].astype(str).str.contains(search_stock) |
            filtered.get("股票名稱", pd.Series()).astype(str).str.contains(search_stock)
        )
        filtered = filtered[mask]

    st.caption(f"顯示 {len(filtered)} 筆")
    st.dataframe(filtered.reset_index(drop=True), use_container_width=True, height=600, hide_index=True)
