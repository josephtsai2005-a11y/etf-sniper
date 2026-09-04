"""
diff_analyzer.py
每日差異比對：今日 vs 昨日持股
產出：新增/加碼/減碼/清倉 + 變動張數 + 資金動向

2026-09-04 修正（期貨合約誤入「ETF連續加碼追蹤」）：
使用者發現「ETF連續加碼追蹤」頁面出現「202609 臺股期貨」這種期貨合約，被系統當成一般
個股處理，算出「連續加碼4天、累計加碼0.2張、最新持股0.7張」這種沒有意義的結果——期貨
合約的「持股數」欄位單位其實是「口」不是「股」，直接／1000換算成「張」完全對不上，才會
出現0.2/0.7這種畸零小數。price_fetcher.py早就有_looks_like_futures_or_invalid()專門
過濾這類非個股代號（6碼、以20開頭、高機率是期貨合約到期年月），但這個判斷式只用在股價
抓取那一條路徑，compute_consecutive_accumulation()是直接讀「盤後原始數據庫」逐日持股
明細做連續天數分析，沒有套用同一層過濾，讓期貨合約（部分主動式ETF會用台指期做曝險/避險，
本來就會出現在原始持股清單裡）混進個股分析裡。修法：直接複用price_fetcher.py的判斷式，
在compute_consecutive_accumulation()分組計算前先過濾掉，避免兩處邏輯不同步。

2026-09-04 修正（股票分割誤判為大幅加碼）：
使用者指出緯穎股票分割「一股換三股」時，ETF對它的「持股數」也會跟著等比例變成3倍——這是
股本基準不連續造成的假訊號，不是ETF真的加碼。原本compute_daily_diff()／
compute_consecutive_accumulation()都只看「今日持股數 vs 昨日/前一天持股數」誰大誰小，
會把分割當天誤判成「大幅加碼」，變動張數/累計加碼張數也會是沒有意義的巨大假數字。
修法：兩處都新增偵測——單日持股數比例變化超過±50%時視為疑似股票分割/減資，
compute_daily_diff()改標「🔀 疑似股票分割/減資（非真實加減碼）」並在aggregate_
stock_diff()裡排除，不算進加碼/減碼統計；compute_consecutive_accumulation()則只保留
「最後一次疑似分割之後」的資料再判斷連續加碼天數，避免分割前後的持股數被混在一起比較。
這個±50%門檻抓不到分割比例很小的情況（例如1股換1.2股），這是已知限制。
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Optional
from price_fetcher import _looks_like_futures_or_invalid

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

        df[date_col] = df[date_col].astype(str).str.replace("-","")
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
    #
    # 2026-09-04修正（股票分割誤判為大幅加碼）：使用者指出緯穎股票分割「一股換三股」時，
    # ETF對它的「持股數」欄位也會跟著等比例變成3倍——這是股本基準不連續造成的假訊號，
    # 不是ETF真的買了兩倍的股票。原本這裡只看「今日持股數 vs 昨日持股數」誰大誰小，
    # 沒有排除這種情況，分割當天會被誤判成「🔺 加碼」，且變動張數（真實股數差）會是一個
    # 巨大的假數字，往下游流進aggregate_stock_diff()的「總變動張數」「資金動向」加總，
    # 汙染統計。修法：偵測到單日持股數比例變化超過±50%（正常ETF單日調節不會有這麼誇張
    # 的比例，但真正的股票分割/減資，比例通常是2倍、3倍這種整數倍，遠超過50%），改標
    # 「🔀 疑似股票分割/減資（非真實加減碼）」，不算進加碼/減碼——這個門檻抓不到分割
    # 比例很小的情況（例如1股換1.2股），這種情況目前還是會被當成正常加碼，是已知限制。
    def get_status(row):
        today_shares   = row["持股數_今"]
        yesterday_shares = row["持股數_昨"]
        if yesterday_shares == 0 and today_shares > 0:
            return "🆕 新增"
        elif today_shares == 0 and yesterday_shares > 0:
            return "🗑️ 清倉"
        elif yesterday_shares > 0 and (today_shares / yesterday_shares >= 1.5
                                        or today_shares / yesterday_shares <= 0.67):
            return "🔀 疑似股票分割/減資（非真實加減碼）"
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
    merged["資金動向(千萬)"] = (
        merged["變動張數"] * merged["收盤價"] * 1000 / 10000000
    ).round(2)

    return merged


def aggregate_stock_diff(diff_df: pd.DataFrame) -> pd.DataFrame:
    """
    跨ETF聚合：把同一股票在不同ETF的變動合併
    產出：每檔股票的總變動張數、加碼ETF數、減碼ETF數
    """
    if diff_df.empty:
        return pd.DataFrame()

    # 2026-09-04修正：排除「疑似股票分割/減資」的列，避免這類非真實加減碼的巨大股數
    # 跳動污染「總變動張數」「資金動向」等加總指標——「持股異動明細」原始表格仍會保留
    # 這一列讓使用者看到（見compute_daily_diff()的get_status()），但這裡的跨ETF聚合
    # 統計不該把它算進「加碼/減碼」，這裡直接濾掉，不進入下面任何一個加總欄位。
    diff_df = diff_df[diff_df["狀態"] != "🔀 疑似股票分割/減資（非真實加減碼）"].copy()
    if diff_df.empty:
        return pd.DataFrame()

    code_col = "股票代號"

    # 計算各欄位是否存在
    has_amount  = "資金動向(千萬)" in diff_df.columns
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
        agg_dict["總資金動向"] = ("資金動向(千萬)", "sum")
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


def compute_consecutive_accumulation(ss, lookback_days: int = 15, min_streak: int = 3) -> pd.DataFrame:
    """
    籌碼面轉折訊號：追蹤「哪一檔ETF」連續好幾個交易日持續加碼「同一檔股票」
    比單看「今天vs昨天」更有說服力——單日加碼可能只是正常調節，
    但同一家ETF連續3天以上都在加碼同一檔股票，代表這是有意識的、持續性的布局動作

    資料來源：「盤後原始數據庫」逐日逐ETF持股紀錄（跟compute_daily_diff同一份資料，
    只是這裡多抓lookback_days天、逐日比對，而不是只比對最近一天）

    lookback_days: 往回看幾個交易日（預設15天，足夠抓到2-3週的連續趨勢）
    min_streak: 至少要連續加碼幾天才算數（預設3天，避免把偶發的1-2天波動也算進來）

    回傳：股票代號、股票名稱、ETF代碼、目前連續加碼天數、累計加碼張數、最新持股數

    2026-09-04修正：加入_looks_like_futures_or_invalid()過濾，排除期貨合約等非個股代號
    （詳見檔案開頭說明），避免這類持股被當成一般個股算出沒有意義的連續加碼統計。
    """
    history_df = load_history_from_sheets(ss, days=lookback_days)
    if history_df.empty:
        log.warning("連續加碼追蹤：無歷史資料可分析")
        return pd.DataFrame()

    code_col, name_col, etf_col, share_col = "股票代號", "股票名稱", "ETF代碼", "持股數"
    date_col = next((c for c in history_df.columns if "日期" in c or "抓取" in c), None)
    if not date_col:
        log.warning("連續加碼追蹤：找不到日期欄")
        return pd.DataFrame()

    df = history_df.copy()
    df[code_col] = df[code_col].astype(str).str.strip()
    df[share_col] = pd.to_numeric(df[share_col].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    df[date_col] = df[date_col].astype(str).str.replace("-", "")

    # 2026-09-04修正（期貨合約誤入連續加碼追蹤）：見檔案開頭說明。這裡直接複用
    # price_fetcher.py的_looks_like_futures_or_invalid()判斷式，避免兩處邏輯不同步。
    before_filter = df[code_col].nunique()
    df = df[~df[code_col].apply(_looks_like_futures_or_invalid)].copy()
    after_filter = df[code_col].nunique()
    if before_filter != after_filter:
        log.info(f"連續加碼追蹤：過濾 {before_filter - after_filter} 檔疑似期貨/非個股代號，不列入連續加碼分析")

    # 每個(股票,ETF)組合，依日期排序後的持股數序列
    df = df.sort_values(date_col)
    dates_available = sorted(df[date_col].unique())
    if len(dates_available) < min_streak + 1:
        log.info(f"連續加碼追蹤：目前只累積{len(dates_available)}個交易日資料，"
                  f"需要至少{min_streak + 1}天才能判斷連續趨勢，暫無結果")
        return pd.DataFrame()

    records = []
    for (code, etf), grp in df.groupby([code_col, etf_col]):
        grp = grp.sort_values(date_col)

        # 2026-09-04修正（股票分割誤判為連續加碼）：股票分割/減資會讓ETF持股數等比例
        # 跳動（例如一股換三股，持股數變成3倍），這不是真的加碼，是股本基準不連續造成
        # 的假訊號。跟price_fetcher.py對付除權息的做法一致：偵測到單日持股數比例變化
        # 超過±50%時，只保留「最後一次疑似分割之後」的資料，避免分割前後的持股數被
        # 誤判成連續加碼、或把分割當天的巨大假增量算進「累計加碼張數」。
        shares_series_raw = grp[share_col].tolist()
        split_pos = None
        prev_v = None
        for i, v in enumerate(shares_series_raw):
            if prev_v is not None and prev_v > 0:
                ratio = v / prev_v
                if ratio >= 1.5 or ratio <= 0.67:
                    split_pos = i
            prev_v = v
        if split_pos is not None:
            grp = grp.iloc[split_pos:]

        if len(grp) < min_streak + 1:
            continue

        shares_series = grp[share_col].tolist()
        name = grp[name_col].iloc[-1] if name_col in grp.columns else ""

        # 從最新一天往回數，計算連續加碼的天數（只要有一天沒加碼就中斷計算）
        streak = 0
        for i in range(len(shares_series) - 1, 0, -1):
            if shares_series[i] > shares_series[i - 1]:
                streak += 1
            else:
                break

        if streak >= min_streak:
            total_increase = shares_series[-1] - shares_series[-1 - streak]
            records.append({
                "股票代號": code,
                "股票名稱": name,
                "ETF代碼": etf,
                "連續加碼交易日數": streak,
                "累計加碼張數": round(total_increase / 1000, 1),
                "最新持股數(張)": round(shares_series[-1] / 1000, 1),
            })

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.sort_values("連續加碼交易日數", ascending=False).reset_index(drop=True)
        log.info(f"連續加碼追蹤：找到 {len(result)} 組(股票,ETF)持續加碼{min_streak}天以上")
    else:
        log.info(f"連續加碼追蹤：目前沒有任何組合連續加碼達{min_streak}天以上")

    return result