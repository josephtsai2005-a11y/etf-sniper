"""
price_fetcher.py v4
串接 TWSE 股價 API
取得：收盤價、漲跌、漲跌幅%、MA20、站上月線、成交量、成交金額
注意：同時保留股票名稱（從 holdings_df 帶入，不從 TWSE 另外抓）

2026-09-01 優化（股價資料即時性）：
1. 新增 fetch_bulk_daily_quote()：一次抓取「全市場當日收盤行情」（TWSE MI_INDEX），
   跟institutional_fetcher.py／margin_fetcher.py已經在用的「抓全市場再過濾」模式一致。
   用途是當某檔股票的個別STOCK_DAY歷史查詢失敗（逾時/網路瞬斷/單檔限流）時，
   至少還能從這份全市場快照補上收盤價/成交量，不必整檔股票的股價完全開天窗
   （技術指標MA/KD/MACD仍需要歷史序列，這份快照無法取代，只作為收盤價的備援）。
   ⚠️ 尚未在正式環境驗證過欄位格式，部署前請先在本機執行：
       python -c "from price_fetcher import fetch_bulk_daily_quote; df=fetch_bulk_daily_quote(); print(len(df)); print(df.head())"
   若失敗或格式不符，函式回傳空DataFrame，不影響原本逐檔抓取的主流程。
2. backfill_prices_to_multi_sheet() 抽出共用邏輯為 backfill_prices_to_sheet()，
   新增 backfill_prices_to_smart_money_sheet()，讓23:00的股價回填機制也能覆蓋
   「聰明錢名單」分頁（原本只回填「多方驗證名單」，較早的聰明錢名單即使過期也不會被修正）。

2026-09-03 修正（除權息/股票分割假漲跌%）：
使用者發現「聰明錢名單」裡「緯穎」顯示漲跌-66.54%，查證後是當天股票分割「一股換三股」
除權（除權參考價2615元），不是真的崩跌。get_stock_price_single()原本直接拿「今收-昨收」
兩天的原始收盤價相減算漲跌%，沒有考慮除權息/股票分割會讓股本/參考價基準不連續，導致
算出誤導性的巨大假跌幅。新增ABNORMAL_CHANGE_PCT_THRESHOLD門檻（台股正常單日漲跌幅上限
±10%），偵測到遠超過這個範圍的「漲跌%」時，不提供誤導性數字，改把漲跌/漲跌幅%欄位留空，
並用「技術指標狀態」欄位明講「疑似除權息/股票分割」——兩個回填函式(backfill_prices_to_
multi_sheet/backfill_prices_to_smart_money_sheet)也把「技術指標狀態」加進回填欄位，
確保23:00的回填也會同步更新/清除這個標示。

2026-09-04 優化（月初MACD留空問題）：
get_stock_price_single()原本固定只抓「當月+上月」兩個月份的STOCK_DAY資料，MACD(12,26,9
EMA)需要至少26天收盤價才能算——每個月最初幾個交易日，兩個月加起來的天數可能還湊不到26天
（尤其上月本身天數較少時），導致MACD訊號整批留空，要等到月中資料自然累積回26天以上才會
恢復。改成：湊出來的資料不足26天時，再多抓一個月（上上月）補齊，讓月初也能盡量算出MACD，
不用乾等——只有真的不足26天時才會多打這一次API，月中以後不會觸發，不影響平常的抓取速度。

2026-09-04 修正（除權息/股票分割污染整段技術指標，不只是漲跌%）：
使用者指出2026-09-03那次修正只處理了「漲跌/漲跌幅%」這一個欄位，但MA5/MA10/MA20、KD、
MACD、ATR、布林通道、均線排列、連續站上月線天數這些技術指標，其實也是拿同一段「跨越除權
前後、原始價格沒對齊」的收盤/最高/最低價序列去算的，等於全部都算錯了，只是沒有像漲跌%
那樣被明顯攔下來、更難被發現。get_stock_price_single()改成：先掃描整段序列找出是否有
異常跳動（沿用ABNORMAL_CHANGE_PCT_THRESHOLD門檻），有的話只保留「最後一次異常跳動之後」
的資料來算技術指標（漲跌/漲跌幅%仍用完整序列算，維持09-03的偵測邏輯不受影響）——天數
因此可能變少，MA20/KD/MACD等需要較長天數的指標會因為天數不夠而暫時留空，這是誠實反映
「除權後至今資料還不夠久」，比拿新舊基準混算出一個看似正常、實際錯誤的數字好。
"""
import requests
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from retry_utils import retry_sheets_write
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.twse.com.tw/",
})

# 除權息/股票分割偵測用門檻：台股正常單日漲跌幅上限為±10%（新股上市前5個交易日、
# 全額交割股等少數情況除外，但這些少見情況本來就該人工另外確認，不在這裡處理）。
# 用「原始收盤價序列」直接相減若算出遠超過這個範圍的漲跌%，幾乎可以確定不是真的單日
# 行情，而是除權息／股票分割／減資等公司行動造成股本或參考價基準不連續，見
# get_stock_price_single() 內的使用處與2026-09-03的緯穎(6669)案例說明。
ABNORMAL_CHANGE_PCT_THRESHOLD = 20.0


