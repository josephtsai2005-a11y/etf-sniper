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
   在那個時間點幾乎必定是空的，等RUN_MODE=="ai"的AI job（2026-09-03起改成隔日05:00
   台股開盤前執行，原本是23:00）真正的資料回填進「多方驗證名單」時，「回測記錄」
   當天那筆已經記過、不會再更新，沿用它會導致這裡永遠比對到空值。改成在
   backfill_margin_signals_to_multi_sheet()真正拿到當天資料「之後」（同一個
   RUN_MODE=="ai"的隔日05:00 job裡）才呼叫append_chip_conflict_history()記錄，
   才能保證比對到的是真正的值。

2026-09-16追加第4種訊號「技術面共振轉向」（detect_resonance_shift()）與「值得截圖提醒」
（build_screenshot_worthy_list()）：背景見這兩個函式的docstring，簡言之是使用者問
「跟著贏家操作，要在什麼時間點去看券商分點截圖」——答案不是讓AI從截圖去猜時間，而是
反過來讓這裡既有（含新增）的純資料訊號主動告訴使用者「今天這幾檔值得去截圖」。

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

    today_date_str：目前處理的交易日trade_date（YYYYMMDD）。如果「籌碼矛盾歷史」分頁裡
    已經有這個日期的記錄（代表這個trade_date對應的AI job——RUN_MODE=="ai"，隔日05:00
    台股開盤前執行——已經跑過、append_chip_conflict_history()已經把這天的值寫進去了），
    需要先排除掉這筆，才能真正拿到「上一個交易日」，否則會誤把「今天」的記錄當成比較基準，
    變成「今天 vs 今天」，永遠比對不出任何變化。不傳這個參數時，直接取history_df裡最新的
    日期當基準（假設呼叫端知道歷史分頁還沒有寫入今天的資料，例如main.py在呼叫
    append_chip_conflict_history()「之前」呼叫這個函式的情境）。

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


# ── 技術面共振轉向（2026-09-16新增）：第4種訊號 ──────────────────────────
# 背景：使用者問「跟著贏家操作，實際上要在哪個時間點、或系統顯示哪些訊號時，才該去
# 找券商分點截圖？」——這4種訊號（含前3種既有的）合起來的用途，就是幫使用者從「每天
# 主動盯著看」，變成「系統告訴你今天哪幾檔剛好轉變，你再決定要不要去截圖」，見下面
# build_screenshot_worthy_list()。
#
# 這一種沿用price_fetcher.py計算「技術面共振」時就已經定義好的多空分類（跟
# broker_branch_analyzer.py::build_entry_exit_checklist()判斷「技術面共振」成立/不成立
# 用的是同一組字串常數，只是這裡額外多了「中性」分類，因為這裡要比對的是「有沒有
# 轉向」，不是「現在算不算成立」），跟前一交易日比對，抓「多頭/空頭/中性」三個分類
# 中的任何一種變化（不只多轉空這種劇烈變化，中性剛轉多/轉空同樣算，因為訊號剛開始
# 出現方向、或剛從有方向變模糊，本身就是值得注意的時間點）。
RESONANCE_BULL = {"🟢🟢 多頭共振", "🟢 偏多"}
RESONANCE_BEAR = {"🔴 偏空", "🔴🔴 空頭共振"}
RESONANCE_NEUTRAL = {"⚠️ 訊號分歧"}


def _resonance_bucket(val) -> str:
    """把「技術面共振」欄位的字串分成「多」/「空」/「中性」三類，格式不明或空值回傳
    None（代表沒有可比較的資料，呼叫端應該跳過而不是當成「中性」處理）。"""
    v = str(val).strip()
    if v in RESONANCE_BULL:
        return "多"
    if v in RESONANCE_BEAR:
        return "空"
    if v in RESONANCE_NEUTRAL:
        return "中性"
    return None


