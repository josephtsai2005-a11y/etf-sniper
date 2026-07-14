"""
position_manager.py
持倉監控與進出場訊號規則

設計背景：
  - 使用者資金有限，同時只操作1-3檔零股，屬於「積極輪動、追求每月都有收入」的策略
  - 這不是自動交易系統，是「決策輔助」：使用者手動記錄自己的進場，
    系統每天比對最新資料，用規則判斷是否該出場，在Streamlit顯示提醒
  - 出場採「三重條件，先觸發先出」：停損 / 停利 / 訊號轉弱，任一觸發就建議出場

進場規則（給候選名單參考，非強制）：
  - 綜合評分 >= ENTRY_MIN_SCORE
  - 買超轉換率% >= ENTRY_MIN_CONVERSION（法人方向要夠一致）
  - 候選過多時，取評分最高的前 MAX_POSITIONS 檔

出場規則（三重條件）：
  1. 停損：報酬率 <= -停損%（每次進場可自訂，預設 DEFAULT_STOP_LOSS_PCT）
  2. 停利：報酬率 >= +停利%（每次進場可自訂，預設 DEFAULT_TAKE_PROFIT_PCT）
  3. 訊號轉弱：評分較進場時下降超過 SIGNAL_WEAKEN_SCORE_DROP，
              或法人由買轉賣（三大合計轉負），
              或買超轉換率%跌破 SIGNAL_WEAKEN_CONVERSION_FLOOR
"""
import logging
import pandas as pd
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_POSITIONS = "我的持倉"
POSITION_COLS = [
    "股票代號", "股票名稱", "進場日期", "進場價", "進場評分", "進場法人訊號", "進場買超轉換率%",
    "自訂停損%", "自訂停利%", "狀態", "出場日期", "出場價", "出場原因", "最後檢查日期",
]

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

STATUS_OPEN = "持有中"
STATUS_CLOSED = "已出場"


def _load_positions(ss) -> pd.DataFrame:
    """讀取持倉紀錄，不存在則回傳空表"""
    try:
        ws = ss.worksheet(SHEET_POSITIONS)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame(columns=POSITION_COLS)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in POSITION_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except Exception:
        return pd.DataFrame(columns=POSITION_COLS)


def _write_positions(ss, df: pd.DataFrame):
    """整表覆寫回Sheets"""
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_POSITIONS not in existing:
        ws = ss.add_worksheet(title=SHEET_POSITIONS, rows=500, cols=15)
    else:
        ws = ss.worksheet(SHEET_POSITIONS)
    ws.clear()
    ws.append_row(df.columns.tolist())
    if not df.empty:
        ws.append_rows(df.fillna("").values.tolist(), value_input_option="USER_ENTERED")


def add_position(ss, code: str, name: str, entry_date: str, entry_price: float,
                  entry_score: float, entry_signal: str, entry_conversion: float,
                  stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
                  take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT):
    """新增一筆持倉紀錄（使用者實際買進時手動呼叫/在Streamlit表單填寫）"""
    df = _load_positions(ss)
    new_row = {
        "股票代號": str(code),
        "股票名稱": name,
        "進場日期": entry_date,
        "進場價": entry_price,
        "進場評分": entry_score,
        "進場法人訊號": entry_signal,
        "進場買超轉換率%": entry_conversion,
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
    log.info(f"新增持倉：{code} {name} 進場價{entry_price}，停損{stop_loss_pct}%/停利{take_profit_pct}%")


def close_position(ss, row_index: int, exit_date: str, exit_price: float, exit_reason: str):
    """手動關閉一筆持倉（使用者實際賣出時呼叫）"""
    df = _load_positions(ss)
    if row_index >= len(df):
        return False
    df.at[row_index, "狀態"] = STATUS_CLOSED
    df.at[row_index, "出場日期"] = exit_date
    df.at[row_index, "出場價"] = exit_price
    df.at[row_index, "出場原因"] = exit_reason
    _write_positions(ss, df)
    return True


def evaluate_open_positions(ss, latest_cross_df: pd.DataFrame) -> pd.DataFrame:
    """
    每天比對最新資料，評估所有「持有中」的部位是否觸發出場條件
    latest_cross_df: 最新的多方驗證名單（含股票代號、收盤價、綜合評分、三大合計、買超轉換率%）
    回傳：每筆持倉的評估結果（含是否建議出場、觸發原因、目前報酬率）
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
        entry_score = float(pos["進場評分"]) if pos["進場評分"] else None
        stop_loss_pct = float(pos["自訂停損%"]) if pos["自訂停損%"] else DEFAULT_STOP_LOSS_PCT
        take_profit_pct = float(pos["自訂停利%"]) if pos["自訂停利%"] else DEFAULT_TAKE_PROFIT_PCT

        latest = latest_by_code.get(code)

        result = {
            "row_index": idx,
            "股票代號": code,
            "股票名稱": pos["股票名稱"],
            "進場日期": pos["進場日期"],
            "進場價": entry_price,
            "建議出場": False,
            "觸發原因": [],
            "目前報酬率%": None,
            "目前評分": None,
            "目前收盤價": None,
        }

        if latest is None or entry_price is None:
            result["觸發原因"].append("⚠️ 找不到今日最新資料（該股可能已跌出追蹤名單，建議人工確認）")
            results.append(result)
            continue

        current_price = pd.to_numeric(latest.get("收盤價"), errors="coerce")
        current_score = pd.to_numeric(latest.get("綜合評分"), errors="coerce")
        current_total = pd.to_numeric(latest.get("三大合計"), errors="coerce")
        current_conversion = pd.to_numeric(latest.get("買超轉換率%"), errors="coerce")

        if pd.notna(current_price) and entry_price:
            ret_pct = round((current_price - entry_price) / entry_price * 100, 2)
            result["目前報酬率%"] = ret_pct
            result["目前收盤價"] = current_price

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

        # ③ 訊號轉弱：法人由買轉賣
        if pd.notna(current_total) and current_total < 0:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟡 法人轉為淨賣超（三大合計{current_total}張）")

        # ③ 訊號轉弱：買超轉換率大幅下滑
        if pd.notna(current_conversion) and current_conversion < SIGNAL_WEAKEN_CONVERSION_FLOOR:
            result["建議出場"] = True
            result["觸發原因"].append(f"🟡 法人方向分歧（買超轉換率{current_conversion}% < {SIGNAL_WEAKEN_CONVERSION_FLOOR}%）")

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

    candidates = candidates.sort_values("綜合評分", ascending=False).head(max_positions)
    return candidates
