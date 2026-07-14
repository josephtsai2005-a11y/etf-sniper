"""
price_fetcher.py v3
串接 TWSE 股價 API
取得：收盤價、漲跌、漲跌幅%、MA20、站上月線、成交量、成交金額
注意：同時保留股票名稱（從 holdings_df 帶入，不從 TWSE 另外抓）
"""
import requests
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List

log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.twse.com.tw/",
})


def _looks_like_futures_or_invalid(stock_code: str) -> bool:
    """
    過濾明顯不是個股代號的項目（例如期貨合約 "202608 臺股期貨08/26"）
    真正的TWSE個股代號多為4碼數字，或4碼數字+英文字母（如興櫃/特別股）；
    6碼且以"20"開頭、全為數字的，高機率是期貨合約的到期年月，直接跳過避免浪費API呼叫
    """
    if not stock_code:
        return True
    code = stock_code.strip()
    if len(code) == 6 and code.isdigit() and code.startswith("20"):
        return True
    return False


def get_stock_price_single(stock_code: str, retries: int = 2) -> dict:
    """
    取得單一股票近期行情（跨月合併，確保有足夠交易日計算 MA20）
    新增：MA5/MA10、均線排列狀態、連續站上月線天數、量能比
    retries: 抓取失敗時的重試次數（避免單次網路異常/TWSE暫時異常就整檔放棄）
    """
    if _looks_like_futures_or_invalid(stock_code):
        log.debug(f"{stock_code} 疑似非個股代號（期貨/無效），跳過股價抓取")
        return {}

    today = datetime.now()
    this_month = today.strftime("%Y%m") + "01"
    prev_month_date = (today.replace(day=1) - timedelta(days=1)).strftime("%Y%m") + "01"

    url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

    def fetch_month(date_str):
        params = {"response": "json", "date": date_str, "stockNo": stock_code}
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return pd.DataFrame()
        fields = data.get("fields", [])
        rows = data.get("data", [])
        return pd.DataFrame(rows, columns=fields)

    last_error = None
    for attempt in range(retries + 1):
        try:
            df_this = fetch_month(this_month)
            df_prev = fetch_month(prev_month_date)
            df = pd.concat([df_prev, df_this], ignore_index=True) if not df_prev.empty else df_this

            if df.empty:
                # TWSE本身回傳「無資料」（例如真的還沒開始交易），重試沒有意義，直接放棄
                return {}
            break  # 成功拿到資料，跳出重試迴圈
        except Exception as e:
            last_error = e
            if attempt < retries:
                log.debug(f"{stock_code} 第{attempt+1}次抓取失敗，重試中: {e}")
                time.sleep(1.5)
                continue
            log.warning(f"{stock_code} 股價抓取失敗（已重試{retries}次）: {e}")
            return {}

    try:
        if df.empty:
            return {}

        for col in df.columns:
            if col not in ["日期"]:
                df[col] = df[col].astype(str).str.replace(",", "").str.replace("+", "")
                df[col] = pd.to_numeric(df[col], errors="coerce")

        close_col  = next((c for c in df.columns if "收盤" in c), None)
        change_col = next((c for c in df.columns if "漲跌" in c and "幅" not in c), None)
        vol_col    = next((c for c in df.columns if "成交股數" in c or "成交量" in c), None)
        amt_col    = next((c for c in df.columns if "成交金額" in c), None)

        if not close_col or df.empty:
            return {}

        closes = df[close_col].dropna().tolist()
        if not closes:
            return {}

        latest_close = closes[-1]
        ma5  = round(sum(closes[-5:])  / min(len(closes), 5),  2)
        ma10 = round(sum(closes[-10:]) / min(len(closes), 10), 2)
        ma20 = round(sum(closes[-20:]) / min(len(closes), 20), 2)
        above_ma20 = latest_close > ma20

        # 均線排列狀態
        if ma5 > ma10 > ma20:
            ma_alignment = "多頭排列"
        elif ma5 < ma10 < ma20:
            ma_alignment = "空頭排列"
        else:
            ma_alignment = "糾結"

        # 連續站上月線天數：回溯計算過去每一天的MA20，反推連續天數
        consecutive_above = 0
        if len(closes) >= 21:
            for i in range(len(closes) - 1, 19, -1):  # 從最新一天往回，至少要有20天可算MA20
                day_ma20 = sum(closes[i-20:i]) / 20
                if closes[i] > day_ma20:
                    consecutive_above += 1
                else:
                    break

        # 量能比：今日成交量 / 近5日均量
        volume_ratio = 0
        if vol_col and len(df) >= 5:
            recent_vols = df[vol_col].dropna().tolist()
            if len(recent_vols) >= 5:
                today_vol = recent_vols[-1]
                avg5_vol = sum(recent_vols[-6:-1]) / 5  # 不含今天的前5日均量
                volume_ratio = round(today_vol / avg5_vol, 2) if avg5_vol > 0 else 0

        change = float(df[change_col].iloc[-1]) if change_col else 0
        prev = latest_close - change
        change_pct = round(change / prev * 100, 2) if prev and prev != 0 else 0

        volume = float(df[vol_col].iloc[-1]) if vol_col else 0
        amount = float(df[amt_col].iloc[-1]) if amt_col else 0

        return {
            "股票代號": stock_code,
            "收盤價":   latest_close,
            "漲跌":     change,
            "漲跌幅%":  change_pct,
            "MA5":      ma5,
            "MA10":     ma10,
            "MA20":     ma20,
            "站上MA20": above_ma20,
            "均線排列": ma_alignment,
            "連續站上月線天數": consecutive_above,
            "量能比":   volume_ratio,
            "成交量":   volume,
            "成交金額": amount,
        }

    except Exception as e:
        log.debug(f"{stock_code} 股價失敗: {e}")
        return {}