def get_trade_date() -> str:
    """跟institutional_fetcher.py／margin_fetcher.py用同一套判斷邏輯，避免各檔案各寫一份、標準不一致"""
    now = datetime.now(TW_TZ)
    if now.hour < 16:
        now -= timedelta(days=1)
    while now.weekday() >= 5:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


def _roc_date_to_gregorian(roc_date_str: str) -> str:
    """
    把TWSE回傳的民國年日期字串轉成西元年8碼（YYYYMMDD），供跟TRADE_DATE比較用。

    背景：TWSE的STOCK_DAY等API固定回傳民國年格式的「日期」欄位（例如"115/08/31"代表
    2026-08-31，115=年份、用"/"分隔），但系統其他地方（TRADE_DATE、main.py的過期偵測、
    backfill_prices_to_multi_sheet的資料日期比對）用的都是西元年8碼格式（例如"20260831"）。

    2026-08-30部署的「資料日期」欄位／過期偵測／股價回填機制，一直沒有做這個轉換，
    直接拿民國年格式的字串（"115/08/31"）跟西元年格式（"20260831"）比較，
    這兩種格式不管實際資料新不新，字串永遠不會相等——等於這個比對從一開始就是壞的，
    「過期資料偵測」log天天都會誤報、「股價回填機制」永遠不會真的覆蓋任何資料，
    不是TWSE真的每次都延遲，是比對邏輯本身有問題。
    """
    try:
        parts = roc_date_str.strip().split("/")
        if len(parts) != 3:
            return ""
        roc_year, month, day = parts
        gregorian_year = int(roc_year) + 1911
        return f"{gregorian_year:04d}{int(month):02d}{int(day):02d}"
    except Exception:
        return ""


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


