"""
position_manager.py
持倉監控與進出場訊號規則

設計背景：
  - 使用者資金有限，同時只操作1-3檔零股，屬於「積極輪動、追求每月都有收入」的策略
  - 這不是自動交易系統，是「決策輔助」：使用者手動記錄自己的進場，
    系統每天比對最新資料，用規則判斷是否該出場，在Streamlit顯示提醒
  - 出場採「四重條件，先觸發先出」：停損 / 停利 / 訊號轉弱 / 技術面提早轉弱，任一觸發就建議出場
  - 支援「自選股」（不在ETF追蹤範圍內的股票）：找不到ETF/法人資料時，
    改用即時抓股價/技術指標當備援，仍可追蹤出場條件（只是少了法人/ETF相關的判斷依據）
  - 同一檔股票分批買進會自動合併成加權平均價格與加總股數，不會產生重複的持倉紀錄

進場規則（給候選名單參考，非強制，僅適用ETF追蹤範圍內的股票）：
  - 綜合評分 >= ENTRY_MIN_SCORE
  - 買超轉換率% >= ENTRY_MIN_CONVERSION（法人方向要夠一致）
  - 候選過多時，取評分最高的前 MAX_POSITIONS 檔

出場規則（四重條件）：
  1. 停損：報酬率 <= -停損%（每次進場可自訂，預設 DEFAULT_STOP_LOSS_PCT，
              也可依 ATR 動態計算建議值，見 suggest_stop_loss_from_atr()）
  2. 停利：報酬率 >= +停利%（每次進場可自訂，預設 DEFAULT_TAKE_PROFIT_PCT）
  3. 訊號轉弱：評分較進場時下降超過 SIGNAL_WEAKEN_SCORE_DROP，
              或法人由買轉賣（三大合計轉負），
              或買超轉換率%跌破 SIGNAL_WEAKEN_CONVERSION_FLOOR
              （僅ETF追蹤範圍內股票適用，自選股沒有這些資料，此類條件會略過）
  4. 技術面提早轉弱：KD/MACD醞釀死亡交叉、或出現頂部背離、或KD/MACD已經死亡交叉
              （這組刻意設計成「提早」偵測，不等實際死叉發生才動作，見price_fetcher.py；
              自選股也適用，因為技術指標是即時抓取，不依賴ETF追蹤範圍）
"""
import logging
import time
import pandas as pd
from datetime import datetime
import pytz
import gspread

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_POSITIONS = "我的持倉"
POSITION_COLS = [
    "股票代號", "股票名稱", "進場日期", "最後加碼日期", "進場價", "累計股數",
    "進場評分", "進場法人訊號", "進場買超轉換率%", "資料來源",
    "自訂停損%", "自訂停利%", "狀態", "出場日期", "出場價", "出場原因", "最後檢查日期",
]

DATA_SOURCE_ETF = "ETF追蹤"
DATA_SOURCE_ADHOC = "自選股(即時查詢)"

# ── 進場規則預設參數（可依回測資料校正）──────────────────────
MAX_POSITIONS = 3
ENTRY_MIN_SCORE = 7.0
ENTRY_MIN_CONVERSION = 60.0
ENTRY_MAX_PRICE = 1000.0  # 資金有限，優先篩選股價1000元以下的標的（零股操作，股價太高單股成本負擔重）

# ── 出場規則預設參數 ──────────────────────────────────────
DEFAULT_STOP_LOSS_PCT = 10.0     # 預設停損 -10%（使用者可在新增持倉時自訂到8~20%）
DEFAULT_TAKE_PROFIT_PCT = 25.0   # 預設停利 +25%（未來可用回測「T20內平均最大報酬%」校正）
SIGNAL_WEAKEN_SCORE_DROP = 2.0   # 評分較進場時下降超過此值 → 判定訊號轉弱
SIGNAL_WEAKEN_CONVERSION_FLOOR = 40.0  # 買超轉換率%跌破此值 → 判定法人開始分歧

# 技術面提早轉弱訊號（來自price_fetcher.py的KD訊號/MACD訊號/背離警示欄位）
TECH_WEAKEN_KD_SIGNALS = {"🔴 死亡交叉", "🍂 醞釀死亡交叉"}
TECH_WEAKEN_MACD_SIGNALS = {"🔴 死亡交叉", "🍂 多方動能趨緩"}