def enrich_with_prices(df: pd.DataFrame, top_n: Optional[int] = None) -> pd.DataFrame:
    """
    主入口：把股價欄位合併進 DataFrame
    - 預設抓「全部」追蹤股票（不再截斷前50檔，避免排名50名後的股票永遠抓不到價格）
    - 若明確傳入 top_n，才會限制只抓前N檔（保留彈性給未來需要限流的情境）
    - 自動過濾疑似期貨合約等非個股代號，避免浪費API呼叫時間
    - 股票名稱從原本的 df 保留，不會被覆蓋
    - 計算「持股市值(千萬)」= 持股數 × 收盤價 / 10000000
    """
    if df.empty or "股票代號" not in df.columns:
        return df

    all_codes = df["股票代號"].dropna().astype(str).unique().tolist()
    codes = [c for c in all_codes if not _looks_like_futures_or_invalid(c)]
    skipped = len(all_codes) - len(codes)
    if skipped > 0:
        log.info(f"過濾 {skipped} 檔疑似非個股代號（期貨/無效），不列入股價抓取")

    if top_n is not None:
        codes = codes[:top_n]

    log.info(f"抓取 {len(codes)} 檔股價...")

    records = []
    failed_codes = []
    for i, code in enumerate(codes, 1):
        result = get_stock_price_single(code)
        if result:
            records.append(result)
        else:
            failed_codes.append(code)
        if i % 10 == 0:
            log.info(f"  股價進度 {i}/{len(codes)}")
        time.sleep(0.35)

    if failed_codes:
        log.warning(f"以下 {len(failed_codes)} 檔股價抓取失敗（可能是TWSE無資料/新股/興櫃/暫停交易）: {failed_codes}")

    if not records:
        log.warning("無法取得任何股價")
        return df

    price_df = pd.DataFrame(records)
    price_df["股票代號"] = price_df["股票代號"].astype(str).str.strip()
    df["股票代號"] = df["股票代號"].astype(str).str.strip()

    # 保留原本名稱欄，合併股價（不合入名稱）
    price_cols = ["股票代號", "收盤價", "漲跌", "漲跌幅%", "MA5", "MA10", "MA20", "站上MA20",
              "均線排列", "連續站上月線天數", "量能比", "成交量", "成交金額"]
    price_df = price_df[[c for c in price_cols if c in price_df.columns]]

    merged = df.merge(price_df, on="股票代號", how="left")

    # 計算持股市值
    if "持股數" in merged.columns and "收盤價" in merged.columns:
        shares = pd.to_numeric(
            merged["持股數"].astype(str).str.replace(",", ""), errors="coerce"
        )
        merged["持股市值(千萬)"] = (shares * merged["收盤價"] / 10000000).round(0)

    got = merged["收盤價"].notna().sum()
    log.info(f"股價合併完成：{got}/{len(merged)} 筆有股價")
    return merged


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 測試
    test_codes = ["2330", "2454", "2383", "6223", "2308", "3037"]
    log.info(f"=== 測試 {len(test_codes)} 檔股價 ===")

    records = []
    for code in test_codes:
        r = get_stock_price_single(code)
        if r:
            records.append(r)
            log.info(f"  {code}: 收盤={r['收盤價']} 漲跌幅={r['漲跌幅%']}% MA20={r['MA20']} 站上月線={r['站上MA20']}")
        time.sleep(0.3)

    print(f"\n成功取得 {len(records)}/{len(test_codes)} 檔")