def detect_resonance_shift(multi_df: pd.DataFrame, backtest_df: pd.DataFrame,
                            today_date_str: str = None) -> pd.DataFrame:
    """
    技術面共振轉向：跟detect_chip_conflict_transitions()是同一種「今天 vs 上一個交易日」
    比對寫法，但資料來源換成backtest_tracker.py既有的「回測記錄」
    （record_daily_snapshot()在RUN_MODE=core/inst約16:45寫入）——技術指標不像融資融券
    要等到晚上才公布，同一天下午就有正確值，不需要像籌碼矛盾那樣另外開一張新的歷史
    分頁，直接重用「回測記錄」即可（見backtest_tracker.py::load_backtest_history()）。

    today_date_str：處理中的交易日，用來排除「回測記錄」裡可能已經記過今天這筆快照的
    情況，避免「今天 vs 今天」永遠比不出變化——邏輯跟detect_chip_conflict_transitions()
    完全一致，見該函式docstring。

    回傳欄位：股票代號、股票名稱、變化（例如「🔄 中性轉多」「🔄 多轉空」）、
    昨日技術面共振、今日技術面共振。冷啟動（這檔股票在上一個交易日沒有回測記錄）、
    或任一邊是空值/無法辨識的格式（`_resonance_bucket()`回傳None），都不會出現在
    結果裡——只比較「兩邊都有明確分類」的情況，避免把「資料不足」誤判成「轉向」。
    """
    if multi_df is None or multi_df.empty or "技術面共振" not in multi_df.columns:
        return pd.DataFrame()
    if backtest_df is None or backtest_df.empty or "記錄日期" not in backtest_df.columns:
        return pd.DataFrame()
    if "股票代號" not in backtest_df.columns:
        return pd.DataFrame()

    dates = sorted(backtest_df["記錄日期"].dropna().unique().tolist())
    if today_date_str and today_date_str in dates:
        dates = [d for d in dates if d != today_date_str]
    if not dates:
        return pd.DataFrame()
    prior_date = dates[-1]

    prior_slice = backtest_df[backtest_df["記錄日期"] == prior_date]
    prior_resonance = dict(zip(
        prior_slice["股票代號"].astype(str).str.strip(),
        prior_slice.get("技術面共振", pd.Series(dtype=str)).astype(str).str.strip(),
    ))

    records = []
    for _, row in multi_df.iterrows():
        code = str(row.get("股票代號", "")).strip()
        if not code or code not in prior_resonance:
            continue  # 冷啟動：這檔股票在上一個交易日沒有回測記錄，無法比較

        today_val = str(row.get("技術面共振", "")).strip()
        prior_val = prior_resonance.get(code, "")

        prior_bucket = _resonance_bucket(prior_val)
        today_bucket = _resonance_bucket(today_val)
        if prior_bucket is None or today_bucket is None or prior_bucket == today_bucket:
            continue

        records.append({
            "股票代號": code, "股票名稱": row.get("股票名稱", ""),
            "變化": f"🔄 {prior_bucket}轉{today_bucket}",
            "昨日技術面共振": prior_val, "今日技術面共振": today_val,
        })

    return pd.DataFrame(records)


