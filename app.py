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

SHEET_SMART  = "聰明錢名單"
SHEET_RAW    = "盤後原始數據庫"
SHEET_DIFF   = "今日訊號"
SHEET_DETAIL = "持股異動明細"
SHEET_TREND  = "題材趨勢"
SHEET_CROSS  = "新聞×籌碼交叉"
SHEET_INST   = "三大法人"
SHEET_MULTI  = "多方驗證名單"
SHEET_RETAIL = "散戶情緒"
SHEET_POS    = "題材位置"
SHEET_FUND   = "基本面資料"


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

    st.caption("🕒 15:30 核心資料")
    page = st.radio("頁面", [
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "📊 持股異動明細",
        "— 16:45 法人資料 —",
        "🏦 三大法人",
        "📈 基本面資料",
        "— 21:00 新聞分析 —",
        "🔗 新聞×籌碼交叉",
        "📰 題材趨勢",
        "🎯 題材位置",
        "📱 散戶情緒",
        "— 其他 —",
        "📊 ETF 覆蓋分析",
        "🔍 個股查詢",
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
# 頁面：多方驗證名單（最重要的頁面）
# ══════════════════════════════════════════════════════════════
# 分隔線項目不做任何事
if page.startswith("—"):
    st.info("請選擇上方的功能頁面")
    st.stop()

if page == "🏆 多方驗證名單":
    st.title("🏆 多方驗證名單")
    st.caption("ETF持股 × 三大法人 × 新聞題材 × 技術面 — 多重確認的高機率標的")

    multi_df = load_sheet(SHEET_MULTI)

    if multi_df.empty:
        st.warning("尚無多方驗證資料（需等今日 16:30 後三大法人資料入庫）")
        st.info("💡 系統每日 15:30 自動執行，16:30 後法人資料加入，產出完整驗證名單")

        # 先顯示聰明錢名單作為替代
        st.subheader("目前可參考：今日聰明錢名單")
        smart_df = load_sheet(SHEET_SMART)
        if not smart_df.empty:
            num_cols(smart_df, ["持有ETF數","平均權重%"])
            cols = ["排名","股票代號","股票名稱","持有ETF數","平均權重%","訊號"]
            avail = [c for c in cols if c in smart_df.columns]
            st.dataframe(smart_df[avail].head(15), use_container_width=True, hide_index=True)
        st.stop()

    num_cols(multi_df, ["持有ETF數","買超法人數","綜合評分","三大合計","收盤價","漲跌幅%"])

    # 摘要
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("總標的", f"{len(multi_df)} 檔")
    c2.metric("🔥 三大齊買", f"{(multi_df.get('買超法人數',pd.Series())==3).sum()} 檔")
    c3.metric("⭐ 綜合評分≥7", f"{(pd.to_numeric(multi_df.get('綜合評分',pd.Series()),errors='coerce')>=7).sum()} 檔")
    c4.metric("✅ 多重確認", f"{multi_df.get('多方驗證',pd.Series()).str.count('✅').ge(3).sum()} 檔")

    st.divider()

    # 篩選
    col1, col2 = st.columns(2)
    with col1:
        min_score = st.slider("最低綜合評分", 0.0, 10.0, 5.0, 0.5)
    with col2:
        min_inst = st.slider("最少買超法人數", 0, 3, 1)

    filtered = multi_df.copy()
    if "綜合評分" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["綜合評分"],errors="coerce").fillna(0) >= min_score]
    if "買超法人數" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["買超法人數"],errors="coerce").fillna(0) >= min_inst]

    display_cols = ["排名","股票代號","股票名稱","持有ETF數","買超法人數",
                    "法人訊號","綜合評分","多方驗證","年增率%","營收訊號","三大合計","收盤價","漲跌幅%"]
    avail = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[avail].reset_index(drop=True),
        use_container_width=True, height=520, hide_index=True,
        column_config={
            "持有ETF數":  st.column_config.ProgressColumn("ETF持有", min_value=0, max_value=34, format="%d"),
            "買超法人數": st.column_config.ProgressColumn("買超法人", min_value=0, max_value=3, format="%d"),
            "綜合評分":   st.column_config.NumberColumn("綜合評分", format="%.1f ⭐"),
            "三大合計":   st.column_config.NumberColumn("法人合計(張)", format="%.0f"),
            "收盤價":     st.column_config.NumberColumn("收盤價", format="%.1f"),
            "漲跌幅%":    st.column_config.NumberColumn("漲跌幅%", format="%.2f%%"),
            "年增率%":    st.column_config.NumberColumn("月營收年增率", format="%.1f%%"),
        }
    )

    # 綜合評分散點圖
    if "綜合評分" in filtered.columns and "持有ETF數" in filtered.columns:
        plot_df = filtered[filtered["綜合評分"].notna() & filtered["持有ETF數"].notna()].copy()
        if not plot_df.empty:
            st.subheader("綜合評分分布")
            fig = px.scatter(
                plot_df,
                x="持有ETF數", y="綜合評分",
                color="法人訊號" if "法人訊號" in plot_df.columns else None,
                text="股票名稱" if "股票名稱" in plot_df.columns else None,
                size_max=20,
                labels={"持有ETF數":"ETF持有數","綜合評分":"綜合評分"},
            )
            fig.update_traces(textposition="top center", textfont_size=10)
            fig.add_hline(y=7, line_dash="dot", line_color="#1D9E75", opacity=0.7,
                          annotation_text="評分7分門檻")
            fig.update_layout(height=400, plot_bgcolor="rgba(0,0,0,0)",
                              paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# 頁面：三大法人
# ══════════════════════════════════════════════════════════════
elif page == "🏦 三大法人":
    st.title("🏦 三大法人買賣超")
    st.caption("外資 + 投信 + 自營商 每日買賣超彙整")

    inst_df = load_sheet(SHEET_INST)

    if inst_df.empty:
        st.warning("尚無三大法人資料（每日 16:30 後更新）")
        st.stop()

    num_cols(inst_df, ["外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數"])

    # 摘要
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("三大齊買", f"{(inst_df.get('買超法人數',pd.Series())==3).sum()} 檔")
    c2.metric("外資買超", f"{(inst_df.get('外資買賣超',pd.Series())>0).sum()} 檔")
    c3.metric("投信買超", f"{(inst_df.get('投信買賣超',pd.Series())>0).sum()} 檔")
    c4.metric("自營買超", f"{(inst_df.get('自營買賣超',pd.Series())>0).sum()} 檔")

    st.divider()

    signal_filter = st.multiselect("篩選法人訊號",
        ["🔥 三大齊買","⚡ 外資+投信","⚡ 外資主導","⚡ 雙向買超","🌱 投信單買","🌱 外資單買"],
        default=["🔥 三大齊買","⚡ 外資+投信","⚡ 外資主導"])

    filtered = inst_df.copy()
    if signal_filter and "法人訊號" in filtered.columns:
        filtered = filtered[filtered["法人訊號"].isin(signal_filter)]

    display_cols = ["排名","股票代號","外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數","法人訊號"]
    avail = [c for c in display_cols if c in filtered.columns]
    st.dataframe(filtered[avail].reset_index(drop=True),
                 use_container_width=True, height=500, hide_index=True,
                 column_config={
                     "外資買賣超": st.column_config.NumberColumn("外資(張)", format="%.0f"),
                     "投信買賣超": st.column_config.NumberColumn("投信(張)", format="%.0f"),
                     "自營買賣超": st.column_config.NumberColumn("自營(張)", format="%.0f"),
                     "三大合計":   st.column_config.NumberColumn("合計(張)", format="%.0f"),
                 })

    # 資金流向長條圖
    if "三大合計" in filtered.columns and not filtered.empty:
        st.subheader("三大法人資金流向")
        top = pd.concat([
            filtered.nlargest(10,"三大合計"),
            filtered.nsmallest(5,"三大合計")
        ]).drop_duplicates()
        top["標籤"] = top["股票代號"].astype(str)
        fig = px.bar(top.sort_values("三大合計"), x="三大合計", y="標籤",
            orientation="h", color="三大合計",
            color_continuous_scale=["#E24B4A","#CCCCCC","#1D9E75"],
            labels={"三大合計":"三大法人合計(張)","標籤":""})
        fig.add_vline(x=0, line_dash="dot", line_color="gray")
        fig.update_layout(height=400, showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# 頁面 0：今日訊號
# ══════════════════════════════════════════════════════════════
elif page == "⚡ 今日訊號":
    st.title("⚡ 今日訊號")
    st.caption("今日 vs 昨日持股變化 — 加碼/減碼/新增/清倉")

    diff_df = load_sheet(SHEET_DIFF)

    if diff_df.empty:
        st.warning("尚無差異比對資料，需要兩天資料才能產出（明天15:30後自動更新）")
        st.info("💡 今日是系統第一天執行，明天盤後即可看到今日vs昨日的完整比對")
        st.stop()

    num_cols(diff_df, ["加碼ETF數","減碼ETF數","新增ETF數","清倉ETF數","總變動張數","總資金動向","收盤價"])

    # 摘要
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔺 加碼", f"{diff_df.get('主要狀態', pd.Series()).str.contains('加碼').sum()} 檔")
    c2.metric("🆕 新增", f"{diff_df.get('主要狀態', pd.Series()).str.contains('新增').sum()} 檔")
    c3.metric("🔻 減碼", f"{diff_df.get('主要狀態', pd.Series()).str.contains('減碼').sum()} 檔")
    c4.metric("🗑️ 清倉", f"{diff_df.get('主要狀態', pd.Series()).str.contains('清倉').sum()} 檔")

    st.divider()

    # 篩選器
    status_filter = st.multiselect(
        "篩選狀態",
        ["🔺 加碼", "🆕 新增", "🔻 減碼", "🗑️ 清倉", "🔀 混合"],
        default=["🔺 加碼", "🆕 新增"],
    )

    filtered = diff_df.copy()
    if status_filter and "主要狀態" in filtered.columns:
        filtered = filtered[filtered["主要狀態"].isin(status_filter)]

    # 主表格
    display_cols = ["排名","股票代號","股票名稱","主要狀態",
                    "加碼ETF數","減碼ETF數","新增ETF數","清倉ETF數",
                    "總變動張數","平均權重變動%","總資金動向","收盤價"]
    available = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[available].reset_index(drop=True),
        use_container_width=True,
        height=500,
        hide_index=True,
        column_config={
            "總變動張數":    st.column_config.NumberColumn("總變動張數", format="%.1f 張"),
            "平均權重變動%": st.column_config.NumberColumn("權重變動%", format="%.2f%%"),
            "總資金動向":   st.column_config.NumberColumn("資金動向(萬)", format="%.1f 萬"),
            "收盤價":       st.column_config.NumberColumn("收盤價", format="%.1f"),
            "加碼ETF數":    st.column_config.NumberColumn("加碼ETF", format="%d"),
            "減碼ETF數":    st.column_config.NumberColumn("減碼ETF", format="%d"),
        }
    )

    # 資金動向長條圖
    if "總資金動向" in filtered.columns and "股票名稱" in filtered.columns:
        st.subheader("資金動向排行")
        flow = filtered[filtered["總資金動向"].notna()].copy()
        flow["標籤"] = flow["股票代號"].astype(str) + " " + flow["股票名稱"].astype(str)
        flow["顏色"] = flow["總資金動向"].apply(lambda x: "#1D9E75" if x > 0 else "#E24B4A")

        top_flow = pd.concat([
            flow.nlargest(10, "總資金動向"),
            flow.nsmallest(10, "總資金動向")
        ]).drop_duplicates()

        fig = px.bar(
            top_flow.sort_values("總資金動向"),
            x="總資金動向", y="標籤",
            orientation="h",
            color="總資金動向",
            color_continuous_scale=["#E24B4A", "#CCCCCC", "#1D9E75"],
            labels={"總資金動向": "資金動向(萬元)", "標籤": ""},
        )
        fig.add_vline(x=0, line_dash="dot", line_color="gray")
        fig.update_layout(
            height=500,
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=150, r=20, t=20, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════
# 頁面：題材趨勢
# ══════════════════════════════════════════════════════════════
elif page == "📰 題材趨勢":
    st.title("📰 題材趨勢")
    st.caption("關鍵字生命週期追蹤 — 萌芽 / 成長 / 爆發 / 衰退")

    trend_df  = load_sheet(SHEET_TREND)
    news_hist = load_sheet("新聞歷史庫")

    if trend_df.empty:
        st.warning("尚無題材趨勢資料，等待今日 15:30 自動執行後產出")
        st.stop()

    num_cols(trend_df, ["今日篇數","近3日均","近7日均","成長率%","峰值篇數","累計篇數"])

    # ── 從新聞歷史庫建立時序資料 ──────────────────────────────
    timeseries_data = {}
    if not news_hist.empty and "抓取日期" in news_hist.columns and "命中關鍵字" in news_hist.columns:
        rows = []
        for _, r in news_hist.iterrows():
            date = str(r["抓取日期"]).strip()
            kws  = [k.strip() for k in str(r["命中關鍵字"]).split(",") if k.strip()]
            for kw in kws:
                rows.append({"日期": date, "關鍵字": kw})

        if rows:
            df_kw = pd.DataFrame(rows)
            df_kw["日期"] = pd.to_datetime(df_kw["日期"], format="%Y%m%d", errors="coerce")
            df_kw = df_kw.dropna(subset=["日期"])

            pivot = df_kw.groupby(["日期","關鍵字"]).size().unstack(fill_value=0)
            all_dates = pd.date_range(pivot.index.min(), pivot.index.max(), freq="D")
            pivot = pivot.reindex(all_dates, fill_value=0)

            for kw in pivot.columns:
                timeseries_data[kw] = pivot[kw]

    has_timeseries = len(timeseries_data) > 0

    # ── 摘要 ──────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔥 爆發中", f"{trend_df['階段'].str.contains('爆發',na=False).sum()} 個")
    c2.metric("⚡ 成長中", f"{trend_df['階段'].str.contains('成長',na=False).sum()} 個")
    c3.metric("🌱 萌芽中", f"{trend_df['階段'].str.contains('萌芽',na=False).sum()} 個")
    c4.metric("📉 衰退中", f"{trend_df['階段'].str.contains('衰退',na=False).sum()} 個")

    if has_timeseries:
        days = len(list(timeseries_data.values())[0])
        st.caption(f"📅 資料累積：{days} 天（7天後趨勢更準確）")
    else:
        st.info("💡 今日為第 1 天，明天 15:30 後折線圖將開始顯示趨勢")

    st.divider()

    # ── 圖一：氣泡圖 ──────────────────────────────────────────
    st.subheader("① 熱度氣泡圖 — 全局一覽")
    st.caption("X軸=今日篇數  Y軸=成長率%  氣泡大小=峰值篇數")

    bubble_df = trend_df[pd.to_numeric(trend_df["今日篇數"], errors="coerce").fillna(0) > 0].copy()
    if bubble_df.empty:
        bubble_df = trend_df.copy()

    stage_colors = {"🔥 爆發":"#E24B4A","⚡ 成長":"#FF8C00","🌱 萌芽":"#1D9E75","📉 衰退":"#888780","💤 沉寂":"#CCCCCC"}
    num_cols(bubble_df, ["今日篇數","成長率%","峰值篇數"])
    bubble_df["峰值篇數"] = bubble_df["峰值篇數"].fillna(1).clip(lower=1)

    fig_bubble = px.scatter(
        bubble_df, x="今日篇數", y="成長率%",
        size="峰值篇數", color="階段", text="關鍵字",
        color_discrete_map={k:v for k,v in stage_colors.items()},
        size_max=60,
        labels={"今日篇數":"今日篇數","成長率%":"7日成長率%"},
    )
    fig_bubble.update_traces(textposition="top center", textfont_size=11)
    fig_bubble.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig_bubble.update_layout(height=440, plot_bgcolor="rgba(0,0,0,0)",
                              paper_bgcolor="rgba(0,0,0,0)", hovermode="closest")
    st.plotly_chart(fig_bubble, use_container_width=True)

    st.divider()

    # ── 圖二：時序折線圖 ──────────────────────────────────────
    st.subheader("② 關鍵字時序折線圖")

    if has_timeseries:
        all_keywords = list(timeseries_data.keys())
        priority_kws = ["CoWoS","AI伺服器","NVIDIA","Fed","液冷散熱","HBM","台幣匯率"]
        default_kws  = [k for k in priority_kws if k in all_keywords][:4]
        if not default_kws:
            default_kws = all_keywords[:4]

        selected_kws = st.multiselect(
            "選擇追蹤的關鍵字（最多5個）",
            all_keywords, default=default_kws, max_selections=5,
        )

        if selected_kws:
            ts_frames = []
            for kw in selected_kws:
                if kw in timeseries_data:
                    for date, val in timeseries_data[kw].items():
                        ts_frames.append({"日期": date, "關鍵字": kw, "篇數": int(val)})
            if ts_frames:
                ts_df = pd.DataFrame(ts_frames)
                fig_line = px.line(ts_df, x="日期", y="篇數", color="關鍵字",
                    markers=True,
                    color_discrete_sequence=["#E24B4A","#FF8C00","#1D9E75","#185FA5","#534AB7"],
                    labels={"篇數":"新聞篇數","日期":""})
                fig_line.update_layout(height=360, plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02))
                st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("📈 折線圖將於明天 15:30 後開始顯示（需要 2 天以上資料）")

    st.divider()

    # ── 圖三：Exploding Topics 風格表格 ───────────────────────
    st.subheader("③ 題材生命週期表")

    stage_filter = st.multiselect("篩選階段",
        ["🔥 爆發","⚡ 成長","🌱 萌芽","📉 衰退"],
        default=["🔥 爆發","⚡ 成長","🌱 萌芽"])
    filtered = trend_df.copy()
    if stage_filter:
        filtered = filtered[filtered["階段"].apply(
            lambda s: any(f in str(s) for f in stage_filter))]

    def make_sparkline(kw):
        if kw not in timeseries_data:
            return '<span style="color:#ccc;font-size:11px">（累積中）</span>'
        vals = timeseries_data[kw].values[-7:]
        if len(vals) == 0 or max(vals) == 0:
            return '<span style="color:#ccc;font-size:11px">（無資料）</span>'
        max_v = max(vals)
        bars = []
        for v in vals:
            h = max(2, int(v/max_v*28))
            c = "#E24B4A" if v>=max_v*0.8 else "#FF8C00" if v>=max_v*0.4 else "#C8E6C9"
            bars.append(f'<span style="display:inline-block;width:7px;height:{h}px;background:{c};margin:0 1px;border-radius:2px;vertical-align:bottom"></span>')
        return "".join(bars)

    scm = {"爆發":"#E24B4A","成長":"#FF8C00","萌芽":"#1D9E75","衰退":"#888780"}

    st.markdown("""<div style="display:flex;padding:4px 14px;font-size:11px;color:#999;font-weight:600">
        <div style="width:120px">關鍵字</div>
        <div style="width:100px">7日趨勢</div>
        <div style="width:110px">階段</div>
        <div style="width:80px">成長率</div>
        <div>今日篇數</div>
    </div>""", unsafe_allow_html=True)

    for _, row in filtered.head(20).iterrows():
        kw    = str(row.get("關鍵字",""))
        stage = str(row.get("階段",""))
        gr    = float(row.get("成長率%") or 0)
        today = int(float(row.get("今日篇數") or 0))
        spark = make_sparkline(kw)
        sc    = next((v for k,v in scm.items() if k in stage),"#888")
        gc    = "#E24B4A" if gr>0 else "#888780"
        gs    = "↑" if gr>0 else "↓"
        bg    = "#FFF8F8" if "爆發" in stage else "#FFFBF5" if "成長" in stage else "#F8FFF8" if "萌芽" in stage else "#FAFAFA"

        st.markdown(f"""<div style="display:flex;align-items:center;padding:8px 14px;margin:3px 0;
            border-radius:8px;border:0.5px solid #eee;background:{bg};">
            <div style="width:120px;font-weight:600;font-size:14px">{kw}</div>
            <div style="width:100px;display:flex;align-items:flex-end;height:32px">{spark}</div>
            <div style="width:110px;font-size:12px;color:{sc};font-weight:600">{stage}</div>
            <div style="width:80px;font-size:13px;color:{gc};font-weight:500">{gs}{abs(gr):.0f}%</div>
            <div style="font-size:12px;color:#666">📰 {today} 篇</div>
        </div>""", unsafe_allow_html=True)
# ══════════════════════════════════════════════════════════════
# 頁面：新聞×籌碼交叉
# ══════════════════════════════════════════════════════════════
elif page == "🔗 新聞×籌碼交叉":
    st.title("🔗 新聞 × 籌碼 交叉驗證")
    st.caption("新聞題材發酵 + 法人同步建倉 = 高機率標的")

    cross_df = load_sheet(SHEET_CROSS)

    if cross_df.empty:
        st.warning("尚無交叉驗證資料（需累積新聞資料後自動產出）")
        st.stop()

    num_cols(cross_df, ["持有ETF數", "熱詞數", "最高成長率%"])

    st.info("💡 同時滿足「新聞題材發酵」+ 「多檔ETF持有」的個股，是最值得關注的標的")

    # 摘要
    c1, c2 = st.columns(2)
    c1.metric("題材+籌碼雙重確認", f"{len(cross_df)} 檔")
    c2.metric("高ETF共識(≥5檔)", f"{(pd.to_numeric(cross_df.get('持有ETF數',pd.Series()), errors='coerce') >= 5).sum()} 檔")

    st.divider()

    display_cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "訊號",
                    "相關熱詞", "熱詞數", "最高成長率%", "題材階段", "綜合強度"]
    available = [c for c in display_cols if c in cross_df.columns]

    st.dataframe(
        cross_df[available].reset_index(drop=True),
        use_container_width=True,
        height=500,
        hide_index=True,
        column_config={
            "持有ETF數":   st.column_config.ProgressColumn("ETF持有數", min_value=0, max_value=34, format="%d"),
            "最高成長率%": st.column_config.NumberColumn("題材成長率%", format="%.1f%%"),
        }
    )

