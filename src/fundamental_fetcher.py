"""
fundamental_fetcher.py
基本面資料抓取 — 使用 FinMind 免費 API
主要指標：月營收年增率、EPS 季增率、本益比
"""
import requests
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = ""  # 免費版不需要 token，有 token 可以提高頻率

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def fetch_monthly_revenue(stock_code: str, months: int = 13) -> pd.DataFrame:
    """
    抓取月營收資料（近 N 個月）
    回傳：date, revenue, revenue_month, revenue_year
    """
    start_date = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m-%d")

    try:
        resp = SESSION.get(
            FINMIND_BASE,
            params={
                "dataset":   "TaiwanStockMonthRevenue",
                "data_id":   stock_code,
                "start_date": start_date,
                "token":     FINMIND_TOKEN,
            },
            timeout=15,
        )
        data = resp.json()

        if data.get("status") != 200 or not data.get("data"):
            return pd.DataFrame()

        df = pd.DataFrame(data["data"])
        df["date"]    = pd.to_datetime(df["date"])
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        return df

    except Exception as e:
        log.debug(f"{stock_code} 月營收失敗: {e}")
        return pd.DataFrame()


def compute_revenue_yoy(df: pd.DataFrame) -> Dict:
    """
    計算月營收年增率（YoY）
    比較當月 vs 去年同月
    """
    if df.empty or len(df) < 2:
        return {}

    latest = df.iloc[-1]
    latest_revenue = latest["revenue"]
    latest_month   = latest["revenue_month"]
    latest_year    = latest["revenue_year"]

    # 找去年同月
    yoy_row = df[
        (df["revenue_month"] == latest_month) &
        (df["revenue_year"]  == latest_year - 1)
    ]

    if yoy_row.empty:
        return {
            "最新月份":   f"{latest_year}/{latest_month:02d}",
            "月營收(億)": round(latest_revenue / 1e8, 1),
            "年增率%":    None,
            "營收訊號":   "📊 資料不足",
        }

    yoy_revenue = yoy_row.iloc[0]["revenue"]
    yoy = round((latest_revenue - yoy_revenue) / yoy_revenue * 100, 1) if yoy_revenue else None

    # 月增率（MoM）
    if len(df) >= 2:
        prev_revenue = df.iloc[-2]["revenue"]
        mom = round((latest_revenue - prev_revenue) / prev_revenue * 100, 1) if prev_revenue else None
    else:
        mom = None

    # 訊號判斷
    if yoy is not None:
        if yoy >= 30:
            signal = "🚀 高速成長"
        elif yoy >= 10:
            signal = "✅ 穩健成長"
        elif yoy >= 0:
            signal = "➡️ 持平微增"
        elif yoy >= -10:
            signal = "⚠️ 小幅衰退"
        else:
            signal = "🔻 明顯衰退"
    else:
        signal = "📊 資料不足"

    return {
        "最新月份":   f"{latest_year}/{latest_month:02d}",
        "月營收(億)": round(latest_revenue / 1e8, 1),
        "年增率%":    yoy,
        "月增率%":    mom,
        "營收訊號":   signal,
        "基本面分數":  2 if (yoy or 0) >= 20 else 1 if (yoy or 0) >= 0 else 0,
    }


def fetch_eps(stock_code: str, quarters: int = 5) -> pd.DataFrame:
    """
    抓取每季 EPS
    """
    start_date = (datetime.now() - timedelta(days=quarters * 92)).strftime("%Y-%m-%d")

    try:
        resp = SESSION.get(
            FINMIND_BASE,
            params={
                "dataset":    "TaiwanStockFinancialStatements",
                "data_id":    stock_code,
                "start_date": start_date,
                "token":      FINMIND_TOKEN,
            },
            timeout=15,
        )
        data = resp.json()

        if data.get("status") != 200 or not data.get("data"):
            return pd.DataFrame()

        df = pd.DataFrame(data["data"])

        # 找 EPS 相關欄位
        eps_df = df[df["type"].str.contains("EPS|每股", na=False)].copy()
        if eps_df.empty:
            eps_df = df[df["type"] == "每股盈餘"].copy()

        if eps_df.empty:
            return pd.DataFrame()

        eps_df["date"]  = pd.to_datetime(eps_df["date"])
        eps_df["value"] = pd.to_numeric(eps_df["value"], errors="coerce")
        eps_df = eps_df.sort_values("date").reset_index(drop=True)
        return eps_df[["date","type","value"]]

    except Exception as e:
        log.debug(f"{stock_code} EPS 失敗: {e}")
        return pd.DataFrame()


def fetch_pe_ratio(stock_code: str) -> Dict:
    """
    抓取本益比（P/E Ratio）
    """
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        resp = SESSION.get(
            FINMIND_BASE,
            params={
                "dataset":    "TaiwanStockPER",
                "data_id":    stock_code,
                "start_date": start_date,
                "token":      FINMIND_TOKEN,
            },
            timeout=15,
        )
        data = resp.json()

        if data.get("status") != 200 or not data.get("data"):
            return {}

        df = pd.DataFrame(data["data"])
        if df.empty:
            return {}

        df["PER"] = pd.to_numeric(df.get("PER", df.get("pe_ratio", 0)), errors="coerce")
        latest_pe = df.iloc[-1]["PER"] if not df.empty else None

        if latest_pe is None:
            return {}

        if latest_pe < 15:
            pe_signal = "💚 便宜"
        elif latest_pe < 25:
            pe_signal = "🟡 合理"
        elif latest_pe < 35:
            pe_signal = "🟠 偏貴"
        else:
            pe_signal = "🔴 昂貴"

        return {"本益比": round(latest_pe, 1), "本益比訊號": pe_signal}

    except Exception as e:
        log.debug(f"{stock_code} 本益比失敗: {e}")
        return {}


def fetch_batch_fundamental(
    stock_codes: List[str],
    delay: float = 0.5,
) -> pd.DataFrame:
    """
    批次抓取多檔股票的基本面資料
    """
    records = []
    total = len(stock_codes)

    log.info(f"抓取基本面資料：{total} 檔...")

    for i, code in enumerate(stock_codes, 1):
        record = {"股票代號": str(code)}

        # 月營收
        rev_df = fetch_monthly_revenue(str(code), months=14)
        if not rev_df.empty:
            rev_info = compute_revenue_yoy(rev_df)
            record.update(rev_info)

        # 本益比
        pe_info = fetch_pe_ratio(str(code))
        record.update(pe_info)

        records.append(record)

        if i % 10 == 0:
            log.info(f"  基本面進度 {i}/{total}")
        time.sleep(delay)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["年增率%"]    = pd.to_numeric(df.get("年增率%", None), errors="coerce")
    df["基本面分數"]  = pd.to_numeric(df.get("基本面分數", 0), errors="coerce").fillna(0)

    log.info(f"基本面抓取完成：{len(df)} 檔，高速成長：{df['營收訊號'].eq('🚀 高速成長').sum() if '營收訊號' in df.columns else 0} 檔")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_codes = ["2330", "2454", "2383", "6223", "2308", "3037"]
    log.info(f"=== 測試基本面抓取：{len(test_codes)} 檔 ===")

    df = fetch_batch_fundamental(test_codes, delay=0.5)
    if not df.empty:
        cols = ["股票代號","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"]
        avail = [c for c in cols if c in df.columns]
        print(df[avail].to_string(index=False))
    else:
        print("無資料")
