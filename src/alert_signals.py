"""
alert_signals.py（2026-09-14新增）
把系統裡已經有、但分散在好幾個頁面/欄位、使用者不容易主動注意到的三種籌碼訊號整理成一份
「今日訊號提醒」，供Streamlit頁面明顯標示、以及每日AI報告額外點名使用。

背景：使用者提出的問題（「主力好像都有默契，系統裡面有籌碼集中度/三大法人一致性/融資券
變化這些指標，但不太會用/觀察，可以設定觸發的提醒嗎？或是在報告/哪個頁面備註？」）——
系統其實早就算出這些指標了，只是分散在「今日訊號」「多方驗證名單」等好幾個頁面的欄位裡，
沒有一個地方主動把「今天有什麼值得注意」點出來，使用者得自己一頁一頁比對。這個模組不
發明新指標，只是把三個既有欄位的既有計算結果收斂成一份摘要：

1. 聰明錢集中度提升：沿用diff_analyzer.py::aggregate_stock_diff()已經算出、寫進
   「今日訊號」分頁的「主要狀態」欄位——「🆕 新增」或「🔺 加碼」代表比昨天有更多/新的
   主動式ETF開始持有這檔股票，這是既有的每日比對結果，這裡只是額外標示出來。
2. 融資券異常變化：沿用margin_fetcher.py::compute_margin_signal()已經用±5%門檻算出、
   寫進「多方驗證名單」的「融資訊號」欄位，內容含「大增」或「大減」文字的即為異常。
3. 籌碼矛盾出現/解除：這是唯一需要「新」比對邏輯的訊號——margin_fetcher.py::
   compute_chip_conflict()算出的「籌碼矛盾」欄位只反映「今天」的狀態，「多方驗證名單」
   分頁每天會被覆寫、沒有保留歷史，沒辦法直接看出「今天 vs 昨天」的變化。

   這裡新增一個獨立的「籌碼矛盾歷史」append-only分頁（append_chip_conflict_history()
   負責寫入）來解決這個問題，而不是沿用backtest_tracker.py既有的「回測記錄」——
   「回測記錄」是main.py在16:45（階段六）呼叫record_daily_snapshot()時記錄的，那個時間點
   融資融券資料通常還沒公布（TWSE融資融券日報約21:30才公布），「籌碼矛盾」/「融資訊號」
   在那個時間點幾乎必定是空的，等23:00真正的資料回填進「多方驗證名單」時，「回測記錄」
   當天那筆已經記過、不會再更新，沿用它會導致這裡永遠比對到空值。改成在
   backfill_margin_signals_to_multi_sheet()真正拿到當天資料「之後」（main.py的
   RUN_MODE=="ai"、23:00附近）才呼叫append_chip_conflict_history()記錄，才能保證
   比對到的是真正的值。

設計原則：detect_*/build_daily_alert_summary()這幾個「偵測」函式全部是純DataFrame輸入
輸出，不接觸Google Sheets——呼叫端（app.py／main.py）各自用自己既有的讀取方式（app.py是
`load_sheet()`的5分鐘快取、main.py是AI job當下的即時讀取）把資料準備好再傳進來，
只有真的需要「寫入」的append_chip_conflict_history()才需要一個真正的gspread
Spreadsheet物件——這樣分工讓偵測邏輯可以脫離Streamlit/gspread直接單元測試，也讓app.py
不需要為了這個功能額外多打一次即時的Google Sheets API（重用既有的load_sheet()快取，
避免重蹈2026-09-11「母題材審核」429頻率限制crash的覆轍）。
"""
import logging
import pandas as pd

log = logging.getLogger(__name__)

SHEET_CHIP_HISTORY = "籌碼矛盾歷史"


def detect_concentration_up(diff_df: pd.DataFrame) -> pd.DataFrame:
    """聰明錢集中度提升：見模組docstring第1點。回傳「今日訊號」分頁裡狀態為
    「🆕 新增」或「🔺 加碼」的列，欄位維持原樣不重新計算。"""
    if diff_df is None or diff_df.empty or "主要狀態" not in diff_df.columns:
        return pd.DataFrame()
    return diff_df[diff_df["主要狀態"].isin(["🆕 新增", "🔺 加碼"])].copy()


def detect_margin_abnormal(multi_df: pd.DataFrame) -> pd.DataFrame:
    """融資券異常變化：見模組docstring第2點。回傳「多方驗證名單」裡「融資訊號」
    含「大增」或「大減」的列（沿用既有±5%門檻，不另外發明新門檻）。"""
    if multi_df is None or multi_df.empty or "融資訊號" not in multi_df.columns:
        return pd.DataFrame()
    return multi_df[multi_df["融資訊號"].astype(str).str.contains("大增|大減", na=False)].copy()