def build_daily_alert_summary(multi_df: pd.DataFrame, diff_df: pd.DataFrame,
                               history_df: pd.DataFrame, backtest_df: pd.DataFrame = None,
                               today_date_str: str = None) -> dict:
    """
    整合四種訊號，回傳供Streamlit頁面/AI報告共用的摘要dict：
        {"concentration_up": df, "margin_abnormal": df, "chip_conflict_change": df,
         "resonance_shift": df}
    任一項無資料時對應值是空DataFrame，呼叫端可以直接用.empty判斷要不要顯示，
    不需要另外判斷None。

    2026-09-16新增第4種「resonance_shift」，`backtest_df`參數預設None（呼叫端沒有
    傳入「回測記錄」資料時，這一項直接回傳空DataFrame，不影響其他3種訊號正常運作，
    向下相容既有呼叫端）。
    """
    return {
        "concentration_up": detect_concentration_up(diff_df),
        "margin_abnormal": detect_margin_abnormal(multi_df),
        "chip_conflict_change": detect_chip_conflict_transitions(multi_df, history_df, today_date_str),
        "resonance_shift": detect_resonance_shift(
            multi_df, backtest_df if backtest_df is not None else pd.DataFrame(), today_date_str
        ),
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

    resonance = summary.get("resonance_shift", pd.DataFrame())
    if not resonance.empty:
        lines.append(f"\n【技術面共振轉向】共{len(resonance)}檔：")
        for _, r in resonance.head(10).iterrows():
            lines.append(f"- {r.get('股票代號','')} {r.get('股票名稱','')}：{r.get('變化','')}"
                          f"（昨{r.get('昨日技術面共振','')} → 今{r.get('今日技術面共振','')}）")

    return "\n".join(lines) if lines else ""


# ── 值得截圖提醒（2026-09-16新增）─────────────────────────────────────
# 背景：使用者問「跟著贏家操作，實際上要在哪個時間點、或系統顯示哪些訊號時，才該去
# 找券商分點截圖？如何利用現成的二手資訊來輔助資料，進一步提早預判入場退場時間？」
#
# 決策：不做「AI從券商分點截圖預測時間」（截圖本身是落後、靜態的一張圖，AI再怎麼
# 判讀也沒辦法比截圖當下更早）。真正能做到「提早」的方式，是反過來讓上面4種既有的
# 純資料訊號告訴使用者「這幾檔今天狀態剛好轉變，值得花時間去截圖確認」，而不是每天
# 漫無目的地篩選要看哪幾檔——這個函式本身不是新訊號，只是把上面4種訊號的股票代號
# 打包成一份「今天的截圖待辦清單」，同一檔股票可能同時觸發多種訊號，「觸發訊號」欄位
# 會列出全部，「訊號數」代表命中幾種既有訊號，可以自行參考優先順序，但這裡刻意不做
# 加權評分（維持誠實原則——不無中生有一個「綜合分數」）。
_SCREENSHOT_SIGNAL_LABELS = {
    "concentration_up": "📈 聰明錢集中度提升",
    "margin_abnormal": "💰 融資券異常",
    "chip_conflict_change": "⚡ 籌碼矛盾變化",
    "resonance_shift": "🔄 技術面共振轉向",
}


def build_screenshot_worthy_list(summary: dict) -> pd.DataFrame:
    """
    整合build_daily_alert_summary()四種訊號的股票代號，回傳「今天值得考慮去手動截圖看
    券商分點」的清單。回傳欄位：股票代號、股票名稱、觸發訊號（用、分隔多個訊號）、
    訊號數（觸發的訊號種類數，越多不代表「越該買」，只代表越多既有指標剛好同時轉變，
    值得交叉驗證）。四種訊號皆無資料時回傳空DataFrame。
    """
    rows = {}
    for key, label in _SCREENSHOT_SIGNAL_LABELS.items():
        df = summary.get(key, pd.DataFrame())
        if df is None or df.empty or "股票代號" not in df.columns:
            continue
        for _, r in df.iterrows():
            code = str(r.get("股票代號", "")).strip()
            if not code:
                continue
            if code not in rows:
                rows[code] = {"股票代號": code, "股票名稱": r.get("股票名稱", ""), "觸發訊號": []}
            rows[code]["觸發訊號"].append(label)

    if not rows:
        return pd.DataFrame()

    records = [
        {"股票代號": code, "股票名稱": info["股票名稱"],
         "觸發訊號": "、".join(info["觸發訊號"]), "訊號數": len(info["觸發訊號"])}
        for code, info in rows.items()
    ]
    return pd.DataFrame(records).sort_values("訊號數", ascending=False).reset_index(drop=True)


def format_screenshot_worthy_for_ai(df: pd.DataFrame) -> str:
    """把build_screenshot_worthy_list()的結果轉成AI報告用的純文字段落，不呼叫AI、
    零額外成本，寫法比照format_alert_summary_for_ai()。空輸入回傳空字串。"""
    if df is None or df.empty:
        return ""
    lines = [
        f"【🎯 值得截圖看券商分點】共{len(df)}檔（今天觸發至少一種上述訊號，建議手動截圖"
        f"上傳「券商分點分析」頁面交叉驗證——這不是自動判讀結果，需要你自己截圖上傳才會有"
        f"分點分析）："
    ]
    for _, r in df.head(10).iterrows():
        lines.append(f"- {r.get('股票代號','')} {r.get('股票名稱','')}（{r.get('觸發訊號','')}）")
    return "\n".join(lines)


def append_chip_conflict_history(ss, multi_df: pd.DataFrame, trade_date: str) -> int:
    """
    把今天每檔股票的「籌碼矛盾」「融資訊號」存成一筆歷史記錄（append-only，不會被覆寫），
    供之後detect_chip_conflict_transitions()比對「今天 vs 上一個交易日」用。

    呼叫時機：務必在backfill_margin_signals_to_multi_sheet()真正拿到當天融資融券資料
    「之後」呼叫（main.py的RUN_MODE=="ai"，2026-09-03起改成隔日05:00台股開盤前執行，
    原本是23:00），且務必在同一次執行裡「先」呼叫
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