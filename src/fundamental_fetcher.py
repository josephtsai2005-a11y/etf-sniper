"""
fundamental_fetcher.py
基本面資料抓取 — 使用 FinMind API
主要指標：月營收年增率、EPS 季增率、本益比
"""
import os
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
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()  # 已註冊帳號取得token，提高請求頻率上限

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def _looks_like_futures_or_invalid(stock_code: str) -> bool:
    """過濾明顯不是個股代號的項目（例如期貨合約），避免浪費API呼叫額度"""
    if not stock_code:
        return True
    code = stock_code.strip()
    if len(code) == 6 and code.isdigit() and code.startswith("20"):
        return True
    return False


def _finmind_request(params: dict, retries: int = 2) -> dict:
    """統一的FinMind請求函式，含重試機制與清楚的失敗log"""
    params = {**params, "token": FINMIND_TOKEN}
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(FINMIND_BASE, params=params, timeout=15)
            data = resp.json()

            # FinMind 對於頻率限制/token無效等狀況會回傳 status != 200，訊息藏在 msg 欄位
            if data.get("status") != 200:
                msg = data.get("msg", "未知錯誤")
                last_error = f"status={data.get('status')}, msg={msg}"
                if attempt < retries:
                    time.sleep(2)
                    continue
                return {"__error__": last_error}

            return data

        except Exception as e:
            last_error = str(e)
            if attempt < retries:
                time.sleep(1.5)
                continue
            return {"__error__": last_error}

    return {"__error__": last_error or "未知錯誤"}


def fetch_monthly_revenue(stock_code: str, months: int = 13) -> pd.DataFrame:
    """
    抓取月營收資料（近 N 個月）
    回傳：date, revenue, revenue_month, revenue_year
    """
    if _looks_like_futures_or_invalid(stock_code):
        return pd.DataFrame()

    start_date = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m-%d")

    data = _finmind_request({
        "dataset":    "TaiwanStockMonthRevenue",
        "data_id":    stock_code,
        "start_date": start_date,
    })

    if "__error__" in data:
        log.warning(f"{stock_code} 月營收抓取失敗: {data['__error__']}")
        return pd.DataFrame()

    if not data.get("data"):
        log.warning(f"{stock_code} 月營收查無資料（可能是新上市/興櫃/FinMind未覆蓋）")
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    df["date"]    = pd.to_datetime(df["date"])
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    return df


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

    if len(df) >= 2:
        prev_revenue = df.iloc[-2]["revenue"]
        mom = round((latest_revenue - prev_revenue) / prev_revenue * 100, 1) if prev_revenue else None
    else:
        mom = None

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
    """抓取每季 EPS"""
    if _looks_like_futures_or_invalid(stock_code):
        return pd.DataFrame()

    start_date = (datetime.now() - timedelta(days=quarters * 92)).strftime("%Y-%m-%d")

    data = _finmind_request({
        "dataset":    "TaiwanStockFinancialStatements",
        "data_id":    stock_code,
        "start_date": start_date,
    })

    if "__error__" in data:
        log.warning(f"{stock_code} EPS抓取失敗: {data['__error__']}")
        return pd.DataFrame()

    if not data.get("data"):
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])

    eps_df = df[df["type"].str.contains("EPS|每股", na=False)].copy()
    if eps_df.empty:
        eps_df = df[df["type"] == "每股盈餘"].copy()

    if eps_df.empty:
        log.warning(f"{stock_code} 財報資料中找不到EPS欄位（type欄位可能沒有EPS/每股相關字樣）")
        return pd.DataFrame()

    eps_df["date"]  = pd.to_datetime(eps_df["date"])
    eps_df["value"] = pd.to_numeric(eps_df["value"], errors="coerce")
    eps_df = eps_df.sort_values("date").reset_index(drop=True)
    return eps_df[["date", "type", "value"]]


def fetch_pe_ratio(stock_code: str) -> Dict:
    """抓取本益比（P/E Ratio）"""
    if _looks_like_futures_or_invalid(stock_code):
        return {}

    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    data = _finmind_request({
        "dataset":    "TaiwanStockPER",
        "data_id":    stock_code,
        "start_date": start_date,
    })

    if "__error__" in data:
        log.warning(f"{stock_code} 本益比抓取失敗: {data['__error__']}")
        return {}

    if not data.get("data"):
        log.warning(f"{stock_code} 本益比查無資料")
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


def fetch_batch_fundamental(
    stock_codes: List[str],
    delay: float = 0.3,
) -> pd.DataFrame:
    """
    批次抓取多檔股票的基本面資料
    delay: 有帶token後可以縮短間隔（原本0.5，token提高頻率上限後可以調快一些）
    """
    if not FINMIND_TOKEN:
        log.warning("尚未設定 FINMIND_TOKEN 環境變數，將使用免費無token額度（頻率限制較低，容易批次抓取失敗）")

    records = []
    failed_codes = []
    total = len(stock_codes)

    log.info(f"抓取基本面資料：{total} 檔...（{'已帶token' if FINMIND_TOKEN else '無token'}）")

    for i, code in enumerate(stock_codes, 1):
        record = {"股票代號": str(code)}
        had_any_data = False

        rev_df = fetch_monthly_revenue(str(code), months=14)
        if not rev_df.empty:
            rev_info = compute_revenue_yoy(rev_df)
            record.update(rev_info)
            had_any_data = True

        pe_info = fetch_pe_ratio(str(code))
        if pe_info:
            record.update(pe_info)
            had_any_data = True

        if not had_any_data:
            failed_codes.append(str(code))

        records.append(record)

        if i % 10 == 0:
            log.info(f"  基本面進度 {i}/{total}")
        time.sleep(delay)

    if failed_codes:
        log.warning(f"以下 {len(failed_codes)} 檔完全無基本面資料: {failed_codes}")

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["年增率%"]    = pd.to_numeric(df.get("年增率%", None), errors="coerce")
    df["基本面分數"]  = pd.to_numeric(df.get("基本面分數", 0), errors="coerce").fillna(0)

    log.info(f"基本面抓取完成：{len(df)} 檔，高速成長：{df['營收訊號'].eq('🚀 高速成長').sum() if '營收訊號' in df.columns else 0} 檔，"
             f"完全無資料：{len(failed_codes)} 檔")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_codes = ["2330", "2454", "2383", "6223", "2308", "3037"]
    log.info(f"=== 測試基本面抓取：{len(test_codes)} 檔 ===")

    df = fetch_batch_fundamental(test_codes, delay=0.3)
    if not df.empty:
        cols = ["股票代號", "最新月份", "月營收(億)", "年增率%", "月增率%", "營收訊號", "本益比", "本益比訊號", "基本面分數"]
        avail = [c for c in cols if c in df.columns]
        print(df[avail].to_string(index=False))
    else:
        print("無資料")