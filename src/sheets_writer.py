"""
sheets_writer.py
將分析結果寫入 Google Sheets 四個分頁
需要: gspread, google-auth
"""
import gspread
import pandas as pd
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials
from typing import Optional
import os

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 四個分頁名稱
SHEET_RAW       = "盤後原始數據庫"
SHEET_ANALYSIS  = "籌碼分析庫"
SHEET_SNIPER    = "狙擊名單"
SHEET_HISTORY   = "歷史回測庫"


def get_client(credentials_path: Optional[str] = None) -> gspread.Client:
    """
    建立 Google Sheets 連線
    credentials_path: service account JSON 路徑
    若未指定，從環境變數 GOOGLE_APPLICATION_CREDENTIALS 讀取
    """
    cred_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        raise ValueError("請設定 GOOGLE_APPLICATION_CREDENTIALS 環境變數或傳入 credentials_path")

    creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_spreadsheet(client: gspread.Client, spreadsheet_id: str) -> gspread.Spreadsheet:
    """取得試算表，確保四個分頁都存在"""
    try:
        ss = client.open_by_key(spreadsheet_id)
        log.info(f"已開啟試算表：{ss.title}")
    except gspread.exceptions.SpreadsheetNotFound:
        raise ValueError(f"找不到試算表 ID: {spreadsheet_id}，請確認 ID 正確且已共用給 Service Account")

    return ss


def write_raw_data(ss: gspread.Spreadsheet, df: pd.DataFrame, trade_date: str):
    """寫入盤後原始數據庫（每日追加）"""
    ws = ss.worksheet(SHEET_RAW)
    df = df.copy()
    df["寫入時間"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    existing = ws.get_all_values()
    if not existing or existing == [[]]:
        # 首次寫入，加標題
        ws.append_row(df.columns.tolist())

    rows = df.fillna("").values.tolist()
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    log.info(f"原始資料寫入完成：{len(df)} 筆 → {SHEET_RAW}")


def write_analysis(ss: gspread.Spreadsheet, df: pd.DataFrame, trade_date: str):
    """寫入籌碼分析庫"""
    ws = ss.worksheet(SHEET_ANALYSIS)

    cols = [
        "抓取日期", "股票代號", "股票名稱", "ETF代碼", "etf_count",
        "sniper_score", "label",
        "s1_trust_cum", "s2_consec_buy", "s3_above_ma20",
        "s4_amount", "s5_vol_ratio", "s6_amplitude", "s7_fund_growth", "s8_weight",
        "trust_cum_5d", "consec_buy_days", "above_ma20",
        "volume_ratio", "fund_growth_5d", "amplitude",
        "close", "amount", "weight_warning",
    ]
    available = [c for c in cols if c in df.columns]
    out = df[available].copy()
    out["抓取日期"] = trade_date

    existing = ws.get_all_values()
    if not existing or existing == [[]]:
        ws.append_row(out.columns.tolist())

    rows = out.fillna("").values.tolist()
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    log.info(f"分析資料寫入完成：{len(out)} 筆 → {SHEET_ANALYSIS}")


def write_sniper_list(ss: gspread.Spreadsheet, df: pd.DataFrame, trade_date: str):
    """
    覆寫狙擊名單（每日更新，只保留今日 Top）
    顯示重點欄位 + 標籤，方便直接決策
    """
    ws = ss.worksheet(SHEET_SNIPER)
    ws.clear()

    top_df = df[df["sniper_score"] >= 5].copy()
    if top_df.empty:
        top_df = df.head(20).copy()

    cols = [
        "排名", "股票代號", "股票名稱", "sniper_score", "label",
        "etf_count", "consec_buy_days", "trust_cum_5d",
        "above_ma20", "volume_ratio", "fund_growth_5d",
        "close", "weight_warning",
    ]
    available = [c for c in cols if c in top_df.columns]
    out = top_df[available].copy()

    # 標題行
    header = [f"⚡ 狙擊名單 {trade_date} | 更新時間：{datetime.now().strftime('%H:%M')}"]
    ws.append_row(header)
    ws.append_row(out.columns.tolist())
    rows = out.fillna("").values.tolist()
    ws.append_rows(rows, value_input_option="USER_ENTERED")

    # 格式化（分數高的行標記顏色）
    try:
        _apply_score_formatting(ws, out)
    except Exception as e:
        log.warning(f"格式化失敗（不影響資料）: {e}")

    log.info(f"狙擊名單更新完成：Top {len(out)} 檔 → {SHEET_SNIPER}")


def _apply_score_formatting(ws: gspread.Worksheet, df: pd.DataFrame):
    """對狙擊名單的高分行套用背景色"""
    from gspread.utils import rowcol_to_a1

    for i, (_, row) in enumerate(df.iterrows(), start=3):  # row 1=標題, 2=欄位名
        score = row.get("sniper_score", 0)
        if score >= 7:
            color = {"red": 0.9, "green": 1.0, "blue": 0.85}   # 淺綠
        elif score >= 5:
            color = {"red": 1.0, "green": 0.97, "blue": 0.82}  # 淺黃
        else:
            continue

        ws.format(f"A{i}:M{i}", {
            "backgroundColor": color,
            "textFormat": {"bold": score >= 7}
        })


def write_history(ss: gspread.Spreadsheet, df: pd.DataFrame, trade_date: str):
    """歷史回測庫：永久追加每日狙擊名單快照"""
    ws = ss.worksheet(SHEET_HISTORY)

    cols = [
        "抓取日期", "股票代號", "股票名稱", "sniper_score",
        "label", "close", "trust_cum_5d", "consec_buy_days",
    ]
    available = [c for c in cols if c in df.columns]
    out = df[available].copy()
    out["抓取日期"] = trade_date

    existing = ws.get_all_values()
    if not existing or existing == [[]]:
        ws.append_row(out.columns.tolist())

    rows = out.head(30).fillna("").values.tolist()  # 每日存 Top 30
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    log.info(f"歷史庫更新完成：{len(rows)} 筆 → {SHEET_HISTORY}")


def read_history(ss: gspread.Spreadsheet, days: int = 10) -> pd.DataFrame:
    """從歷史回測庫讀取最近 N 日資料，供 analyzer 使用"""
    try:
        ws = ss.worksheet(SHEET_HISTORY)
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if "抓取日期" in df.columns:
            recent_dates = sorted(df["抓取日期"].unique())[-days:]
            df = df[df["抓取日期"].isin(recent_dates)]

        return df
    except Exception as e:
        log.error(f"讀取歷史資料失敗: {e}")
        return pd.DataFrame()


def write_all(
    raw_df: pd.DataFrame,
    scored_df: pd.DataFrame,
    spreadsheet_id: str,
    trade_date: str,
    credentials_path: Optional[str] = None,
):
    """統一寫入入口：一次寫入四個分頁"""
    client = get_client(credentials_path)
    ss = get_or_create_spreadsheet(client, spreadsheet_id)

    write_raw_data(ss, raw_df, trade_date)
    write_analysis(ss, scored_df, trade_date)
    write_sniper_list(ss, scored_df, trade_date)
    write_history(ss, scored_df, trade_date)

    log.info("=== 全部寫入完成 ===")
    return ss


if __name__ == "__main__":
    # 測試：讀入 CSV 後寫入 Sheets
    import os
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "your_spreadsheet_id_here")

    raw = pd.read_csv("/tmp/etf_raw_test.csv")
    scored = pd.read_csv("/tmp/etf_scored.csv")
    trade_date = datetime.now().strftime("%Y%m%d")

    write_all(raw, scored, SPREADSHEET_ID, trade_date)
