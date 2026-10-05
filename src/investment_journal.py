"""
investment_journal.py
投資筆記：追蹤一檔股票從「觀察中」到「持有」到「賣出」整個過程的心得記錄，
並用填寫當時股價 vs 目前股價，即時比對「預期方向」是否吻合，協助使用者練習紀律——
強迫自己在動作前先想清楚、寫下理由，之後回頭檢視自己當時的判斷準不準。

這不是嚴謹的統計回測（那是backtest_tracker.py的工作，有固定T+N天數、
最小樣本數門檻等統計要求），這裡單純是給使用者自己用的主觀學習/回顧工具，
用「現在」當比對基準即可，不需要鎖定特定天數後才能定案。

階段(階段欄位)自動依「我的持倉」目前的真實狀態判斷，不需要使用者手動選：
  - 持有中：該股目前在「我的持倉」有「持有中」的紀錄
  - 已賣出：該股在「我的持倉」曾經有紀錄，但目前都已出場
  - 追蹤中：該股從來沒有在「我的持倉」出現過（純觀察、尚未投資）
"""
import logging
import pandas as pd
from datetime import datetime
import pytz
import gspread

from retry_utils import retry_sheets_write

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_JOURNAL = "投資筆記"
JOURNAL_COLS = [
    "日期時間", "股票代號", "股票名稱", "階段", "當時股價",
    "心得內容", "預期方向", "目標價", "停損價",
]

STAGE_WATCHING = "追蹤中"   # 尚未投資，純觀察
STAGE_HOLDING = "持有中"    # 已經買進，正在持有
STAGE_SOLD = "已賣出"       # 已經賣出

DIRECTION_UP = "看漲"
DIRECTION_DOWN = "看跌"

ACCURACY_MOVE_THRESHOLD_PCT = 1.0  # 漲跌幅在這個門檻以內視為「持平」，不判定對/錯，避免小幅震盪被誤判


def _load_journal(ss) -> pd.DataFrame:
    """讀取投資筆記，不存在則回傳空表（含正確欄位結構）"""
    try:
        ws = ss.worksheet(SHEET_JOURNAL)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame(columns=JOURNAL_COLS)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in JOURNAL_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=JOURNAL_COLS)
    except Exception as e:
        log.warning(f"讀取投資筆記失敗: {e}")
        return pd.DataFrame(columns=JOURNAL_COLS)


def determine_stage(ss, code: str) -> str:
    """
    依「我的持倉」目前的真實紀錄，判斷這檔股票現在該歸類成哪個階段。
    沿用position_manager.py既有的get_position_status()，不在這裡重複讀一次Sheet。
    """
    from position_manager import get_position_status, STATUS_OPEN

    status = get_position_status(ss, code)
    if status == STATUS_OPEN:
        return STAGE_HOLDING
    elif status is not None:
        return STAGE_SOLD
    return STAGE_WATCHING


