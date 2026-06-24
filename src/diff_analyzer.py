"""
diff_analyzer.py
每日差異比對：今日 vs 昨日持股
產出：新增/加碼/減碼/清倉 + 變動張數 + 資金動向
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)


def load_history_from_sheets(ss, days: int = 2) -> pd.DataFrame:
    """從 Google Sheets 盤後原始數據庫讀取最近兩天資料"""
    try:
        ws = ss.worksheet("盤後原始數據庫")
        all_values = ws.get_all_values()
        if not all_values or len(all_values) < 2:
            return pd.DataFrame()

        headers = all_values[0]
        data = all_values[1:]
        df = pd.DataFrame(data, columns=headers)
        df = df[df.apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)]

        # 找日期欄
        date_col = next((c for c in df.columns if "日期" in c or "抓取" in c), None)
        if not date_col:
            return df

        dates = sorted(df[date_col].unique())[-days:]
        return df[df[date_col].isin(dates)].copy()

    except Exception as e:
        log.error(f"讀取歷史資料失敗: {e}")
        return pd.DataFrame()


def compute_daily_diff(
    today_df: pd.DataFrame,
    history_df: pd.DataFrame,
    today_date: str,
) -> pd.DataFrame:
    """
    比對今日 vs 昨日持股，計算：
    - 狀態：新增/加碼/減碼/清倉/持平
    - 變動張數（股數差異 / 1000）
    - 變動幅度%
    - 資金動向（變動張數 × 收盤價）
    """
    if today_df.empty or history_df.empty:
        log.warning("今日或昨日資料為空，無法比對")
        return pd.DataFrame()

    # 找日期欄
    date_col = next((c for c in history_df.columns if "日期" in c or "抓取" in c), None)
    if not date_col:
        log.warning("找不到日期欄")
        return pd.DataFrame()

    # 統一日期格式（去除分隔符，統一為 YYYYMMDD）
    def normalize_date(d):
        return str(d).replace("-", "").replace("/", "").strip()

    history_df = history_df.copy()
    history_df[date_col] = history_df[date_col].apply(normalize_date)
    today_norm = normalize_date(today_date)

    dates = sorted(history_df[date_col].unique())
    if len(dates) < 1:
        return pd.DataFrame()

    # 找昨日（排除今日）
    other_dates = [d for d in dates if d != today_norm]
    yesterday_date = other_dates[-1] if other_dates else None

    if not yesterday_date:
        log.warning("無昨日資料可比對")
        return pd.DataFrame()

    # 用 normalize 後的格式過濾
    today_date = today_norm

    yesterday_df = history_df[history_df[date_col] == yesterday_date].copy()
    log.info(f"比對日期：今日={today_date} vs 昨日={yesterday_date}")

    # 標準化欄位
    code_col  = "股票代號"
    name_col  = "股票名稱"
    etf_col   = "ETF代碼"
    share_col = "持股數"
    weight_col = "權重%"

    for df in [today_df, yesterday_df]:
        df[code_col] = df[code_col].astype(str).str.strip()
        if share_col in df.columns:
            df[share_col] = pd.to_numeric(
                df[share_col].astype(str).str.replace(",", ""), errors="coerce"
            ).fillna(0)
        if weight_col in df.columns:
            df[weight_col] = pd.to_numeric(df[weight_col], errors="coerce").fillna(0)

    # 依「股票代號 + ETF代碼」聚合（同一股票可被多檔ETF持有）
    def agg(df):
        return df.groupby([code_col, etf_col]).agg(
            股票名稱=(name_col, "first") if name_col in df.columns else (code_col, "first"),
            持股數=(share_col, "sum") if share_col in df.columns else (code_col, "count"),
            權重=(weight_col, "mean") if weight_col in df.columns else (code_col, "count"),
        ).reset_index()

    today_agg     = agg(today_df)
    yesterday_agg = agg(yesterday_df)

    # 合併比對
    merged = today_agg.merge(
        yesterday_agg[[code_col, etf_col, "持股數", "權重"]],
        on=[code_col, etf_col],
        how="outer",
        suffixes=("_今", "_昨"),
    )
    merged = merged.fillna(0)

    # 計算變動
    merged["變動股數"] = merged["持股數_今"] - merged["持股數_昨"]
    merged["變動張數"] = (merged["變動股數"] / 1000).round(1)
    merged["權重變動%"] = (merged["權重_今"] - merged["權重_昨"]).round(2)

    # 判斷狀態
    def get_status(row):
        today_shares   = row["持股數_今"]
        yesterday_shares = row["持股數_昨"]
        if yesterday_shares == 0 and today_shares > 0:
            return "🆕 新增"
        elif today_shares == 0 and yesterday_shares > 0:
            return "🗑️ 清倉"
        elif today_shares > yesterday_shares:
            return "🔺 加碼"
        elif today_shares < yesterday_shares:
            return "🔻 減碼"
        else:
            return "➖ 持平"

    merged["狀態"] = merged.apply(get_status, axis=1)

    # 加入股票名稱（從今日或昨日取）
    name_map = {}
    for df in [today_df, yesterday_df]:
        if name_col in df.columns:
            for _, r in df[[code_col, name_col]].drop_duplicates().iterrows():
                name_map[r[code_col]] = r[name_col]
    merged["股票名稱"] = merged[code_col].map(name_map).fillna(merged.get("股票名稱", ""))

    # 加入比對日期
    merged["今日"]   = today_date
    merged["昨日"]   = yesterday_date

    # 只保留有變動的（排除持平）
    changed = merged[merged["狀態"] != "➖ 持平"].copy()

    log.info(
        f"差異比對完成：新增={( changed['狀態']=='🆕 新增').sum()} "
        f"加碼={(changed['狀態']=='🔺 加碼').sum()} "
        f"減碼={(changed['狀態']=='🔻 減碼').sum()} "
        f"清倉={(changed['狀態']=='🗑️ 清倉').sum()}"
    )
    return changed.sort_values("狀態").reset_index(drop=True)


def compute_fund_flow(diff_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.DataFrame:
    """
    計算資金動向：變動張數 × 收盤價
    price_df：含「股票代號」和「收盤價」
    """
    if diff_df.empty or price_df.empty:
        return diff_df

    price_df = price_df[["股票代號", "收盤價"]].drop_duplicates("股票代號")
    price_df["股票代號"] = price_df["股票代號"].astype(str).str.strip()

    merged = diff_df.merge(price_df, on="股票代號", how="left")
    merged["收盤價"] = pd.to_numeric(merged["收盤價"], errors="coerce")
    merged["資金動向(萬)"] = (
        merged["變動張數"] * merged["收盤價"] * 1000 / 10000
    ).round(1)

    return merged


def aggregate_stock_diff(diff_df: pd.DataFrame) -> pd.DataFrame:
    """
    跨ETF聚合：把同一股票在不同ETF的變動合併
    產出：每檔股票的總變動張數、加碼ETF數、減碼ETF數
    """
    if diff_df.empty:
        return pd.DataFrame()

    code_col = "股票代號"

    # 計算各欄位是否存在
    has_amount  = "資金動向(萬)" in diff_df.columns
    has_price   = "收盤價" in diff_df.columns
    has_weight  = "權重變動%" in diff_df.columns

    agg_dict = {
        "股票名稱":  ("股票名稱", "first"),
        "加碼ETF數": ("狀態", lambda x: (x == "🔺 加碼").sum()),
        "減碼ETF數": ("狀態", lambda x: (x == "🔻 減碼").sum()),
        "新增ETF數": ("狀態", lambda x: (x == "🆕 新增").sum()),
        "清倉ETF數": ("狀態", lambda x: (x == "🗑️ 清倉").sum()),
        "總變動張數": ("變動張數", "sum"),
    }
    if has_amount:
        agg_dict["總資金動向"] = ("資金動向(萬)", "sum")
    if has_price:
        agg_dict["收盤價"] = ("收盤價", "first")
    if has_weight:
        agg_dict["平均權重變動%"] = ("權重變動%", "mean")

    agg = diff_df.groupby(code_col).agg(**agg_dict).reset_index()

    # 主要狀態標籤
    def main_status(row):
        if row["新增ETF數"] > 0 and row["加碼ETF數"] == 0 and row["減碼ETF數"] == 0:
            return "🆕 新增"
        elif row["清倉ETF數"] > 0 and row["加碼ETF數"] == 0 and row["減碼ETF數"] == 0:
            return "🗑️ 清倉"
        elif row["加碼ETF數"] > row["減碼ETF數"]:
            return "🔺 加碼"
        elif row["減碼ETF數"] > row["加碼ETF數"]:
            return "🔻 減碼"
        else:
            return "🔀 混合"

    agg["主要狀態"] = agg.apply(main_status, axis=1)

    # 排序：加碼 → 新增 → 混合 → 減碼 → 清倉
    order = {"🔺 加碼": 0, "🆕 新增": 1, "🔀 混合": 2, "🔻 減碼": 3, "🗑️ 清倉": 4}
    agg["排序"] = agg["主要狀態"].map(order).fillna(5)
    sort_col = "平均權重變動%" if "平均權重變動%" in agg.columns else "總資金動向" if "總資金動向" in agg.columns else "總變動張數"
    agg = agg.sort_values(
        ["排序", sort_col],
        ascending=[True, False]
    ).drop("排序", axis=1).reset_index(drop=True)
    agg.insert(0, "排名", range(1, len(agg) + 1))

    log.info(f"跨ETF聚合完成：{len(agg)} 檔有變動")
    return agg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("diff_analyzer 模組載入成功，等待資料...")
    log.info("使用方式：從 main.py 呼叫，需要今日 + 昨日兩天資料")