# ATR動態停損：停損% = ATR% × 倍數，波動大的股票給寬一點停損、波動小的給緊一點，
# 比固定10%一刀切更合理；夾在[ATR_STOP_MIN, ATR_STOP_MAX]之間避免極端值
ATR_STOP_MULTIPLIER = 2.0
ATR_STOP_MIN = 5.0
ATR_STOP_MAX = 25.0


def suggest_stop_loss_from_atr(atr_pct) -> float:
    """
    依ATR%計算建議停損百分比：ATR% × 倍數，夾在合理範圍內
    atr_pct: 該股的ATR佔股價比例（來自price_fetcher.py的「ATR%」欄位）
    找不到ATR資料時回傳預設值 DEFAULT_STOP_LOSS_PCT
    """
    if atr_pct is None or pd.isna(atr_pct) or atr_pct <= 0:
        return DEFAULT_STOP_LOSS_PCT
    suggested = float(atr_pct) * ATR_STOP_MULTIPLIER
    return round(min(max(suggested, ATR_STOP_MIN), ATR_STOP_MAX), 1)

STATUS_OPEN = "持有中"
STATUS_CLOSED = "已出場"


def _with_retry(func, retries: int = 3, base_delay: float = 2.0):
    """
    Google Sheets API 429（頻率限制）重試包裝器
    遇到429時等待後自動重試，避免直接讓整個頁面crash
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            last_error = e
            is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "Quota exceeded" in str(e)
            if is_rate_limit and attempt < retries:
                wait = base_delay * (attempt + 1)
                log.warning(f"Google Sheets API頻率限制，{wait}秒後重試（第{attempt+1}次）: {e}")
                time.sleep(wait)
                continue
            raise
    raise last_error


def _load_positions(ss) -> pd.DataFrame:
    """讀取持倉紀錄，不存在則回傳空表"""
    try:
        ws = _with_retry(lambda: ss.worksheet(SHEET_POSITIONS))
        vals = _with_retry(lambda: ws.get_all_values())
        if len(vals) < 2:
            return pd.DataFrame(columns=POSITION_COLS)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in POSITION_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=POSITION_COLS)
    except Exception as e:
        log.warning(f"讀取持倉紀錄失敗: {e}")
        return pd.DataFrame(columns=POSITION_COLS)


def _write_positions(ss, df: pd.DataFrame):
    """整表覆寫回Sheets"""
    def _do_write():
        existing = [ws.title for ws in ss.worksheets()]
        if SHEET_POSITIONS not in existing:
            ws = ss.add_worksheet(title=SHEET_POSITIONS, rows=500, cols=15)
        else:
            ws = ss.worksheet(SHEET_POSITIONS)
        ws.clear()
        ws.append_row(df.columns.tolist())
        if not df.empty:
            ws.append_rows(df.fillna("").values.tolist(), value_input_option="USER_ENTERED")

    try:
        _with_retry(_do_write)
    except Exception as e:
        log.warning(f"寫入持倉紀錄失敗: {e}")


def add_position(ss, code: str, name: str, entry_date: str, entry_price: float, shares: float,
                  entry_score, entry_signal: str, entry_conversion,
                  stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
                  take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT,
                  data_source: str = DATA_SOURCE_ETF) -> str:
    """
    新增一筆持倉紀錄（使用者實際買進時手動呼叫/在Streamlit表單填寫）
    shares: 這次買進的股數
    自動合併規則：如果同一檔股票代號已經有「持有中」的紀錄，不會新增一列，
    而是把新買進的股數併入既有紀錄，用加權平均重新計算進場價，
    避免同一檔股票分批買進卻在畫面上變成好幾筆各自獨立的持倉

    回傳："新增" 或 "合併"，方便呼叫端顯示對應訊息
    """
    df = _load_positions(ss)

    existing_open = pd.DataFrame()
    if not df.empty:
        existing_open = df[(df["股票代號"] == str(code)) & (df["狀態"] == STATUS_OPEN)]

    if not existing_open.empty:
        idx = existing_open.index[0]
        old_shares = float(df.at[idx, "累計股數"] or 0)
        old_price = float(df.at[idx, "進場價"] or 0)
        new_total_shares = old_shares + shares
        new_avg_price = (
            (old_shares * old_price + shares * entry_price) / new_total_shares
            if new_total_shares > 0 else entry_price
        )
        df.at[idx, "累計股數"] = new_total_shares
        df.at[idx, "進場價"] = round(new_avg_price, 2)
        df.at[idx, "最後加碼日期"] = entry_date
        # 評分/法人訊號用最新一次加碼時的資料更新，反映目前狀態
        if entry_score is not None:
            df.at[idx, "進場評分"] = entry_score
        if entry_signal:
            df.at[idx, "進場法人訊號"] = entry_signal
        if entry_conversion is not None:
            df.at[idx, "進場買超轉換率%"] = entry_conversion
        _write_positions(ss, df)
        log.info(f"持倉合併：{code} 加碼{shares}股，加權平均價更新為{round(new_avg_price,2)}"
                  f"（原{old_shares}股@{old_price} + 新{shares}股@{entry_price}）")
        return "合併"

    new_row = {
        "股票代號": str(code),
        "股票名稱": name,
        "進場日期": entry_date,
        "最後加碼日期": entry_date,
        "進場價": entry_price,
        "累計股數": shares,
        "進場評分": entry_score if entry_score is not None else "",
        "進場法人訊號": entry_signal,
        "進場買超轉換率%": entry_conversion if entry_conversion is not None else "",
        "資料來源": data_source,
        "自訂停損%": stop_loss_pct,
        "自訂停利%": take_profit_pct,
        "狀態": STATUS_OPEN,
        "出場日期": "",
        "出場價": "",
        "出場原因": "",
        "最後檢查日期": entry_date,
    }
    combined = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True) if not df.empty else pd.DataFrame([new_row])
    _write_positions(ss, combined)
    log.info(f"新增持倉：{code} {name} {shares}股 進場價{entry_price}，停損{stop_loss_pct}%/停利{take_profit_pct}%（{data_source}）")
    return "新增"


def close_position(ss, row_index: int, exit_date: str, exit_price: float, exit_reason: str):
    """手動關閉一筆持倉（使用者實際賣出時呼叫，會保留歷史紀錄，狀態改為已出場）"""
    df = _load_positions(ss)
    if row_index >= len(df):
        return False
    df.at[row_index, "狀態"] = STATUS_CLOSED
    df.at[row_index, "出場日期"] = exit_date
    df.at[row_index, "出場價"] = exit_price
    df.at[row_index, "出場原因"] = exit_reason
    _write_positions(ss, df)
    return True


def delete_position(ss, row_index: int) -> bool:
    """
    完全刪除一筆持倉紀錄（不留痕跡）
    跟 close_position 不同：close_position是「正常賣出」，會保留歷史供之後統計勝率；
    delete_position是「這筆紀錄本身是錯的」（例如測試資料、輸入錯誤），直接移除，不計入任何統計
    """
    df = _load_positions(ss)
    if row_index >= len(df):
        return False
    df = df.drop(index=row_index).reset_index(drop=True)
    _write_positions(ss, df)
    return True


def update_position(ss, row_index: int, **fields) -> bool:
    """
    修改一筆持倉紀錄的欄位（例如訂正輸入錯誤的進場價/股數/停損停利%）
    fields: 要更新的欄位=新值，例如 update_position(ss, 0, 進場價=150.5, 累計股數=1000)
    """
    df = _load_positions(ss)
    if row_index >= len(df):
        return False
    for key, val in fields.items():
        if key in df.columns:
            df.at[row_index, key] = val
    _write_positions(ss, df)
    return True


def evaluate_open_positions(ss, latest_cross_df: pd.DataFrame) -> pd.DataFrame:
    """
    每天比對最新資料，評估所有「持有中」的部位是否觸發出場條件
    latest_cross_df: 最新的多方驗證名單（含股票代號、收盤價、綜合評分、三大合計、買超轉換率%）

    自選股（不在latest_cross_df裡的股票）備援機制：
      改用 price_fetcher.get_stock_price_single() 即時抓股價/技術指標，
      這樣即使不是ETF追蹤範圍內的股票，也能持續追蹤停損/停利/技術面轉弱這幾類條件
      （法人相關的③訊號轉弱條件因為沒有資料，會自動略過，不會誤判）

    回傳：每筆持倉的評估結果（含是否建議出場、觸發原因、目前報酬率，以及完整參考資訊供畫面顯示）
    """
    df = _load_positions(ss)
    if df.empty:
        return pd.DataFrame()

    open_positions = df[df["狀態"] == STATUS_OPEN].copy()
    if open_positions.empty:
        return pd.DataFrame()

    today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")

    latest_by_code = {}
    if not latest_cross_df.empty and "股票代號" in latest_cross_df.columns:
        for _, r in latest_cross_df.iterrows():
            latest_by_code[str(r["股票代號"])] = r

    results = []
    for idx, pos in open_positions.iterrows():
        code = pos["股票代號"]
        entry_price = float(pos["進場價"]) if pos["進場價"] else None
        entry_score = float(pos["進場評分"]) if pos["進場評分"] not in ("", None) else None
        shares = float(pos.get("累計股數") or 0)
        stop_loss_pct = float(pos["自訂停損%"]) if pos["自訂停損%"] else DEFAULT_STOP_LOSS_PCT
        take_profit_pct = float(pos["自訂停利%"]) if pos["自訂停利%"] else DEFAULT_TAKE_PROFIT_PCT

        latest = latest_by_code.get(code)
        used_fallback = False

        # 自選股備援：ETF追蹤範圍內找不到，改即時抓股價/技術指標
        if latest is None:
            try:
                from price_fetcher import get_stock_price_single
                live = get_stock_price_single(code)
                if live:
                    latest = pd.Series(live)
                    used_fallback = True
            except Exception as e:
                log.warning(f"{code} 即時股價備援抓取失敗: {e}")

        result = {
            "row_index": idx,
            "股票代號": code,
            "股票名稱": pos["股票名稱"],
            "進場日期": pos["進場日期"],
            "進場價": entry_price,
            "累計股數": shares,
            "建議出場": False,
            "觸發原因": [],
            "目前報酬率%": None,
            "目前評分": None,
            "目前收盤價": None,
            "損益金額": None,
            "資料來源": "即時查詢備援" if used_fallback else "ETF追蹤資料",
            "法人訊號": None,
            "KD訊號": None,
            "MACD訊號": None,
            "技術面共振": None,
        }

        if latest is None or entry_price is None:
            result["觸發原因"].append("⚠️ 找不到今日最新資料（TWSE查無此代號，或今日尚無交易，建議人工確認）")
            results.append(result)
            continue

        current_price = pd.to_numeric(latest.get("收盤價"), errors="coerce")
        current_score = pd.to_numeric(latest.get("綜合評分"), errors="coerce")
        current_total = pd.to_numeric(latest.get("三大合計"), errors="coerce")
        current_conversion = pd.to_numeric(latest.get("買超轉換率%"), errors="coerce")

        result["法人訊號"] = latest.get("法人訊號")
        result["KD訊號"] = latest.get("KD訊號")
        result["MACD訊號"] = latest.get("MACD訊號")
        result["技術面共振"] = latest.get("技術面共振")

        if pd.notna(current_price) and entry_price:
            ret_pct = round((current_price - entry_price) / entry_price * 100, 2)
            result["目前報酬率%"] = ret_pct
            result["目前收盤價"] = current_price
            if shares:
                result["損益金額"] = round((current_price - entry_price) * shares, 0)

            # ① 停損
            if ret_pct <= -stop_loss_pct:
                result["建議出場"] = True
                result["觸發原因"].append(f"🔴 觸及停損（報酬{ret_pct}% <= -{stop_loss_pct}%）")

            # ② 停利
            if ret_pct >= take_profit_pct:
                result["建議出場"] = True
                result["觸發原因"].append(f"🟢 觸及停利（報酬{ret_pct}% >= +{take_profit_pct}%）")

        if pd.notna(current_score):
            result["目前評分"] = current_score
            # ③ 訊號轉弱：評分下降
            if entry_score is not None and (entry_score - current_score) >= SIGNAL_WEAKEN_SCORE_DROP:
                result["建議出場"] = True
                result["觸發原因"].append(f"🟡 評分轉弱（{entry_score}分→{current_score}分）")

        # ③ 訊號轉弱：法人由買轉賣（自選股沒有法人資料，current_total是NaN，自動略過不誤判）
        if pd.notna(current_total) and current_total < 0:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟡 法人轉為淨賣超（三大合計{current_total}張）")

        # ③ 訊號轉弱：買超轉換率大幅下滑
        if pd.notna(current_conversion) and current_conversion < SIGNAL_WEAKEN_CONVERSION_FLOOR:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟡 法人方向分歧（買超轉換率{current_conversion}% < {SIGNAL_WEAKEN_CONVERSION_FLOOR}%）")

        # ④ 技術面提早轉弱：KD/MACD醞釀或已死亡交叉、頂部背離（不等確認訊號完全成形，提早示警）
        current_kd_signal = str(latest.get("KD訊號", "")) if latest is not None else ""
        current_macd_signal = str(latest.get("MACD訊號", "")) if latest is not None else ""
        current_divergence = str(latest.get("背離警示", "")) if latest is not None else ""

        if current_kd_signal in TECH_WEAKEN_KD_SIGNALS:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟠 技術面轉弱（KD：{current_kd_signal}）")

        if current_macd_signal in TECH_WEAKEN_MACD_SIGNALS:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟠 技術面轉弱（MACD：{current_macd_signal}）")

        if current_divergence:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟠 {current_divergence}")

        results.append(result)

        # 更新最後檢查日期
        df.at[idx, "最後檢查日期"] = today_str

    _write_positions(ss, df)  # 寫回最後檢查日期
    return pd.DataFrame(results)


def get_entry_candidates(latest_cross_df: pd.DataFrame, max_positions: int = MAX_POSITIONS,
                          max_price: float = ENTRY_MAX_PRICE) -> pd.DataFrame:
    """
    依進場規則篩選候選標的：綜合評分>=門檻 且 買超轉換率%>=門檻 且 股價<=上限，取評分最高的前N檔
    latest_cross_df: 最新的多方驗證名單
    max_price: 股價上限（資金有限時可調整，例如零股操作偏好1000元以下標的）

    另外標記「技術面提早轉強」（KD醞釀/已黃金交叉 或 MACD空方動能趨緩/已黃金交叉），
    這只是提供給你參考的加分資訊，不是硬性篩選條件（避免技術面資料缺失時，該股就整檔被排除）
    """
    if latest_cross_df.empty:
        return pd.DataFrame()

    df = latest_cross_df.copy()
    df["綜合評分"] = pd.to_numeric(df.get("綜合評分"), errors="coerce")
    df["買超轉換率%"] = pd.to_numeric(df.get("買超轉換率%"), errors="coerce")
    df["收盤價"] = pd.to_numeric(df.get("收盤價"), errors="coerce")

    candidates = df[
        (df["綜合評分"] >= ENTRY_MIN_SCORE) &
        (df["買超轉換率%"] >= ENTRY_MIN_CONVERSION) &
        (df["收盤價"] <= max_price)
    ].copy()

    if candidates.empty:
        return pd.DataFrame()

    tech_strong_kd = {"🟢 黃金交叉", "🌱 醞釀黃金交叉"}
    tech_strong_macd = {"🟢 黃金交叉", "🌱 空方動能趨緩"}

    def _tech_note(row):
        notes = []
        if str(row.get("KD訊號", "")) in tech_strong_kd:
            notes.append(f"KD:{row.get('KD訊號')}")
        if str(row.get("MACD訊號", "")) in tech_strong_macd:
            notes.append(f"MACD:{row.get('MACD訊號')}")
        return "、".join(notes)

    if "KD訊號" in candidates.columns or "MACD訊號" in candidates.columns:
        candidates["技術面提早轉強"] = candidates.apply(_tech_note, axis=1)

    candidates = candidates.sort_values("綜合評分", ascending=False).head(max_positions)
    return candidates