def add_journal_entry(ss, code: str, name: str, current_price, content: str,
                       direction: str = "", target_price=None, stop_price=None) -> bool:
    """
    新增一筆投資筆記。階段由determine_stage()自動判斷，不是使用者手動選的，
    確保「階段」永遠反映真實持倉狀態，不會因為使用者選錯而失真。

    用append_row直接加一列（不整表覆寫）——筆記是逐筆累積的個人紀錄，
    不像「我的持倉」需要頻繁整表更新同一列，用append效率更好也更安全，
    不會有clear()之後寫入中斷導致舊筆記遺失的風險。

    direction: DIRECTION_UP/DIRECTION_DOWN其中之一，或留空""代表純記錄心得、
               不做方向預測（這種筆記之後在準確度比對會被標記「未填預期方向」，
               不計入命中率統計，不是錯誤)
    """
    stage = determine_stage(ss, code)

    def _do_append():
        existing = [ws.title for ws in ss.worksheets()]
        if SHEET_JOURNAL not in existing:
            ws = ss.add_worksheet(title=SHEET_JOURNAL, rows=1000, cols=len(JOURNAL_COLS) + 2)
            ws.append_row(JOURNAL_COLS)
        else:
            ws = ss.worksheet(SHEET_JOURNAL)
            if not ws.row_values(1):
                ws.append_row(JOURNAL_COLS)
        row = [
            datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M"),
            str(code), name, stage,
            current_price if current_price is not None else "",
            content, direction,
            target_price if target_price is not None else "",
            stop_price if stop_price is not None else "",
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")

    try:
        retry_sheets_write(_do_append, retries=2, base_wait=5, label="投資筆記新增")
        log.info(f"投資筆記新增：{code} {name}（{stage}）")
        return True
    except Exception as e:
        log.warning(f"投資筆記新增失敗: {e}")
        return False


def delete_journal_entry(ss, row_index: int) -> bool:
    """
    刪除一筆投資筆記（例如打錯字、測試資料）
    row_index: 對應_load_journal()/evaluate_journal_accuracy()回傳DataFrame的index（0-based，不含表頭）
    """
    def _do_delete():
        ws = ss.worksheet(SHEET_JOURNAL)
        ws.delete_rows(row_index + 2)  # +1表頭 +1轉成1-based列號

    try:
        retry_sheets_write(_do_delete, retries=2, base_wait=5, label="投資筆記刪除")
        return True
    except Exception as e:
        log.warning(f"投資筆記刪除失敗: {e}")
        return False


def get_journal_by_code(ss, code: str) -> pd.DataFrame:
    """取得某股票的歷史筆記，依時間排序（最新在最前面，方便UI直接顯示最近心得）"""
    df = _load_journal(ss)
    if df.empty:
        return df
    sub = df[df["股票代號"] == str(code)].copy()
    return sub.sort_values("日期時間", ascending=False)


def get_tracked_codes(ss, stage: str = None) -> list:
    """
    取得目前投資筆記裡出現過的所有股票代號+名稱（不重複）。

    stage: 若指定，只回傳「目前」（即時用determine_stage()依我的持倉判斷，
           不是看筆記當時存的「階段」欄位）符合這個階段的股票——因為股票可能
           先被追蹤、之後才買進，筆記歷史會留著「追蹤中」時期寫的舊紀錄，但這
           支股票現在可能已經變成「持有中」，這裡要反映「現在」的真實狀態，
           不能照搬筆記當時寫的標籤，否則已經買進的股票會一直留在追蹤清單裡。

    用來讓UI畫出「追蹤中」分頁的股票清單——「追蹤中」股票本來就沒有持倉紀錄，
    投資筆記本身就是這份觀察清單的唯一來源，不需要另外維護一份獨立的自選股清單。
    回傳：[(股票代號, 股票名稱), ...]，依最近一次筆記時間新到舊排序
    """
    df = _load_journal(ss)
    if df.empty:
        return []
    df = df.sort_values("日期時間", ascending=False)
    seen = []
    seen_codes = set()
    for _, row in df.iterrows():
        code = row["股票代號"]
        if code in seen_codes:
            continue
        seen_codes.add(code)
        if stage and determine_stage(ss, code) != stage:
            continue
        seen.append((code, row["股票名稱"]))
    return seen


def evaluate_journal_accuracy(ss, latest_cross_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    對每一筆有填「預期方向」的筆記，即時比對「填寫當時股價」vs「目前股價」，
    判定方向是否吻合，附加「目前股價」「漲跌%」「判定」三個欄位回傳。

    latest_cross_df: 最新的多方驗證名單（優先用，有收盤價可以直接查，避免重複呼叫API）；
                      查不到的股票代號（例如自選股/追蹤中股票）改用
                      price_fetcher.get_stock_price_single()即時抓，
                      跟position_manager.evaluate_open_positions()的備援邏輯一致
    """
    df = _load_journal(ss)
    if df.empty:
        return df

    latest_by_code = {}
    if latest_cross_df is not None and not latest_cross_df.empty and "股票代號" in latest_cross_df.columns:
        for _, r in latest_cross_df.iterrows():
            latest_by_code[str(r["股票代號"])] = pd.to_numeric(r.get("收盤價"), errors="coerce")

    price_cache = {}

    def _current_price(code):
        code = str(code)
        if code in price_cache:
            return price_cache[code]
        price = latest_by_code.get(code)
        if price is None or pd.isna(price):
            try:
                from price_fetcher import get_stock_price_single
                live = get_stock_price_single(code)
                price = live.get("收盤價") if live else None
            except Exception as e:
                log.warning(f"投資筆記準確度比對：{code} 即時股價抓取失敗: {e}")
                price = None
        price_cache[code] = price
        return price

    current_prices, change_pcts, verdicts = [], [], []

    for _, row in df.iterrows():
        code = row["股票代號"]
        direction = row.get("預期方向", "")
        entry_price = pd.to_numeric(row.get("當時股價"), errors="coerce")
        now_price = _current_price(code)
        now_price = pd.to_numeric(now_price, errors="coerce") if now_price is not None else None

        current_prices.append(now_price if now_price is not None and not pd.isna(now_price) else "")

        if now_price is None or pd.isna(now_price) or pd.isna(entry_price) or not entry_price:
            change_pcts.append("")
            verdicts.append("－（資料不足）")
            continue

        change_pct = round((now_price - entry_price) / entry_price * 100, 2)
        change_pcts.append(change_pct)

        if direction not in (DIRECTION_UP, DIRECTION_DOWN):
            verdicts.append("－（未填預期方向）")
        elif abs(change_pct) < ACCURACY_MOVE_THRESHOLD_PCT:
            verdicts.append("➖ 持平（尚不明顯）")
        elif (direction == DIRECTION_UP and change_pct > 0) or (direction == DIRECTION_DOWN and change_pct < 0):
            verdicts.append("✅ 判斷吻合")
        else:
            verdicts.append("❌ 判斷不符")

    df["目前股價"] = current_prices
    df["漲跌%"] = change_pcts
    df["判定"] = verdicts
    return df


def get_accuracy_summary(evaluated_df: pd.DataFrame) -> pd.DataFrame:
    """
    依「階段」分組統計命中率（✅數 / (✅+❌)數，排除持平跟未填方向的筆記）。

    分階段看的原因：「追蹤中」命中率代表「看對趨勢、敢不敢在對的時間點進場」的練習成果；
    「持有中」命中率代表「持倉時的判斷有沒有被情緒干擾、誤判訊號」——這是兩種不同性質的
    紀律練習，混在一起看會失去「我到底是進場判斷不準，還是抱股時容易自己嚇自己」這種
    具體的自我檢視價值。
    """
    if evaluated_df is None or evaluated_df.empty or "判定" not in evaluated_df.columns:
        return pd.DataFrame()

    records = []
    for stage in [STAGE_WATCHING, STAGE_HOLDING, STAGE_SOLD]:
        sub = evaluated_df[evaluated_df["階段"] == stage]
        if sub.empty:
            continue
        hit = (sub["判定"] == "✅ 判斷吻合").sum()
        miss = (sub["判定"] == "❌ 判斷不符").sum()
        total_judged = hit + miss
        records.append({
            "階段": stage,
            "筆記總數": len(sub),
            "已有明確結果": int(total_judged),
            "命中率%": round(hit / total_judged * 100, 1) if total_judged > 0 else None,
        })
    return pd.DataFrame(records)
