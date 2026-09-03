"""
fundamental_fetcher.py
基本面資料抓取 — 使用 FinMind API
主要指標：月營收年增率、EPS 季增率、本益比

2026-09-01 優化（基本面資料覆蓋率）：
新增「批次模式」fetch_bulk_monthly_revenue() / fetch_bulk_pe_ratio()——原本設想FinMind的
dataset在不帶data_id參數時會回傳「當期全市場」資料，可以用1-2次API呼叫取代原本
fetch_batch_fundamental()逐檔呼叫（N檔股票=N次呼叫）的做法。

**2026-09-01 本機實測結果：這個批次功能被FinMind擋下來了**——不帶data_id的請求會
回傳 `status=400, msg=Your level is free. Please update your user level.`，代表
「一次拿全市場」是FinMind付費Sponsor方案才開放的功能，免費帳號（不管有沒有註冊token）
都無法使用，不是重試或延遲能解決的問題。

因此 fetch_batch_fundamental() 預設把 use_bulk 關掉（use_bulk=False），批次函式保留在
程式碼裡但不會被自動呼叫——如果之後升級FinMind Sponsor方案，把 fetch_batch_fundamental()
呼叫時的 use_bulk 設回 True 即可重新啟用，不需要改動其他邏輯。

在使用者尚未考慮升級付費方案的前提下，要改善基本面覆蓋率，目前最低成本的手段是：
**到 FinMind 免費註冊一個帳號、拿到（免費的）token，設定到 FINMIND_TOKEN 環境變數**——
免費註冊帳號雖然不能用批次模式，但仍然可以提高逐檔請求的每分鐘頻率上限（比完全匿名/
無token的請求限制寬鬆），能直接緩解原本「逐檔抓取撞到頻率限制」的問題，且完全免費。
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


def _finmind_request(params: dict, retries: int = 2, timeout: int = 15) -> dict:
    """統一的FinMind請求函式，含重試機制與清楚的失敗log"""
    params = {**params, "token": FINMIND_TOKEN}
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(FINMIND_BASE, params=params, timeout=timeout)
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


def fetch_bulk_monthly_revenue(months: int = 14, retries: int = 1) -> pd.DataFrame:
    """
    一次性抓取「全市場」月營收（不指定data_id），取代逐檔各呼叫一次TaiwanStockMonthRevenue。

    FinMind的dataset在省略data_id時，多數會回傳「當期全部股票」的資料——理論上可以把
    fetch_batch_fundamental()原本N次逐檔呼叫，變成1次批次呼叫，大幅降低被免費額度
    頻率限制擋下來的機率。

    ⚠️ 尚未實測驗證，部署前請先在本機手動確認回傳格式（見檔案開頭說明）。
    失敗或格式不符預期時回傳空DataFrame，呼叫端會自動退回逐檔抓取，不影響既有行為。

    回傳：跟fetch_monthly_revenue()單檔版格式相同，多一個stock_id欄位，
    供後續依股票代號分組計算YoY/MoM。
    """
    start_date = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m-%d")

    data = _finmind_request({
        "dataset":    "TaiwanStockMonthRevenue",
        "start_date": start_date,
    }, retries=retries, timeout=60)

    if "__error__" in data:
        log.warning(f"批次月營收抓取失敗，將退回逐檔抓取: {data['__error__']}")
        return pd.DataFrame()

    if not data.get("data"):
        log.warning("批次月營收查無資料，將退回逐檔抓取")
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    if "stock_id" not in df.columns:
        log.warning(f"批次月營收回傳格式不含stock_id欄位（實際欄位：{list(df.columns)}），將退回逐檔抓取")
        return pd.DataFrame()

    df["date"]    = pd.to_datetime(df["date"])
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df = df.sort_values(["stock_id", "date"]).reset_index(drop=True)
    log.info(f"批次月營收抓取成功：{df['stock_id'].nunique()} 檔股票、{len(df)} 筆月資料")
    return df


def fetch_bulk_pe_ratio(retries: int = 1) -> pd.DataFrame:
    """
    一次性抓取「全市場」本益比（不指定data_id），取代逐檔各呼叫一次TaiwanStockPER。
    設計與注意事項同 fetch_bulk_monthly_revenue()。
    """
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    data = _finmind_request({
        "dataset":    "TaiwanStockPER",
        "start_date": start_date,
    }, retries=retries, timeout=60)

    if "__error__" in data:
        log.warning(f"批次本益比抓取失敗，將退回逐檔抓取: {data['__error__']}")
        return pd.DataFrame()

    if not data.get("data"):
        log.warning("批次本益比查無資料，將退回逐檔抓取")
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    if "stock_id" not in df.columns:
        log.warning(f"批次本益比回傳格式不含stock_id欄位（實際欄位：{list(df.columns)}），將退回逐檔抓取")
        return pd.DataFrame()

    df["PER"]  = pd.to_numeric(df.get("PER", df.get("pe_ratio", 0)), errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["stock_id", "date"]).reset_index(drop=True)
    log.info(f"批次本益比抓取成功：{df['stock_id'].nunique()} 檔股票")
    return df


def _pe_signal_from_value(pe: float) -> str:
    if pe < 15:
        return "💚 便宜"
    elif pe < 25:
        return "🟡 合理"
    elif pe < 35:
        return "🟠 偏貴"
    else:
        return "🔴 昂貴"


def fetch_batch_fundamental(
    stock_codes: List[str],
    delay: float = 0.3,
    use_bulk: bool = False,
) -> pd.DataFrame:
    """
    批次抓取多檔股票的基本面資料
    delay: 有帶token後可以縮短間隔（原本0.5，token提高頻率上限後可以調快一些）
    use_bulk: 是否優先嘗試批次模式（1-2次API呼叫取代N次逐檔呼叫）。
        ⚠️ 2026-09-01實測確認：批次模式（省略data_id一次拿全市場）是FinMind付費
        Sponsor方案才開放的功能，免費帳號會直接被拒絕（status=400, "Your level is
        free"），不是重試/延遲能解決的問題。預設關閉（False），避免每次執行都白白
        浪費1-2次注定失敗的API呼叫。如果之後升級FinMind Sponsor方案，呼叫時傳入
        use_bulk=True 即可重新啟用批次模式，不需要改動其他邏輯。
        批次模式沒抓到、或格式不符預期的股票，會自動退回逐檔模式補齊，
        確保覆蓋率至少不會比優化前差。

    新增「資料來源」欄位（批次/逐檔），方便之後追查是哪個環節造成覆蓋率不足。
    """
    if not FINMIND_TOKEN:
        log.warning("尚未設定 FINMIND_TOKEN 環境變數，將使用免費無token額度（頻率限制較低，容易批次抓取失敗）")

    codes = [str(c) for c in stock_codes]
    records: List[dict] = []
    failed_codes: List[str] = []
    remaining_codes = list(codes)

    # ── 優先嘗試批次模式 ──────────────────────────────────────
    if use_bulk:
        bulk_rev = fetch_bulk_monthly_revenue(months=14)
        bulk_pe  = fetch_bulk_pe_ratio()

        if not bulk_rev.empty or not bulk_pe.empty:
            still_remaining = []
            for code in remaining_codes:
                record = {"股票代號": code}
                had_any_data = False

                if not bulk_rev.empty:
                    sub = bulk_rev[bulk_rev["stock_id"] == code].reset_index(drop=True)
                    if not sub.empty:
                        rev_info = compute_revenue_yoy(sub)
                        if rev_info:
                            record.update(rev_info)
                            had_any_data = True

                if not bulk_pe.empty:
                    sub_pe = bulk_pe[bulk_pe["stock_id"] == code]
                    if not sub_pe.empty:
                        latest_pe = sub_pe.iloc[-1]["PER"]
                        if pd.notna(latest_pe):
                            record["本益比"]   = round(float(latest_pe), 1)
                            record["本益比訊號"] = _pe_signal_from_value(float(latest_pe))
                            had_any_data = True

                if had_any_data:
                    record["資料來源"] = "批次"
                    records.append(record)
                else:
                    still_remaining.append(code)

            log.info(f"批次模式完成：{len(codes) - len(still_remaining)}/{len(codes)} 檔已取得資料，"
                     f"剩餘 {len(still_remaining)} 檔改用逐檔模式補抓")
            remaining_codes = still_remaining
        else:
            log.info("批次模式無可用資料，全部改用逐檔模式")

    # ── 逐檔模式：批次模式的完整備援，或補齊批次沒抓到的股票 ──────
    total = len(remaining_codes)
    if total > 0:
        log.info(f"逐檔抓取基本面資料：{total} 檔...（{'已帶token' if FINMIND_TOKEN else '無token'}）")

        for i, code in enumerate(remaining_codes, 1):
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

            if had_any_data:
                record["資料來源"] = "逐檔"
            else:
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

    bulk_n = (df.get("資料來源", pd.Series(dtype=str)) == "批次").sum()
    single_n = (df.get("資料來源", pd.Series(dtype=str)) == "逐檔").sum()
    log.info(f"基本面抓取完成：{len(df)} 檔（批次來源 {bulk_n} 檔／逐檔來源 {single_n} 檔），"
             f"高速成長：{df['營收訊號'].eq('🚀 高速成長').sum() if '營收訊號' in df.columns else 0} 檔，"
             f"完全無資料：{len(failed_codes)} 檔")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_codes = ["2330", "2454", "2383", "6223", "2308", "3037"]
    log.info(f"=== 測試基本面抓取：{len(test_codes)} 檔 ===")

    df = fetch_batch_fundamental(test_codes, delay=0.3)
    if not df.empty:
        cols = ["股票代號", "資料來源", "最新月份", "月營收(億)", "年增率%", "月增率%", "營收訊號", "本益比", "本益比訊號", "基本面分數"]
        avail = [c for c in cols if c in df.columns]
        print(df[avail].to_string(index=False))
    else:
        print("無資料")