# ══════════════════════════════════════════════════════════════
# 頁面：散戶情緒（Google Trends）
# ══════════════════════════════════════════════════════════════
elif page == "📱 散戶情緒":
    st.title("📱 散戶情緒指標")
    st.caption("Google Trends 搜尋量 — 散戶關注度越低，越是法人布局期")

    retail_df = load_sheet(SHEET_RETAIL)
    pos_df    = load_sheet(SHEET_POS)

    if retail_df.empty:
        st.warning("尚無散戶情緒資料")
        st.stop()

    num_cols(retail_df, ["當前搜尋量","近3日均","近7日均","搜尋成長%","峰值","相對峰值%"])

    # 摘要
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💤 最佳布局", f"{retail_df['散戶關注度'].str.contains('淡漠',na=False).sum()} 個")
    c2.metric("🌱 法人期",   f"{retail_df['散戶關注度'].str.contains('萌芽',na=False).sum()} 個")
    c3.metric("⚡ 注意",     f"{retail_df['散戶關注度'].str.contains('追進',na=False).sum()} 個")
    c4.metric("🔥 危險",     f"{retail_df['散戶關注度'].str.contains('爆買',na=False).sum()} 個")

    st.divider()

    # 主表格
    display_cols = ["排名","主題","散戶關注度","進場訊號","當前搜尋量","搜尋成長%","相對峰值%"]
    avail = [c for c in display_cols if c in retail_df.columns]

    # 顏色標記
    def highlight_signal(val):
        if "最佳" in str(val) or "法人期" in str(val):
            return "background-color: #E8F5E9"
        elif "注意" in str(val) or "謹慎" in str(val):
            return "background-color: #FFF3E0"
        elif "危險" in str(val) or "爆買" in str(val):
            return "background-color: #FFEBEE"
        return ""

    st.dataframe(
        retail_df[avail].reset_index(drop=True),
        use_container_width=True, height=420, hide_index=True,
        column_config={
            "當前搜尋量":  st.column_config.ProgressColumn("搜尋量", min_value=0, max_value=100, format="%d"),
            "相對峰值%":   st.column_config.NumberColumn("相對峰值%", format="%.0f%%"),
            "搜尋成長%":   st.column_config.NumberColumn("搜尋成長%", format="%.1f%%"),
        }
    )

    # 散點圖：搜尋量 vs 進場訊號
    st.subheader("散戶關注度 vs 搜尋趨勢")
    if "搜尋成長%" in retail_df.columns and "當前搜尋量" in retail_df.columns:
        stage_colors = {
            "💤 散戶淡漠": "#1D9E75",
            "🌱 散戶萌芽": "#4CAF50",
            "⚡ 散戶追進": "#FF8C00",
            "🔥 散戶爆買": "#E24B4A",
            "📉 散戶退場": "#888780",
        }
        fig = px.scatter(
            retail_df, x="當前搜尋量", y="搜尋成長%",
            color="散戶關注度", text="主題",
            color_discrete_map=stage_colors,
            size_max=20,
            labels={"當前搜尋量":"Google搜尋量（0-100）","搜尋成長%":"7日搜尋成長%"},
        )
        fig.update_traces(textposition="top center", textfont_size=11)
        fig.add_vline(x=30, line_dash="dot", line_color="orange",
                      annotation_text="散戶開始注意", opacity=0.7)
        fig.add_vline(x=60, line_dash="dot", line_color="red",
                      annotation_text="散戶爆買警戒", opacity=0.7)
        fig.update_layout(height=400, plot_bgcolor="rgba(0,0,0,0)",
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # 題材位置交叉表
    if not pos_df.empty:
        st.subheader("📍 題材位置分析（新聞 × 搜尋）")
        st.caption("新聞熱但搜尋冷 = 法人期 = 最佳進場時機")
        pos_display = ["排名","主題","題材位置","新聞篇數","當前搜尋量"]
        pos_avail = [c for c in pos_display if c in pos_df.columns]
        if pos_avail:
            st.dataframe(pos_df[pos_avail].reset_index(drop=True),
                        use_container_width=True, height=350, hide_index=True)


# ══════════════════════════════════════════════════════════════
# 頁面 1：今日聰明錢名單
# ══════════════════════════════════════════════════════════════
elif page == "🎯 今日聰明錢名單":
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

elif page == "📊 持股異動明細":
    st.title("📊 持股異動明細")
    st.caption("ETF 每日持股變動明細")
    df = load_sheet("持股異動明細")
    if df.empty:
        st.warning("尚無持股異動明細（每日 15:30 後更新）")
    else:
        st.dataframe(df, use_container_width=True)

elif page == "📈 基本面資料":
    st.title("📈 基本面資料")
    st.caption("月營收、本益比、成長率")
    df = load_sheet("基本面資料")
    if df.empty:
        st.warning("尚無基本面資料（每日 16:45 後更新）")
    else:
        st.dataframe(df, use_container_width=True)

elif page == "🎯 題材位置":
    st.title("🎯 題材位置")
    st.caption("新聞題材與散戶情緒交叉分析")
    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        st.dataframe(df, use_container_width=True)
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