def detect_chip_conflict_transitions(multi_df: pd.DataFrame, history_df: pd.DataFrame,
                                      today_date_str: str = None) -> pd.DataFrame:
    """
    籌碼矛盾出現/解除：見模組docstring第3點。

    比對「今天」（multi_df，呼叫端當下拿到的「多方驗證名單」）vs 「上一個交易日」
    （history_df，累積的「籌碼矛盾歷史」分頁）的「籌碼矛盾」欄位，找出「新出現」或
    「剛解除」的股票。

    today_date_str：目前的交易日（YYYYMMDD）。如果「籌碼矛盾歷史」分頁裡已經有這個日期的
    記錄（代表今天23:00的AI job已經跑過、append_chip_conflict_history()已經把今天的值
    寫進去了），需要先排除掉這筆，才能真正拿到「上一個交易日」，否則會誤把「今天」的記錄
    當成比較基準，變成「今天 vs 今天」，永遠比對不出任何變化。不傳這個參數時，直接取
    history_df裡最新的日期當基準（假設呼叫端知道歷史分頁還沒有寫入今天的資料，例如
    main.py在呼叫append_chip_conflict_history()「之前」呼叫這個函式的情境）。

    回傳欄位：股票代號、股票名稱、變化、昨日籌碼矛盾、今日籌碼矛盾。「變化」為
    「🆕 矛盾出現」或「✅ 矛盾解除」。冷啟動（歷史分頁還沒有任何記錄，或這檔股票在
    上一個交易日沒有記錄）時該股票不會出現在結果裡——不是判斷錯誤，只是還沒有基準可以比較。
    """
    if multi_df is None or multi_df.empty or "籌碼矛盾" not in multi_df.columns:
        return pd.DataFrame()
    if history_df is None or history_df.empty or "日期" not in history_df.columns:
        return pd.DataFrame()
    if "股票代號" not in history_df.columns:
        return pd.DataFrame()

    dates = sorted(history_df["日期"].dropna().unique().tolist())
    if today_date_str and today_date_str in dates:
        dates = [d for d in dates if d != today_date_str]
    if not dates:
        return pd.DataFrame()
    prior_date = dates[-1]

    prior_slice = history_df[history_df["日期"] == prior_date]
    prior_conflict = dict(zip(
        prior_slice["股票代號"].astype(str).str.strip(),
        prior_slice.get("籌碼矛盾", pd.Series(dtype=str)).astype(str).str.strip(),
    ))

    records = []
    for _, row in multi_df.iterrows():
        code = str(row.get("股票代號", "")).strip()
        if not code or code not in prior_conflict:
            continue  # 冷啟動：這檔股票在上一個交易日沒有記錄，無法比較
        today_val = str(row.get("籌碼矛盾", "")).strip()
        prior_val = prior_conflict.get(code, "")
        if not prior_val and today_val:
            records.append({"股票代號": code, "股票名稱": row.get("股票名稱", ""),
                             "變化": "🆕 矛盾出現", "昨日籌碼矛盾": prior_val, "今日籌碼矛盾": today_val})
        elif prior_val and not today_val:
            records.append({"股票代號": code, "股票名稱": row.get("股票名稱", ""),
                             "變化": "✅ 矛盾解除", "昨日籌碼矛盾": prior_val, "今日籌碼矛盾": today_val})

    return pd.DataFrame(records)


def build_daily_alert_summary(multi_df: pd.DataFrame, diff_df: pd.DataFrame,
                               history_df: pd.DataFrame, today_date_str: str = None) -> dict:
    """
    整合三種訊號，回傳供Streamlit頁面/AI報告共用的摘要dict：
        {"concentration_up": df, "margin_abnormal": df, "chip_conflict_change": df}
    任一項無資料時對應值是空DataFrame，呼叫端可以直接用.empty判斷要不要顯示，
    不需要另外判斷None。
    """
    return {
        "concentration_up": detect_concentration_up(diff_df),
        "margin_abnormal": detect_margin_abnormal(multi_df),
        "chip_conflict_change": detect_chip_conflict_transitions(multi_df, history_df, today_date_str),
    }


