"""
margin_fetcher.py
融資融券資料抓取
來源：TWSE 公開資料 MI_MARGN（跟三大法人TWT38U同一套機制，selectType=ALL一次抓全市場）

設計目的：融資融券反映「散戶槓桿部位」，跟三大法人（法人動向）放在一起看，
才能判斷「量多量少到底是換手還是誘多出貨」——
  - 融資大增 + 法人賣超 + 股價滯漲 → 疑似誘多出貨（散戶追高、法人退場）
  - 融資持平/減少 + 法人買超 + 股價墊高 → 疑似真實換手（籌碼從弱手到強手）
  - 融資大減（斷頭/認賠）+ 法人買超 → 疑似籌碼沉澱期，法人低接

2026-09-02 修正（籌碼矛盾敘事漏看股價走勢）：
使用者實測發現一個真實案例：某股當天股價上漲+3.44%（KD顯示高檔過熱），融資大減、
三大法人淨買超，系統卻把這個組合講成「疑似法人低接（散戶停損認賠，法人卻在買）」——
停損認賠是股價下跌時才會發生的行為，一支上漲、甚至過熱的股票沒理由讓散戶恐慌停損，
這個敘事在這種情境下根本說不通。

追查後發現：原本的判斷邏輯（在這個檔案的backfill_margin_signals_to_multi_sheet()，
以及institutional_fetcher.py的cross_with_etf()裡各自維護一份幾乎一樣的邏輯）只看
「融資增減方向」跟「三大法人買賣方向」兩個變數，完全沒有用到股價漲跌方向——即使
compute_margin_signal()自己的docstring早就寫明「需搭配法人買賣方向、股價走勢一起看，
單看這個欄位不足以下結論」，實際的矛盾判斷式卻漏接了股價走勢這個變數。

新增compute_chip_conflict()，把股價漲跌方向（price_change_pct）一起納入判斷，取代
原本兩處各自維護的重複邏輯，institutional_fetcher.py改成直接import這裡的版本，
避免兩份邏輯不同步。
"""
import requests
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List
import pytz
from retry_utils import retry_sheets_write

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


def fetch_market_margin_summary(trade_date: Optional[str] = None, retries: int = 2) -> dict:
    """
    抓取「全市場」融資融券彙總（不分個股），來自MI_MARGN的tables[0]
    用於判斷散戶整體槓桿情緒（大盤層級，跟fetch_margin_all的個股層級是互補的兩種顆粒度）
    回傳：{融資買進, 融資賣出, 融資前日餘額, 融資今日餘額, 融資增減,
           融券買進, 融券賣出, 融券前日餘額, 融券今日餘額, 融券增減}
    """
    if not trade_date:
        trade_date = get_trade_date()

    url = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
    params = {"response": "json", "date": trade_date, "selectType": "ALL"}

    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=15)
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("tables"):
                return {}
            tables = data["tables"]
            break
        except Exception as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.warning(f"全市場融資融券彙總抓取失敗: {e}")
            return {}

    try:
        summary_table = tables[0]  # tables[0]固定是大盤總計（信用交易統計）
        rows = summary_table.get("data", [])

        def _num(v):
            try:
                return float(str(v).replace(",", "").strip())
            except (ValueError, TypeError):
                return None

        result = {}
        for r in rows:
            if len(r) < 6:
                continue
            item = str(r[0])
            buy, sell, prev, today = _num(r[1]), _num(r[2]), _num(r[4]), _num(r[5])
            if "融資" in item and "金額" not in item:
                result["融資買進"] = buy
                result["融資賣出"] = sell
                result["融資前日餘額"] = prev
                result["融資今日餘額"] = today
                result["融資增減"] = (today - prev) if today is not None and prev is not None else None
            elif "融券" in item:
                result["融券買進"] = buy
                result["融券賣出"] = sell
                result["融券前日餘額"] = prev
                result["融券今日餘額"] = today
                result["融券增減"] = (today - prev) if today is not None and prev is not None else None

        result["抓取日期"] = trade_date
        return result

    except Exception as e:
        log.warning(f"全市場融資融券彙總解析失敗: {e}")
        return {}


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