def fetch_bulk_daily_quote(trade_date: Optional[str] = None, retries: int = 2) -> pd.DataFrame:
    """
    一次抓取「當日全市場」收盤價/成交量/成交金額（TWSE MI_INDEX），取代逐檔呼叫STOCK_DAY，
    跟institutional_fetcher.py的fetch_all_institutional()／margin_fetcher.py的
    fetch_margin_all()同一套「抓全市場再過濾」模式——這兩個模組已經證明這個模式在這個
    專案裡是可行的，這裡是把同樣的做法延伸到股價。

    只提供「當日快照」（收盤價/成交量/成交金額），不含歷史序列，所以不能取代
    get_stock_price_single()——MA/KD/MACD等技術指標仍然需要逐檔呼叫STOCK_DAY取得歷史資料。
    這份資料的用途是：當某檔股票的STOCK_DAY歷史查詢失敗時，至少能從這裡補上收盤價，
    不用讓那檔股票的價格完全開天窗。

    刻意不從這份表格反推「漲跌」/「漲跌幅%」——price_fetcher.py先前已經踩過TWSE原始
    漲跌欄位正負號不可靠的坑（見get_stock_price_single內的說明），現在改成用收盤價序列
    自己算，這裡沒有歷史序列可以自己算，所以漲跌/漲跌幅%欄位留白，不去信任TWSE這張表的
    漲跌欄位，避免重蹈覆轍。

    ⚠️ 尚未在正式環境驗證過欄位格式（開發時的sandbox網路權限無法連線TWSE測試），
    部署前請先在本機手動確認（見檔案開頭說明）。失敗或格式不符時回傳空DataFrame，
    呼叫端會忽略備援、維持原本行為，不影響主流程。
    """
    if not trade_date:
        trade_date = get_trade_date()

    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    params = {"response": "json", "date": trade_date, "type": "ALLBUT0999"}

    last_error = None
    data = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=20)
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("tables"):
                log.warning(f"全市場當日收盤行情無資料 ({trade_date})")
                return pd.DataFrame()
            break
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.warning(f"全市場當日收盤行情抓取失敗（已重試{retries}次）: {e}")
            return pd.DataFrame()

    # 個股明細表格：用欄位特徵找（有「證券代號」+「收盤價」），不依賴固定index，
    # 因為TWSE這份報表過去調整過tables內部的表格順序/數量
    stock_table = None
    for t in data.get("tables", []):
        fields = t.get("fields", [])
        if "證券代號" in fields and "收盤價" in fields:
            stock_table = t
            break

    if stock_table is None or not stock_table.get("data"):
        log.warning(f"全市場當日收盤行情：找不到個股明細表格 ({trade_date})，"
                    f"實際tables標題：{[t.get('title') for t in data.get('tables', [])]}")
        return pd.DataFrame()

    fields = stock_table["fields"]
    rows = stock_table["data"]

    try:
        df = pd.DataFrame(rows, columns=fields)
    except Exception as e:
        log.warning(f"全市場當日收盤行情解析失敗（欄位數與資料不符）: {e}")
        return pd.DataFrame()

    def _num(v):
        v = str(v).replace(",", "").replace("+", "").replace("X", "").strip()
        if v in ("", "--", "---"):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    df = df.rename(columns={"證券代號": "股票代號"})
    df["股票代號"] = df["股票代號"].astype(str).str.strip()

    for col in ["收盤價", "成交股數", "成交金額", "開盤價", "最高價", "最低價"]:
        if col in df.columns:
            df[col] = df[col].apply(_num)

    df = df.rename(columns={"成交股數": "成交量"})
    df["資料日期"] = trade_date
    log.info(f"全市場當日收盤行情：{len(df)} 檔 ({trade_date})")
    return df[[c for c in ["股票代號", "收盤價", "成交量", "成交金額", "資料日期"] if c in df.columns]]


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
    prev_month_first = today.replace(day=1) - timedelta(days=1)
    prev_month_date = prev_month_first.strftime("%Y%m") + "01"
    prev2_month_date = (prev_month_first.replace(day=1) - timedelta(days=1)).strftime("%Y%m") + "01"

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

            # 2026-09-04優化（月初MACD留空問題）：MACD(12,26,9 EMA)需要至少26天收盤價才能算，
            # 「當月+上月」兩個月資料在每個月最初幾個交易日（尤其上月天數本身較少時，例如2月）
            # 可能還湊不到26天，導致MACD訊號整批留空，要等到月中資料自然累積回26天以上才會
            # 恢復——使用者確認這是資料量不足、不是程式壞掉之後，要求順便優化：資料不足26天時
            # 再多抓一個月（上上月）補齊，讓月初也能盡量算出MACD，不用乾等資料自然累積。只有
            # 真的不足26天時才會多打這一次API，月中以後不會觸發，不影響平常的抓取速度。
            if len(df) < 26:
                df_prev2 = fetch_month(prev2_month_date)
                if not df_prev2.empty:
                    df = pd.concat([df_prev2, df], ignore_index=True)

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
        high_col   = next((c for c in df.columns if "最高" in c), None)
        low_col    = next((c for c in df.columns if "最低" in c), None)
        change_col = next((c for c in df.columns if "漲跌" in c and "幅" not in c), None)
        vol_col    = next((c for c in df.columns if "成交股數" in c or "成交量" in c), None)
        amt_col    = next((c for c in df.columns if "成交金額" in c), None)

        if not close_col or df.empty:
            return {}

        # closes_full：完整、未截斷的收盤價序列，只用來偵測「今天是不是除權息當天」跟算
        # 「漲跌/漲跌幅%」（見下方，維持2026-09-03那次修正的邏輯不變）。
        closes_full = df[close_col].dropna().tolist()
        if not closes_full:
            return {}

        # 2026-09-04修正（除權息/股票分割污染整段技術指標）：
        # 使用者指出緯穎除權那次，2026-09-03的修正只處理了「漲跌/漲跌幅%」這一個欄位
        # （只比對最後兩天），但MA5/MA10/MA20、KD、MACD、ATR、布林通道、均線排列、
        # 連續站上月線天數這些技術指標，全部都是拿df裡整段「跨月合併」的收盤/最高/最低價
        # 序列去算的——如果這段期間裡發生過除權息/股票分割（股本或參考價基準不連續），
        # 序列裡會同時混著「除權前的原始高價」跟「除權後的原始低價」，所有技術指標全部都
        # 會算錯，只是不會像漲跌%那樣被明顯攔下來變成一個誇張的數字，而是安靜地產生一個
        # 看起來正常、但基準根本不一致的錯誤數字，比漲跌%的假崩跌更難被發現。
        # 修法：在計算任何技術指標之前，先掃描整段收盤價序列找出是否有異常跳動（沿用跟
        # 漲跌%偵測同一個ABNORMAL_CHANGE_PCT_THRESHOLD門檻），如果找到，只保留「最後一次
        # 異常跳動之後」的資料（也就是除權後、基準一致的那一段），捨棄除權前的舊資料——
        # 這會讓可用天數變少，MA20/KD/MACD等需要較長天數的指標可能會因此暫時算不出來
        # （沿用下面各指標本來就有的「len(closes)>=N」門檻，天數不夠時自然留空/留預設值），
        # 但這是誠實反映「除權後至今資料還不夠久」，比拿新舊基準混算出一個看似正常、實際
        # 錯誤的數字好——沿用專案一貫「資料不足/不可信就明講」的設計原則。
        split_boundary_pos = None
        prev_val = None
        for i, val in enumerate(df[close_col].tolist()):
            if pd.isna(val):
                continue
            if prev_val is not None and prev_val != 0:
                if abs((val - prev_val) / prev_val * 100) > ABNORMAL_CHANGE_PCT_THRESHOLD:
                    split_boundary_pos = i  # 保留最後一次異常跳動的位置，捨棄它之前的資料
            prev_val = val

        indicators_truncated = False
        if split_boundary_pos is not None:
            df = df.iloc[split_boundary_pos:].reset_index(drop=True)
            indicators_truncated = True

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

        # ── KD值（隨機指標，9,3,3）──────────────────────
        # RSV = (收盤-N日最低) / (N日最高-N日最低) * 100，K/D皆用3日平滑
        k_val, d_val, kd_signal = None, None, ""
        if high_col and low_col and len(closes) >= 9:
            n = 9
            highs = df[high_col].tolist()
            lows = df[low_col].tolist()
            k_series, d_series = [], []
            prev_k, prev_d = 50.0, 50.0  # 起始值慣例用50
            for i in range(len(closes)):
                if i < n - 1:
                    k_series.append(prev_k)
                    d_series.append(prev_d)
                    continue
                period_high = max(highs[i - n + 1:i + 1])
                period_low = min(lows[i - n + 1:i + 1])
                if period_high == period_low:
                    rsv = 50.0
                else:
                    rsv = (closes[i] - period_low) / (period_high - period_low) * 100
                cur_k = prev_k * 2 / 3 + rsv * 1 / 3
                cur_d = prev_d * 2 / 3 + cur_k * 1 / 3
                k_series.append(cur_k)
                d_series.append(cur_d)
                prev_k, prev_d = cur_k, cur_d

            k_val = round(k_series[-1], 1)
            d_val = round(d_series[-1], 1)

            if len(k_series) >= 3:
                diff_series = [k_series[i] - d_series[i] for i in range(len(k_series))]
                prev_diff = diff_series[-2]
                cur_diff = diff_series[-1]
                # 差距是否連續2天在縮小（不論正負，代表兩線正在靠近，交叉在醞釀中）
                gap_narrowing = abs(diff_series[-1]) < abs(diff_series[-2]) < abs(diff_series[-3])

                if prev_diff <= 0 and cur_diff > 0:
                    kd_signal = "🟢 黃金交叉"
                elif prev_diff >= 0 and cur_diff < 0:
                    kd_signal = "🔴 死亡交叉"
                elif cur_diff < 0 and gap_narrowing and k_val < 50:
                    kd_signal = "🌱 醞釀黃金交叉"  # 提早訊號：還沒交叉，但K正在低檔追上D
                elif cur_diff > 0 and gap_narrowing and k_val > 50:
                    kd_signal = "🍂 醞釀死亡交叉"  # 提早訊號：還沒交叉，但K正在高檔被D追上
                elif cur_diff > 0:
                    kd_signal = "K>D"
                else:
                    kd_signal = "K<D"

                # 高檔過熱：K、D兩者都卡在80以上，不論有沒有交叉都值得留意——
                # 這種情況常常是「持續噴出、指標鈍化」，可能還沒死叉但風險已經在累積
                # （2026-08-28使用者比對真實券商資料後提出的需求：K/D高檔糾結，比單純等死叉更早示警）
                if k_val >= 80 and d_val >= 80:
                    kd_signal = f"🌡️ 高檔過熱（{kd_signal}）"

        # ── MACD（12,26,9 EMA）───────────────────────────
        dif_val, macd_signal_val, macd_hist, macd_cross = None, None, None, ""
        if len(closes) >= 26:
            close_series = pd.Series(closes)
            ema12 = close_series.ewm(span=12, adjust=False).mean()
            ema26 = close_series.ewm(span=26, adjust=False).mean()
            dif_series = ema12 - ema26
            signal_series = dif_series.ewm(span=9, adjust=False).mean()
            hist_series = dif_series - signal_series

            dif_val = round(dif_series.iloc[-1], 2)
            macd_signal_val = round(signal_series.iloc[-1], 2)
            macd_hist = round(hist_series.iloc[-1], 2)

            if len(hist_series) >= 3:
                h = hist_series.tolist()
                prev_hist, cur_hist = h[-2], h[-1]
                # 柱狀連續2天縮小（力道衰竭中，不論正負）
                hist_shrinking = abs(h[-1]) < abs(h[-2]) < abs(h[-3])

                if prev_hist <= 0 and cur_hist > 0:
                    macd_cross = "🟢 黃金交叉"
                elif prev_hist >= 0 and cur_hist < 0:
                    macd_cross = "🔴 死亡交叉"
                elif cur_hist < 0 and hist_shrinking:
                    macd_cross = "🌱 空方動能趨緩"  # 提早訊號：柱狀仍是負的，但空方力道在減弱
                elif cur_hist > 0 and hist_shrinking:
                    macd_cross = "🍂 多方動能趨緩"  # 提早訊號：柱狀仍是正的，但多方力道在減弱
                elif cur_hist > 0:
                    macd_cross = "柱狀翻紅"
                else:
                    macd_cross = "柱狀翻綠"

        # ── 背離偵測（提早出場訊號中最經典的一種）─────────────
        # 股價創近期新高，但KD沒有跟著創新高 → 動能其實已經衰竭，價格是靠慣性衝高
        divergence_signal = ""
        lookback = 10
        if len(closes) >= lookback and k_val is not None:
            try:
                recent_closes = closes[-lookback:]
                recent_k = k_series[-lookback:]
                price_making_new_high = recent_closes[-1] >= max(recent_closes)
                kd_not_confirming = recent_k[-1] < max(recent_k[:-1]) - 5  # K值明顯低於前段高點
                if price_making_new_high and kd_not_confirming:
                    divergence_signal = "⚠️ 頂部背離：價格創高但KD未跟上"
            except Exception:
                pass

        # ── 布林通道（20期，2倍標準差）────────────────────────
        # 中軌沿用MA20；上下軌反映近期波動範圍，可看「是否觸及極端」跟「通道寬窄變化（噴出前兆）」
        bb_upper, bb_lower, bb_position, bb_signal = None, None, "", ""
        if len(closes) >= 20:
            recent20 = closes[-20:]
            std20 = pd.Series(recent20).std()
            bb_mid = ma20
            bb_upper = round(bb_mid + 2 * std20, 2)
            bb_lower = round(bb_mid - 2 * std20, 2)
            bb_width = round((bb_upper - bb_lower) / bb_mid * 100, 2) if bb_mid else 0  # 通道寬度%，越窄代表波動壓縮

            if latest_close >= bb_upper:
                bb_position = "🔥 觸及上軌"
            elif latest_close <= bb_lower:
                bb_position = "❄️ 觸及下軌"
            elif latest_close >= bb_mid:
                bb_position = "中軌之上"
            else:
                bb_position = "中軌之下"

            # 通道壓縮偵測：近5天通道寬度是否持續收斂，是「即將噴出」的經典早期訊號（不分方向）
            if len(closes) >= 25:
                widths = []
                for i in range(5):
                    idx_end = len(closes) - i
                    window = closes[idx_end - 20:idx_end]
                    w_mid = sum(window) / 20
                    w_std = pd.Series(window).std()
                    w_width = (w_mid + 2 * w_std - (w_mid - 2 * w_std)) / w_mid * 100 if w_mid else 0
                    widths.append(w_width)
                widths = widths[::-1]  # 轉成時間正序
                if widths[-1] < widths[-3] < widths[-5]:
                    bb_signal = "🌊 通道壓縮中（波動率降低，可能醞釀噴出，方向未定）"

        # ── ATR 真實波動幅度（14期）────────────────────────────
        # 反映該股「正常波動的絕對金額」，可用來動態設計停損（波動大的股票給寬一點停損）
        atr_val, atr_pct = None, None
        if high_col and low_col and len(closes) >= 15:
            highs_full = df[high_col].tolist()
            lows_full = df[low_col].tolist()
            trs = []
            for i in range(1, len(closes)):
                tr = max(
                    highs_full[i] - lows_full[i],
                    abs(highs_full[i] - closes[i - 1]),
                    abs(lows_full[i] - closes[i - 1]),
                )
                trs.append(tr)
            if len(trs) >= 14:
                atr_val = round(sum(trs[-14:]) / 14, 2)
                atr_pct = round(atr_val / latest_close * 100, 2) if latest_close else None

        # ── 技術面共振燈號：把均線/MACD/KD三個不同週期指標的方向合成一個燈號 ──
        # 三個都同意才是「共振」；方向不一致時明確標示「分歧」，不強行合併成單一買賣訊號
        tech_score = 0
        if ma_alignment == "多頭排列":
            tech_score += 1
        elif ma_alignment == "空頭排列":
            tech_score -= 1

        macd_bull_set = {"🟢 黃金交叉", "柱狀翻紅", "🌱 空方動能趨緩"}
        macd_bear_set = {"🔴 死亡交叉", "柱狀翻綠", "🍂 多方動能趨緩"}
        if macd_cross in macd_bull_set:
            tech_score += 1
        elif macd_cross in macd_bear_set:
            tech_score -= 1

        kd_bull_set = {"🟢 黃金交叉", "🌱 醞釀黃金交叉", "K>D"}
        kd_bear_set = {"🔴 死亡交叉", "🍂 醞釀死亡交叉", "K<D"}
        if kd_signal in kd_bull_set:
            tech_score += 1
        elif kd_signal in kd_bear_set:
            tech_score -= 1

        if tech_score == 3:
            resonance_signal = "🟢🟢 多頭共振"
        elif tech_score >= 1:
            resonance_signal = "🟢 偏多"
        elif tech_score == 0:
            resonance_signal = "⚠️ 訊號分歧"
        elif tech_score >= -2:
            resonance_signal = "🔴 偏空"
        else:
            resonance_signal = "🔴🔴 空頭共振"

        # 漲跌/漲跌幅：改用收盤價序列自己算（今日收盤 - 昨日收盤），
        # 不再直接信任TWSE原始「漲跌價差」欄位的文字格式——
        # 該欄位的正負號編碼在TWSE不同回應裡不一定一致，直接float()轉換曾經出現正負號顛倒的案例
        # （2026-08-28發現：某股實際上漲+3.43%，此欄位算出來卻是-3.43%，數值大小對但方向錯）
        # 注意：這裡刻意用closes_full（未被上面除權息截斷的完整序列），不是closes——
        # 截斷後的closes可能只剩下今天一筆（除權息剛好發生在今天時），會讓下面這段偵測
        # 今天是不是除權息當天的邏輯失效。closes_full永遠保留完整的「今收-昨收」兩天，
        # 才能正確抓到「今天」這筆的異常跳動。
        if len(closes_full) >= 2:
            change = round(closes_full[-1] - closes_full[-2], 2)
            change_pct = round(change / closes_full[-2] * 100, 2) if closes_full[-2] else 0
        else:
            change = float(df[change_col].iloc[-1]) if change_col else 0
            change_pct = round(change / (latest_close - change) * 100, 2) if (latest_close - change) else 0

        # 除權息/股票分割偵測（2026-09-03新增）：
        # 使用者實測發現「緯穎」顯示漲跌-66.54%，查證後是當天股票分割「一股換三股」除權
        # （除權參考價2615元），股本／參考價基準因此不連續，上面用「今收-昨收」原始價格
        # 直接相減算出來的65%~66%「跌幅」其實是假訊號，不是真的單日崩跌——2610元的收盤價
        # 本身沒有錯，錯的是拿它跟除權前的原始收盤價直接比較。
        # 這裡不嘗試回頭推算「還原權值後的正確漲跌%」（需要額外查除權息公告資料才能算準，
        # 超出這支fetcher的範圍），而是採保守做法：偵測到超出台股正常單日漲跌幅上限
        # （±10%）甚遠的異常跳動時，承認「今天没辦法用簡單相減算出有意義的漲跌%」，
        # 把漲跌/漲跌幅%欄位留空並用「技術指標狀態」欄位明講原因，不讓使用者被誤導的
        # 假數字騙到——沿用專案一貫「資料不足/不可信就明講」的設計原則。
        split_note = ""
        if change_pct is not None and abs(change_pct) > ABNORMAL_CHANGE_PCT_THRESHOLD:
            split_note = "⚠️ 疑似除權息/股票分割（原始股價未還原權值），今日漲跌%不具比較意義"
            change = None
            change_pct = None
        elif indicators_truncated:
            # 2026-09-04新增：今天本身不是除權息當天（上面沒被攔下），但這段查詢期間裡
            # 之前發生過除權息/股票分割，技術指標已經改用除權後的資料重新計算——天數
            # 可能因此比平常少，MA20/KD/MACD等需要較長天數的指標可能暫時顯示空白，
            # 明講原因，不讓使用者誤以為是抓取失敗。
            split_note = (f"ℹ️ 近期疑似發生除權息/股票分割，技術指標已改用除權後資料重新"
                          f"計算（僅{len(closes)}個交易日，天數不足的指標會暫時留空）")

        # 資料日期：回傳實際抓到的最新一筆日期，供上層比對是否跟預期交易日一致，
        # 偵測「資料整天沒更新、停留在前一天」這種過期狀況（不會自動修正，只是讓過期狀況可被看見）。
        #
        # 重要：TWSE回傳的「日期」欄位是民國年格式（例如"115/08/31"），這裡一定要轉成
        # 西元年8碼（"20260831"）才能跟系統其他地方用的TRADE_DATE正確比較——
        # 這是2026-08-31發現的問題：轉換這一步原本漏掉了，導致「資料日期」跟TRADE_DATE
        # 用的是兩種不同曆法，字串永遠不會相等，讓「過期資料偵測」天天誤報、
        # 「股價回填機制」永遠判定為失敗、無法真的把資料寫回去，即使TWSE其實已經更新了。
        date_col_name = next((c for c in df.columns if "日期" in c), None)
        raw_data_date = str(df[date_col_name].iloc[-1]).strip() if date_col_name else ""
        latest_data_date = _roc_date_to_gregorian(raw_data_date)

        volume = float(df[vol_col].iloc[-1]) if vol_col else 0
        amount = float(df[amt_col].iloc[-1]) if amt_col else 0

        return {
            "股票代號": stock_code,
            "收盤價":   latest_close,
            "漲跌":     change,
            "漲跌幅%":  change_pct,
            "資料日期": latest_data_date,
            "MA5":      ma5,
            "MA10":     ma10,
            "MA20":     ma20,
            "站上MA20": above_ma20,
            "均線排列": ma_alignment,
            "連續站上月線天數": consecutive_above,
            "量能比":   volume_ratio,
            "K值":      k_val,
            "D值":      d_val,
            "KD訊號":   kd_signal,
            "DIF":      dif_val,
            "MACD":     macd_signal_val,
            "MACD柱狀": macd_hist,
            "MACD訊號": macd_cross,
            "背離警示": divergence_signal,
            "布林上軌": bb_upper,
            "布林下軌": bb_lower,
            "布林位置": bb_position,
            "布林壓縮": bb_signal,
            "ATR":      atr_val,
            "ATR%":     atr_pct,
            "技術面共振": resonance_signal,
            "成交量":   volume,
            "成交金額": amount,
            "技術指標狀態": split_note,
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

    2026-09-01新增：全市場當日收盤行情備援。個別股票的STOCK_DAY歷史查詢完全失敗時
    （逾時/網路瞬斷/單檔限流，回傳{}），改用fetch_bulk_daily_quote()這份全市場快照
    補上收盤價/成交量，並用「技術指標狀態」欄位明確標示這筆是備援資料、技術指標缺失，
    不會偽裝成跟正常路徑一樣完整——沿用專案一貫「資料不足就明講」的設計原則。
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

    # 全市場當日收盤行情備援：1次API呼叫，個別股票查詢失敗時用來補收盤價，
    # 這裡失敗也不影響主流程，只是備援機制失效、退回原本行為（該股票價格留空）
    bulk_lookup = {}
    try:
        bulk_quote = fetch_bulk_daily_quote()
        if not bulk_quote.empty:
            bulk_lookup = bulk_quote.set_index("股票代號").to_dict(orient="index")
    except Exception as e:
        log.debug(f"全市場當日收盤行情備援抓取失敗（不影響主流程）: {e}")

    records = []
    failed_codes = []
    fallback_codes = []
    for i, code in enumerate(codes, 1):
        result = get_stock_price_single(code)
        if not result and code in bulk_lookup:
            b = bulk_lookup[code]
            if b.get("收盤價") is not None:
                result = {
                    "股票代號": code,
                    "收盤價":   b.get("收盤價"),
                    "資料日期": b.get("資料日期"),
                    "成交量":   b.get("成交量"),
                    "成交金額": b.get("成交金額"),
                    "技術指標狀態": "⚠️ 僅收盤價（個股歷史查詢失敗，已用全市場備援資料補收盤價，技術指標缺失）",
                }
                fallback_codes.append(code)
        if result:
            records.append(result)
        else:
            failed_codes.append(code)
        if i % 10 == 0:
            log.info(f"  股價進度 {i}/{len(codes)}")
        time.sleep(0.35)

    if fallback_codes:
        log.info(f"以下 {len(fallback_codes)} 檔改用全市場備援資料補上收盤價（技術指標缺失）: {fallback_codes}")
    if failed_codes:
        log.warning(f"以下 {len(failed_codes)} 檔股價抓取失敗（可能是TWSE無資料/新股/興櫃/暫停交易）: {failed_codes}")

    if not records:
        log.warning("無法取得任何股價")
        return df

    price_df = pd.DataFrame(records)
    price_df["股票代號"] = price_df["股票代號"].astype(str).str.strip()
    df["股票代號"] = df["股票代號"].astype(str).str.strip()

    # 保留原本名稱欄，合併股價（不合入名稱）
    price_cols = ["股票代號", "收盤價", "漲跌", "漲跌幅%", "資料日期", "MA5", "MA10", "MA20", "站上MA20",
              "均線排列", "連續站上月線天數", "量能比", "K值", "D值", "KD訊號",
              "DIF", "MACD", "MACD柱狀", "MACD訊號", "背離警示",
              "布林上軌", "布林下軌", "布林位置", "布林壓縮", "ATR", "ATR%", "技術面共振",
              "成交量", "成交金額", "技術指標狀態"]
    price_df = price_df[[c for c in price_cols if c in price_df.columns]]

    merged = df.merge(price_df, on="股票代號", how="left")

    # 計算持股市值
    if "持股數" in merged.columns and "收盤價" in merged.columns:
        shares = pd.to_numeric(
            merged["持股數"].astype(str).str.replace(",", ""), errors="coerce"
        )
        merged["持股市值(千萬)"] = (shares * merged["收盤價"] / 10000000).round(0)

    got = merged["收盤價"].notna().sum()
    log.info(f"股價合併完成：{got}/{len(merged)} 筆有股價（含備援 {len(fallback_codes)} 筆）")
    return merged


def backfill_prices_to_sheet(ss, sheet_name: str, trade_date: str,
                              backfill_cols: List[str], delay: float = 0.3) -> int:
    """
    通用股價回填：把指定分頁裡過期的股價/技術指標欄位，用當天最新資料覆蓋。

    從原本只針對「多方驗證名單」硬編的邏輯抽出來，讓其他分頁（例如「聰明錢名單」）
    也能套用同一套回填機制，不用重複寫一份幾乎一樣的程式碼。

    設計沿用原本 backfill_prices_to_multi_sheet 的邏輯：假設分頁第1列是標題、
    第2列(index=1)是真正欄位標題、第3列起是資料；只有重抓到的「資料日期」
    確認等於trade_date，才會覆蓋更新該列，避免用另一批依然過期的資料去覆蓋，白忙一場。

    回傳：成功回填的股票筆數（0代表這次重抓依然拿不到當天資料，可能TWSE延遲更嚴重，
    或這個分頁本身還沒有資料）。
    """
    try:
        ws = ss.worksheet(sheet_name)
        all_values = ws.get_all_values()
    except Exception as e:
        log.warning(f"股價回填失敗，讀取「{sheet_name}」失敗: {e}")
        return 0

    if len(all_values) < 3:
        log.warning(f"股價回填失敗：「{sheet_name}」目前沒有足夠資料")
        return 0

    header = all_values[1]
    data_rows = all_values[2:]
    if "股票代號" not in header:
        log.warning(f"股價回填失敗：「{sheet_name}」找不到「股票代號」欄位")
        return 0

    df = pd.DataFrame(data_rows, columns=header)
    stock_codes = df["股票代號"].dropna().astype(str).unique().tolist()
    if not stock_codes:
        return 0

    for col in backfill_cols:
        if col not in df.columns:
            df[col] = ""

    updated = 0
    stale_still = 0
    for idx, row in df.iterrows():
        code = str(row["股票代號"]).strip()
        try:
            live = get_stock_price_single(code)
        except Exception:
            live = None
        time.sleep(delay)

        if not live:
            continue

        fetched_date = str(live.get("資料日期", "")).replace("-", "").strip()
        if fetched_date and fetched_date != trade_date:
            stale_still += 1
            continue  # 這次重抓依然是舊資料，不覆蓋，維持原值

        for col in backfill_cols:
            if col in live:
                df.at[idx, col] = live[col]
        updated += 1

    if updated > 0:
        title_row = [all_values[0][0] if all_values[0] else f"{sheet_name} {trade_date}"]
        cols = df.columns.tolist()
        rows = df.fillna("").values.tolist()

        def _do_write():
            ws.clear()
            ws.append_row(title_row)
            time.sleep(2)
            ws.append_row(cols)
            ws.append_rows(rows, value_input_option="USER_ENTERED")

        try:
            # 這裡是clear()+整表重寫，不是只回填的幾個欄位——寫入失敗時值得多重試幾次，
            # 因為失敗代表整張表被清空後沒寫回去，不只是回填的部分沒生效
            retry_sheets_write(_do_write, retries=3, base_wait=8, label=f"{sheet_name}股價回填寫入")
            log.info(f"「{sheet_name}」股價回填完成：{updated}/{len(df)} 檔已更新（資料日期：{trade_date}）"
                      f"，仍有{stale_still}檔重抓後依然是舊資料")
        except Exception as e:
            log.error(f"「{sheet_name}」股價回填寫入失敗（已重試仍失敗），可能已被清空但寫入未完成，請檢查Sheets: {e}")
            return 0
    else:
        log.warning(f"「{sheet_name}」股價回填：本次重抓{len(stock_codes)}檔全部依然是舊資料（TWSE延遲比預期更嚴重）")

    return updated


def backfill_prices_to_multi_sheet(ss, trade_date: str, delay: float = 0.3) -> int:
    """
    多方驗證名單的股價回填（原本的唯一回填目標）。
    2026-08-28發現TWSE股價資料當天公布得比平常晚，16:45的daily job抓到的整批股票都停留在
    「前一交易日」的舊資料，卻沒有任何錯誤訊息。這個函式設計成在較晚時段（23:00 ai job，
    比16:45多爭取6小時公布時間）呼叫，對名單裡每檔股票重新確認一次是否已有當天資料。
    """
    return backfill_prices_to_sheet(
        ss, "多方驗證名單", trade_date,
        ["收盤價", "漲跌", "漲跌幅%", "KD訊號", "MACD訊號", "背離警示", "ATR%", "技術面共振", "技術指標狀態"],
        delay=delay,
    )


def backfill_prices_to_smart_money_sheet(ss, trade_date: str, delay: float = 0.3) -> int:
    """
    聰明錢名單的股價回填（2026-09-01新增）。
    「聰明錢名單」跟「多方驗證名單」都在16:45寫入、都可能受到TWSE股價延遲公布影響，
    但原本的回填機制只覆蓋「多方驗證名單」——使用者如果看的是聰明錢名單，
    23:00之後仍可能看到過期股價卻不自知。這裡用同一套回填邏輯補上這個缺口。
    """
    return backfill_prices_to_sheet(
        ss, "聰明錢名單", trade_date,
        ["收盤價", "漲跌幅%", "MA5", "MA10", "MA20", "站上MA20",
         "均線排列", "連續站上月線天數", "量能比", "成交量", "技術指標狀態"],
        delay=delay,
    )