def format_alert_summary_for_ai(summary: dict) -> str:
    """
    把build_daily_alert_summary()的結果轉成一段純文字摘要，供AI報告prompt直接引用。
    這段本身不呼叫AI、不花任何API成本，純粹是資料格式化，比照
    ai_analyzer.py::build_affordable_picks_section()的做法（同樣是零額外成本的資料篩選
    段落，不是額外呼叫一次Claude去生成)。三項皆無資料時回傳空字串，呼叫端可以據此判斷
    要不要在報告裡加這個段落。
    """
    lines = []

    up = summary.get("concentration_up", pd.DataFrame())
    if not up.empty:
        lines.append(f"【聰明錢集中度提升】共{len(up)}檔（比前一交易日有更多/新的主動式ETF開始持有）：")
        for _, r in up.head(10).iterrows():
            lines.append(f"- {r.get('股票代號','')} {r.get('股票名稱','')}：{r.get('主要狀態','')}"
                          f"（新增{r.get('新增ETF數','0')}檔／加碼{r.get('加碼ETF數','0')}檔）")

    margin = summary.get("margin_abnormal", pd.DataFrame())
    if not margin.empty:
        lines.append(f"\n【融資券異常變化】共{len(margin)}檔（單日融資增減幅度達±5%門檻）：")
        for _, r in margin.head(10).iterrows():
            lines.append(f"- {r.get('股票代號','')} {r.get('股票名稱','')}：{r.get('融資訊號','')}")

    conflict = summary.get("chip_conflict_change", pd.DataFrame())
    if not conflict.empty:
        lines.append(f"\n【籌碼矛盾出現/解除】共{len(conflict)}檔：")
        for _, r in conflict.head(10).iterrows():
            today_conflict = r.get("今日籌碼矛盾", "") or "（無）"
            lines.append(f"- {r.get('股票代號','')} {r.get('股票名稱','')}：{r.get('變化','')}（今日：{today_conflict}）")

    return "\n".join(lines) if lines else ""


def append_chip_conflict_history(ss, multi_df: pd.DataFrame, trade_date: str) -> int:
    """
    把今天每檔股票的「籌碼矛盾」「融資訊號」存成一筆歷史記錄（append-only，不會被覆寫），
    供之後detect_chip_conflict_transitions()比對「今天 vs 上一個交易日」用。

    呼叫時機：務必在backfill_margin_signals_to_multi_sheet()真正拿到當天融資融券資料
    「之後」呼叫（main.py的RUN_MODE=="ai"、23:00附近），且務必在同一次執行裡「先」呼叫
    detect_chip_conflict_transitions()做完比對「之後」才呼叫這個函式——順序顛倒的話，
    今天的記錄會提早出現在歷史分頁裡，讓比對邏輯誤把「今天」當成「上一個交易日」。

    冪等處理：同一天可能因為TWSE延遲多次重跑AI job/backfill，這裡採「當天已經記錄過就
    跳過」（不覆蓋更新）——融資融券資料一旦公布不會再變動，第一次成功記錄到的就是當天
    最終值，不需要每次重跑都覆寫，跟backtest_tracker.py::record_daily_snapshot()的
    去重邏輯一致。

    回傳：實際新增的筆數（0代表今天已經記錄過、或沒有可記錄的資料，皆為正常情況不是錯誤）。
    """
    from retry_utils import retry_sheets_write

    if multi_df is None or multi_df.empty:
        return 0
    if not {"股票代號", "籌碼矛盾"}.issubset(multi_df.columns):
        return 0

    try:
        existing_sheets = [w.title for w in ss.worksheets()]
        if SHEET_CHIP_HISTORY not in existing_sheets:
            ws = ss.add_worksheet(title=SHEET_CHIP_HISTORY, rows=2000, cols=6)
            ws.append_row(["日期", "股票代號", "股票名稱", "籌碼矛盾", "融資訊號"])
        else:
            ws = ss.worksheet(SHEET_CHIP_HISTORY)
    except Exception as e:
        log.warning(f"開啟「{SHEET_CHIP_HISTORY}」分頁失敗，跳過本次記錄: {e}")
        return 0

    try:
        existing_vals = ws.get_all_values()
    except Exception as e:
        log.warning(f"讀取「{SHEET_CHIP_HISTORY}」分頁失敗，跳過本次記錄: {e}")
        return 0

    if len(existing_vals) >= 2:
        header = existing_vals[0]
        if "日期" in header:
            date_idx = header.index("日期")
            existing_dates = {row[date_idx] for row in existing_vals[1:] if len(row) > date_idx}
            if trade_date in existing_dates:
                log.info(f"「{SHEET_CHIP_HISTORY}」{trade_date} 已記錄過，跳過重複寫入")
                return 0

    rows = []
    for _, row in multi_df.iterrows():
        code = str(row.get("股票代號", "")).strip()
        if not code:
            continue
        rows.append([
            trade_date, code, row.get("股票名稱", ""),
            str(row.get("籌碼矛盾", "")).strip(), str(row.get("融資訊號", "")).strip(),
        ])

    if not rows:
        return 0

    def _do_write():
        ws.append_rows(rows, value_input_option="USER_ENTERED")

    retry_sheets_write(_do_write, retries=2, label=f"{SHEET_CHIP_HISTORY}寫入")
    log.info(f"「{SHEET_CHIP_HISTORY}」新增 {len(rows)} 筆（{trade_date}）")
    return len(rows)
