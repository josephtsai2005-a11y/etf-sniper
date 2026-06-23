"""
app.py v2 — ETF 狙擊系統 Streamlit 看板
新增：收盤價、漲跌幅%、站上月線、持股市值 欄位
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

SHEET_SMART = "聰明錢名單"
SHEET_RAW   = "盤後原始數據庫"


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
        sid = st.secrets.get("SPREADSHEET_ID", "") or os.environ.get("SPREADSHEET_ID", "")
        ss = client.open_by_key(sid)
        ws = ss.worksheet(sheet_name)
        all_values = ws.get_all_values()

        if not all_values or len(all_values) < 2:
            return pd.DataFrame()

        # 找欄位標題行
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
        df = df[df.apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)]
        return df

    except Exception as e:
        st.error(f"無法載入 {sheet_name}: {e}")
        return pd.DataFrame()


def get_update_time(sheet_name: str) -> str:
    try:
        client = get_client()
        sid = st.secrets.get("SPREADSHEET_ID", "") or os.environ.get("SPREADSHEET_ID", "")
        ss = client.open_by_key(sid)
        ws = ss.worksheet(sheet_name)
        first_row = ws.row_values(1)
        return first_row[0] if first_row else ""
    except:
        return ""


def num_cols(df: pd.DataFrame, cols: list):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def format_change(val):
    """漲跌幅顏色格式"""
    try:
        v = float(val)
        return f"{'🔴' if v > 0 else '🟢' if v < 0 else '—'} {v:+.2f}%"
    except:
        return str(val)


# ── Sidebar ──────────────────────────────────────────────────
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

    # 數字轉換
    num_cols(df, ["持有ETF數", "平均權重%", "排名", "收盤價", "漲跌幅%", "MA20", "持股市值(萬)"])

    # 篩選
    col1, col2 = st.columns([1, 3])
    with col1:
        min_etf = st.slider("最少被幾檔ETF持有", 1, 20, 3)
    filtered = df[df["持有ETF數"] >= min_etf].copy() if "持有ETF數" in df.columns else df

    # 摘要指標
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("符合標的", f"{len(filtered)} 檔")
    if "持有ETF數" in filtered.columns:
        c2.metric("超高集中 (≥10檔)", f"{(filtered['持有ETF數'] >= 10).sum()} 檔")
        c3.metric("高度共識 (≥5檔)",  f"{(filtered['持有ETF數'] >= 5).sum()} 檔")
        c4.metric("多方認同 (≥3檔)",  f"{(filtered['持有ETF數'] >= 3).sum()} 檔")

    # 加漲跌幅顏色欄
    if "漲跌幅%" in filtered.columns:
        filtered["漲跌"] = filtered["漲跌幅%"].apply(format_change)

    st.divider()

    # 主表格 — 含股價欄位
    display_cols = [
        "排名", "股票代號", "股票名稱",
        "持有ETF數", "平均權重%", "訊號",
        "收盤價", "漲跌", "站上MA20", "持股市值(萬)"
    ]
    available = [c for c in display_cols if c in filtered.columns]

    col_config = {
        "持有ETF數": st.column_config.ProgressColumn(
            "持有ETF數", min_value=0, max_value=34, format="%d 檔"
        ),
        "平均權重%":  st.column_config.NumberColumn("平均權重%",  format="%.2f%%"),
        "收盤價":     st.column_config.NumberColumn("收盤價",     format="%.1f"),
        "持股市值(萬)": st.column_config.NumberColumn("持股市值(萬)", format="%.0f 萬"),
        "站上MA20":   st.column_config.CheckboxColumn("站上月線"),
    }

    st.dataframe(
        filtered[available].reset_index(drop=True),
        use_container_width=True,
        height=520,
        hide_index=True,
        column_config=col_config,
    )

    # 漲跌幅 vs 持有ETF數 散點圖（若有股價）
    if "漲跌幅%" in filtered.columns and "收盤價" in filtered.columns:
        has_price = filtered[filtered["收盤價"].notna() & filtered["漲跌幅%"].notna()]
        if not has_price.empty:
            st.subheader("漲跌幅 vs 聰明錢集中度")
            fig_scatter = px.scatter(
                has_price,
                x="持有ETF數",
                y="漲跌幅%",
                size="平均權重%",
                color="漲跌幅%",
                color_continuous_scale=["#E24B4A", "#CCCCCC", "#1D9E75"],
                hover_data=["股票代號", "股票名稱", "收盤價"],
                labels={"持有ETF數": "ETF持有數", "漲跌幅%": "今日漲跌幅%"},
            )
            fig_scatter.add_hline(y=0, line_dash="dot", line_color="gray")
            fig_scatter.update_layout(
                height=380,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

    # Top 20 長條圖
    if "持有ETF數" in filtered.columns and "股票名稱" in filtered.columns:
        st.subheader("Top 20 聰明錢集中度")
        top20 = filtered.head(20).copy()
        top20["標籤"] = top20["股票代號"].astype(str) + " " + top20["股票名稱"].astype(str)
        fig = px.bar(
            top20, x="持有ETF數", y="標籤", orientation="h",
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

    num_cols(df, ["持有ETF數", "平均權重%"])

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
        fig1.update_layout(showlegend=False, height=350,
                           plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        st.subheader("訊號分布")
        if "訊號" in df.columns:
            signal_counts = df["訊號"].value_counts()
            fig2 = px.pie(
                values=signal_counts.values, names=signal_counts.index,
                color_discrete_sequence=["#1D9E75", "#FF8C00", "#185FA5", "#888780"],
                hole=0.5,
            )
            fig2.update_layout(height=350, paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

    # 站上月線統計（若有）
    if "站上MA20" in df.columns:
        st.subheader("站上月線統計")
        above = df["站上MA20"].astype(str).str.lower().isin(["true", "1", "是", "yes"]).sum()
        total_with_price = df["站上MA20"].astype(str).ne("").sum()
        ca, cb, cc = st.columns(3)
        ca.metric("站上月線", f"{above} 檔")
        cb.metric("月線以下", f"{total_with_price - above} 檔")
        cc.metric("比例", f"{above/total_with_price*100:.0f}%" if total_with_price else "—")

    # 個股被哪些ETF持有
    if "持有ETF清單" in df.columns:
        st.subheader("個股被哪些ETF持有（Top 10）")
        for _, row in df.head(10).iterrows():
            code  = row.get("股票代號", "")
            name  = row.get("股票名稱", "")
            n     = row.get("持有ETF數", 0)
            etfs  = row.get("持有ETF清單", "")
            close = row.get("收盤價", "")
            chg   = row.get("漲跌幅%", "")
            label = f"{code} {name}　— 被 {n} 檔ETF持有"
            if close:
                label += f"　收盤 {close}"
            if chg:
                try:
                    label += f"　漲跌 {float(chg):+.2f}%"
                except:
                    pass
            with st.expander(label):
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

    num_cols(result, ["持有ETF數", "平均權重%", "收盤價", "漲跌幅%", "持股市值(萬)"])

    display_cols = [
        "排名", "股票代號", "股票名稱", "持有ETF數", "平均權重%",
        "訊號", "收盤價", "漲跌幅%", "MA20", "站上MA20", "持股市值(萬)", "持有ETF清單"
    ]
    available = [c for c in display_cols if c in result.columns]
    st.dataframe(result[available].reset_index(drop=True),
                 use_container_width=True, hide_index=True)

    # 個股在各ETF的權重圖
    if not raw_df.empty and search and "股票代號" in raw_df.columns:
        stock_data = raw_df[
            raw_df["股票代號"].astype(str).str.contains(search) |
            raw_df.get("股票名稱", pd.Series()).astype(str).str.contains(search)
        ]
        if not stock_data.empty and "權重%" in stock_data.columns and "ETF代碼" in stock_data.columns:
            st.subheader("各ETF中的持股權重")
            stock_data = stock_data.copy()
            stock_data["權重%"] = pd.to_numeric(stock_data["權重%"], errors="coerce")
            fig = px.bar(
                stock_data.sort_values("權重%", ascending=False),
                x="ETF代碼", y="權重%",
                color="權重%",
                color_continuous_scale=["#E6F1FB", "#1D9E75"],
                labels={"ETF代碼": "ETF", "權重%": "持股權重%"},
            )
            fig.update_layout(height=350,
                              plot_bgcolor="rgba(0,0,0,0)",
                              paper_bgcolor="rgba(0,0,0,0)")
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

    col1, col2 = st.columns(2)
    with col1:
        if "ETF代碼" in raw_df.columns:
            etf_list = ["全部"] + sorted(raw_df["ETF代碼"].dropna().unique().tolist())
            selected_etf = st.selectbox("選擇ETF", etf_list)
        else:
            selected_etf = "全部"
    with col2:
        search_stock = st.text_input("搜尋股票", placeholder="代號或名稱")

    filtered = raw_df.copy()
    if "ETF代碼" in filtered.columns and selected_etf != "全部":
        filtered = filtered[filtered["ETF代碼"] == selected_etf]
    if search_stock:
        mask = pd.Series(False, index=filtered.index)
        for col in ["股票代號", "股票名稱"]:
            if col in filtered.columns:
                mask |= filtered[col].astype(str).str.contains(search_stock, na=False)
        filtered = filtered[mask]

    st.caption(f"顯示 {len(filtered)} 筆")
    st.dataframe(filtered.reset_index(drop=True),
                 use_container_width=True, height=600, hide_index=True)