def compute_chip_conflict(signal: str, inst_total, price_change_pct=None) -> str:
    """
    籌碼矛盾/換手敘事：融資（散戶槓桿）方向 × 三大法人方向 × 股價漲跌方向 綜合判斷。

    2026-09-02修正重點：新增price_change_pct參數，取代原本只看「融資訊號」+「法人買賣
    方向」兩個變數就下定論的做法（原本任何一天只要「融資大減+法人買超」就一律講成
    「散戶停損認賠」，不管股價當天其實是漲是跌，導致股價明明在漲、KD還過熱的情況下，
    系統也講成「疑似停損認賠」，這種敘事本身就說不通——停損認賠只在下跌時才成立）。

    判斷邏輯：
    - 融資大增 + 法人賣超：這個組合本身（散戶追價 vs 法人減碼）方向已經相反，不需要靠
      股價方向才成立，維持「疑似誘多出貨/法人調節」的判斷，但依股價方向補充説明出貨壓力
      是否已經反映在價格上。
    - 融資大減 + 法人買超 + 股價上漲：改判為「散戶獲利了結、法人逢高續買」，這其實是
      正常換手（籌碼從弱手轉強手），不算恐慌訊號，用💡而非⚠️標示。
    - 融資大減 + 法人買超 + 股價下跌（或持平）：維持原本「疑似法人低接（散戶停損認賠，
      法人卻在買）」的解讀，這才是原本設計「逢低承接」想捕捉的情境。
    - price_change_pct 允許傳 None（呼叫端沒有漲跌幅資料時），此時退回不預設方向的中性
      文字，不再武斷地講「認賠」。

    用`in`子字串比對signal而非精確相等，讓這個函式同時相容
    compute_margin_signal()產生的完整文字（含括號說明）跟只有「🔺 融資大增」這種簡短版本，
    兩個呼叫端（本檔案的backfill、institutional_fetcher.py的cross_with_etf）不用統一
    成同一種signal格式也能正確運作。
    """
    inst_total = inst_total if pd.notna(inst_total) else 0

    pct = None
    try:
        if price_change_pct is not None and pd.notna(price_change_pct):
            pct = float(price_change_pct)
    except (ValueError, TypeError):
        pct = None

    signal = str(signal or "")

    if "融資大增" in signal and inst_total < 0:
        if pct is not None and pct < 0:
            return "⚠️ 疑似誘多出貨（融資追價中，法人卻在賣，股價已下跌，出貨壓力可能已反映）"
        return "⚠️ 疑似法人逢高調節（融資追價中，法人卻在賣，股價暫未走弱，須留意後續）"

    elif "融資大減" in signal and inst_total > 0:
        if pct is not None and pct > 0:
            return "💡 疑似獲利了結換手（散戶減碼獲利了結，法人逢高續買，屬正常換手非恐慌訊號）"
        elif pct is not None and pct < 0:
            return "💡 疑似法人低接（散戶停損認賠，法人卻在買）"
        else:
            return "💡 疑似法人承接（融資減少、法人卻在買，股價漲跌不明顯，方向待觀察）"

    return ""


