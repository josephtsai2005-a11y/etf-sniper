"""
margin_fetcher.py
融資融券資料抓取
來源：TWSE 公開資料 MI_MARGN（跟三大法人TWT38U同一套機制，selectType=ALL一次抓全市場）

設計目的：融資融券反映「散戶槓桿部位」，跟三大法人（法人動向）放在一起看，
才能判斷「量多量少到底是換手還是誘多出貨」——
  - 融資大增 + 法人賣超 + 股價滯漲 → 疑似誘多出貨（散戶追高、法人退場）
  - 融資持平/減少 + 法人買超 + 股價墊高 → 疑似真實換手（籌碼從弱手到強手）
  - 融資大減（斷頭/認賠）+ 法人買超 → 疑似籌碼沉澱期，法人低接
"""
import requests
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.twse.com.tw/",
})


def get_trade_date() -> str:
    now = datetime.now(TW_TZ)
    if now.hour < 16:
        now -= timedelta(days=1)
    while now.weekday() >= 5:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


def fetch_margin_all(trade_date: Optional[str] = None, retries: int = 2) -> pd.DataFrame:
    """
    抓取全市場個股融資融券餘額（一次API呼叫拿到全部股票，不用逐檔查詢）
    回傳：股票代號、融資餘額(張)、融資增減(張)、融券餘額(張)、融券增減(張)、券資比%

    注意：MI_MARGN這份報表回傳結構是 {"stat","date","tables":[...]}，不是單一fields/data，
    共兩個表格：tables[0]是大盤總計、tables[1]才是個股明細。
    個股明細的欄位名稱本身有重複（融資、融券兩邊的「買進」「賣出」「前日餘額」「今日餘額」
    完全同名、沒有前綴區分），只能用「欄位出現的位置順序」解析，不能用關鍵字比對欄位名稱：
      0=代號 1=名稱 2-6=融資(買進/賣出/現金償還/前日餘額/今日餘額) 7=融資限額
      8-12=融券(買進/賣出/現券償還/前日餘額/今日餘額) 13=融券限額 14=資券互抵 15=註記
    """
    if not trade_date:
        trade_date = get_trade_date()

    url = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
    params = {"response": "json", "date": trade_date, "selectType": "ALL"}

    last_error = None
    tables = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=15)
            data = resp.json()

            if data.get("stat") != "OK" or not data.get("tables"):
                log.warning(f"融資融券彙總無資料 ({trade_date})")
                return pd.DataFrame()

            tables = data["tables"]
            break
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.warning(f"融資融券彙總抓取失敗（已重試{retries}次）: {e}")
            return pd.DataFrame()

    try:
        # 個股明細固定在表格1（表格0是大盤總計，非個股）
        stock_table = None
        for t in tables:
            if "全部" in str(t.get("title", "")) or len(t.get("fields", [])) >= 14:
                stock_table = t
                break
        if stock_table is None and len(tables) >= 2:
            stock_table = tables[1]

        if stock_table is None or not stock_table.get("data"):
            log.warning(f"融資融券個股明細表格未找到 ({trade_date})")
            return pd.DataFrame()

        rows = stock_table["data"]

        def _num(v):
            if v is None:
                return None
            v = str(v).replace(",", "").replace("X", "").strip()
            try:
                return float(v)
            except ValueError:
                return None

        records = []
        for r in rows:
            if len(r) < 13:
                continue
            margin_buy, margin_sell = _num(r[2]), _num(r[3])
            margin_prev, margin_today = _num(r[5]), _num(r[6])
            short_buy, short_sell = _num(r[8]), _num(r[9])
            short_prev, short_today = _num(r[11]), _num(r[12])

            records.append({
                "股票代號": str(r[0]).strip(),
                "股票名稱": str(r[1]).strip(),
                "融資餘額(張)": margin_today,
                "融資增減(張)": (margin_today - margin_prev) if margin_today is not None and margin_prev is not None else None,
                "融券餘額(張)": short_today,
                "融券增減(張)": (short_today - short_prev) if short_today is not None and short_prev is not None else None,
            })

        result = pd.DataFrame(records)
        if result.empty:
            return result

        # 強制轉成標準數值型別（float64+NaN），避免records裡的Python None混雜造成object型別，
        # 導致後續除法/四捨五入出錯（NAType doesn't define __round__）
        for col in ["融資餘額(張)", "融資增減(張)", "融券餘額(張)", "融券增減(張)"]:
            result[col] = pd.to_numeric(result[col], errors="coerce")

        margin_balance_safe = result["融資餘額(張)"].replace(0, float("nan"))
        result["券資比%"] = (result["融券餘額(張)"] / margin_balance_safe * 100).round(2)
        result["抓取日期"] = trade_date
        log.info(f"融資融券彙總：{len(result)} 檔 ({trade_date})")
        return result

    except Exception as e:
        log.warning(f"融資融券資料解析失敗: {e}")
        return pd.DataFrame()


def fetch_margin_for_stocks(stock_codes: List[str], trade_date: Optional[str] = None) -> pd.DataFrame:
    """
    主入口：抓全市場融資融券後，篩選出你追蹤的股票清單
    stock_codes: 要篩選的股票代號清單（例如你的聰明錢名單股票）
    """
    all_margin = fetch_margin_all(trade_date)
    if all_margin.empty:
        return pd.DataFrame()

    codes_set = set(str(c) for c in stock_codes)
    filtered = all_margin[all_margin["股票代號"].isin(codes_set)].reset_index(drop=True)
    log.info(f"融資融券篩選：{len(filtered)}/{len(stock_codes)} 檔追蹤股票有資料")
    return filtered


def compute_margin_signal(row) -> str:
    """
    依融資增減幅度，給出簡易文字判讀（供AI報告/畫面顯示參考，非投資建議）
    需搭配法人買賣方向、股價走勢一起看，單看這個欄位不足以下結論
    """
    margin_change = row.get("融資增減(張)")
    margin_balance = row.get("融資餘額(張)")

    if pd.isna(margin_change) or pd.isna(margin_balance) or margin_balance == 0:
        return ""

    change_pct = margin_change / margin_balance * 100 if margin_balance else 0

    if change_pct >= 5:
        return "🔺 融資大增（散戶槓桿追價中）"
    elif change_pct <= -5:
        return "🔻 融資大減（散戶停損/獲利了結中）"
    elif change_pct > 0:
        return "融資小增"
    elif change_pct < 0:
        return "融資小減"
    return "融資持平"