def backfill_margin_signals_to_multi_sheet(ss, trade_date: str) -> int:
    """
    融資融券回填機制：TWSE融資融券日報公布時間約晚上9:30（比三大法人的下午5:00晚很多），
    daily job在16:45執行時，當天的融資融券資料根本還沒公布，抓到的一定是空的——
    這不是門檻設太嚴，是抓取時間點抓早了。

    這個函式設計成在較晚的時段（例如23:00的ai job，確定晚於21:30公布時間）呼叫，
    重新抓一次當天真正的融資融券資料，回頭把「多方驗證名單」分頁裡的
    「融資增減(張)」「券資比%」「融資訊號」「籌碼矛盾」這幾欄用新資料覆蓋更新，
    其他欄位（法人/技術面/評分等）維持16:45寫入的原值不動。

    2026-09-02：籌碼矛盾的敘事改用compute_chip_conflict()，加入股價漲跌方向一起判斷
    （股價欄位在這個分頁裡本來就有，之前只是沒有拿來用）。

    回傳：成功回填的股票筆數（0代表融資融券資料這次依然抓不到，可能TWSE還沒公布或延遲更久）
    """
    import time as _t

    SHEET_MULTI = "多方驗證名單"
    try:
        ws = ss.worksheet(SHEET_MULTI)
        all_values = ws.get_all_values()
    except Exception as e:
        log.warning(f"回填融資融券失敗，讀取「{SHEET_MULTI}」失敗: {e}")
        return 0

    if len(all_values) < 3:
        log.warning(f"回填融資融券失敗：「{SHEET_MULTI}」目前沒有足夠資料")
        return 0

    header = all_values[1]  # 第1列是title、第2列(index=1)才是真正欄位標題
    data_rows = all_values[2:]

    if "股票代號" not in header:
        log.warning(f"回填融資融券失敗：「{SHEET_MULTI}」找不到「股票代號」欄位")
        return 0

    df = pd.DataFrame(data_rows, columns=header)

    stock_codes = df["股票代號"].dropna().astype(str).unique().tolist()
    if not stock_codes:
        return 0

    margin_df = fetch_margin_for_stocks(stock_codes, trade_date)
    if margin_df.empty:
        log.warning(f"回填融資融券：{trade_date} 這次重新抓取依然沒有資料"
                     f"（可能TWSE還沒公布，或今天休市），暫不更新")
        return 0

    margin_df["股票代號"] = margin_df["股票代號"].astype(str).str.strip()
    margin_lookup = margin_df.set_index("股票代號").to_dict(orient="index")

    for col in ["融資增減(張)", "券資比%", "融資訊號", "籌碼矛盾"]:
        if col not in df.columns:
            df[col] = ""

    df["三大合計_num"] = pd.to_numeric(df.get("三大合計"), errors="coerce")
    # 股價漲跌方向：這個分頁在16:45就已經寫入「漲跌幅%」欄位，這裡把它一起讀出來，
    # 用於判斷「融資大減/大增」的敘事到底該講「停損」還是「獲利了結」
    df["漲跌幅%_num"] = pd.to_numeric(df.get("漲跌幅%"), errors="coerce")

    updated = 0
    for idx, row in df.iterrows():
        code = str(row["股票代號"]).strip()
        m = margin_lookup.get(code)
        if not m:
            continue

        bal = m.get("融資餘額(張)")
        chg = m.get("融資增減(張)")
        df.at[idx, "融資增減(張)"] = chg if chg is not None else ""
        df.at[idx, "券資比%"] = m.get("券資比%", "")

        signal = compute_margin_signal({"融資餘額(張)": bal, "融資增減(張)": chg})
        df.at[idx, "融資訊號"] = signal

        inst_total = row["三大合計_num"]
        price_change_pct = row["漲跌幅%_num"]
        conflict = compute_chip_conflict(signal, inst_total, price_change_pct)
        df.at[idx, "籌碼矛盾"] = conflict

        updated += 1

    df = df.drop(columns=["三大合計_num", "漲跌幅%_num"])

    if updated > 0:
        title_row = [all_values[0][0] if all_values[0] else f"{SHEET_MULTI} {trade_date}"]
        cols = df.columns.tolist()
        rows = df.fillna("").values.tolist()

        def _do_write():
            ws.clear()
            ws.append_row(title_row)
            _t.sleep(2)
            ws.append_row(cols)
            ws.append_rows(rows, value_input_option="USER_ENTERED")

        try:
            # 跟股價回填一樣，這裡是clear()+整表重寫「多方驗證名單」，失敗代表整張表被清空
            # 卻沒寫回去，值得多重試幾次
            retry_sheets_write(_do_write, retries=3, base_wait=8, label="融資融券回填寫入")
            log.info(f"融資融券回填完成：{updated}/{len(df)} 檔已更新（資料日期：{trade_date}）")
        except Exception as e:
            log.error(f"融資融券回填寫入失敗（已重試仍失敗）：「{SHEET_MULTI}」可能已被清空但寫入未完成，請檢查Sheets: {e}")
            return 0

    return updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    trade_date = get_trade_date()
    log.info(f"=== 測試融資融券抓取 ({trade_date}) ===")

    test_stocks = ["2330", "2454", "2383", "6223", "2308"]
    log.info(f"測試 {len(test_stocks)} 檔個股...")

    df = fetch_margin_for_stocks(test_stocks, trade_date)
    if not df.empty:
        print(df.to_string(index=False))
    else:
        log.warning("無融資融券資料（約晚上9:30後才公布）")