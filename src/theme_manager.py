"""
theme_manager.py
母題材（Master Theme）清單管理

設計核心：「AI做重活、人類做守門」
  - 第一階段（配對優先）：AI生成個股關鍵字時，會被要求優先從「現有已核准母題材清單」裡挑一個最合適的
    只有真的沒有合適選項，AI才能「建議」一個全新母題材——需人工審核才會生效
  - 第二階段（本檔案新增）：
    a) 定期整併：每週一次，AI審視現有母題材清單，抓出語義重複的組合建議合併，
       同樣需人工審核；核准後自動把底下所有已核准關鍵字重新指向保留下來的題材
    b) 沉寂淘汰：不刪除資料，只是「題材總覽」顯示時把長期無新聞熱度的題材
       自動移到次要區塊，全自動不需審核（純顯示排序，可逆，熱度回升會自動移回主區塊）

母題材清單存在「母題材清單」分頁，欄位：母題材、建立日期、狀態、來源關鍵字、最後熱度日期
"""
import logging
import time
import pandas as pd
from datetime import datetime, timedelta
import pytz
import gspread

from ai_analyzer import call_claude

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_THEME_LIST = "母題材清單"
SHEET_MERGE_QUEUE = "母題材整併建議"
THEME_COLS = ["母題材", "建立日期", "狀態", "來源關鍵字", "最後熱度日期"]
MERGE_COLS = ["建議合併組", "建議保留名稱", "建議日期", "狀態"]

THEME_STATUS_PENDING = "待審核"
THEME_STATUS_APPROVED = "已核准"
THEME_STATUS_REJECTED = "已拒絕"
THEME_STATUS_MERGED = "已合併"

MERGE_STATUS_PENDING = "待審核"
MERGE_STATUS_APPROVED = "已核准"
MERGE_STATUS_REJECTED = "已拒絕"

DORMANT_DAYS_THRESHOLD = 30  # 連續這麼多天沒有新聞熱度，就歸類為「已沉寂」


def _with_retry(func, retries: int = 3, base_delay: float = 2.0):
    """
    Google Sheets API 429（頻率限制）重試包裝器
    Streamlit頁面短時間內可能疊加多次讀取，容易撞到每分鐘60次請求的上限，
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

# 種子母題材：系統第一次啟用時的起始清單，讓AI一開始就有東西可以配對，
# 不用從零開始每個關鍵字都提案新題材。之後會隨AI建議+人工核准持續成長。
SEED_THEMES = [
    "CoWoS", "先進封裝", "AI伺服器", "HBM", "液冷散熱", "電源管理",
    "NVIDIA", "電動車", "GB200", "矽光子", "台積電供應鏈", "散熱模組",
    "記憶體", "半導體設備", "網通/交換器", "PCB/CCL", "機殼/機構件",
    "被動元件", "IC設計", "封裝測試", "電源供應器", "資料中心",
]


def _load_theme_list(ss) -> pd.DataFrame:
    """讀取母題材清單，不存在則建立並灌入種子清單"""
    try:
        ws = _with_retry(lambda: ss.worksheet(SHEET_THEME_LIST))
        vals = _with_retry(lambda: ws.get_all_values())
        if len(vals) < 2:
            return _init_seed_themes(ss)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in THEME_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except gspread.exceptions.WorksheetNotFound:
        return _init_seed_themes(ss)
    except Exception as e:
        log.warning(f"讀取母題材清單失敗: {e}")
        return pd.DataFrame(columns=THEME_COLS)


def _init_seed_themes(ss) -> pd.DataFrame:
    """第一次使用時，用種子清單初始化母題材分頁（全部直接標記為已核准）"""
    today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    rows = [
        {"母題材": t, "建立日期": today_str, "狀態": THEME_STATUS_APPROVED, "來源關鍵字": "(系統種子清單)"}
        for t in SEED_THEMES
    ]
    df = pd.DataFrame(rows)
    _write_theme_list(ss, df)
    log.info(f"母題材清單：首次初始化，灌入 {len(rows)} 個種子母題材")
    return df


def _write_theme_list(ss, df: pd.DataFrame):
    """整表覆寫回Sheets"""
    def _do_write():
        existing = [ws.title for ws in ss.worksheets()]
        if SHEET_THEME_LIST not in existing:
            ws = ss.add_worksheet(title=SHEET_THEME_LIST, rows=500, cols=10)
        else:
            ws = ss.worksheet(SHEET_THEME_LIST)
        ws.clear()
        ws.append_row(df.columns.tolist())
        if not df.empty:
            ws.append_rows(df.fillna("").values.tolist(), value_input_option="USER_ENTERED")

    try:
        _with_retry(_do_write)
    except Exception as e:
        log.warning(f"寫入母題材清單失敗: {e}")


def get_approved_themes(ss) -> list:
    """取得所有已核准的母題材名稱清單，供AI生成關鍵字時當作配對選項"""
    df = _load_theme_list(ss)
    if df.empty:
        return list(SEED_THEMES)
    approved = df[df["狀態"] == THEME_STATUS_APPROVED]
    return approved["母題材"].tolist()


def get_pending_themes(ss) -> pd.DataFrame:
    """取得所有待審核的母題材，供Streamlit審核頁面顯示"""
    df = _load_theme_list(ss)
    if df.empty:
        return df
    return df[df["狀態"] == THEME_STATUS_PENDING].reset_index(drop=True)


def propose_new_theme(ss, theme_name: str, source_keyword: str = ""):
    """
    AI生成關鍵字時，如果現有清單沒有合適的母題材，會呼叫這個函式提案一個新的
    如果這個題材名稱已經存在（不管什麼狀態），不會重複新增
    """
    theme_name = theme_name.strip()
    if not theme_name:
        return

    df = _load_theme_list(ss)
    if not df.empty and theme_name in df["母題材"].tolist():
        return  # 已存在，不重複提案

    today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    new_row = {
        "母題材": theme_name,
        "建立日期": today_str,
        "狀態": THEME_STATUS_PENDING,
        "來源關鍵字": source_keyword,
    }
    combined = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True) if not df.empty else pd.DataFrame([new_row])
    _write_theme_list(ss, combined)
    log.info(f"母題材提案：新增待審核母題材「{theme_name}」（來源關鍵字：{source_keyword}）")


def apply_theme_review_decisions(ss, decisions: dict) -> int:
    """
    套用管理者對母題材的審核決定
    decisions: {母題材名稱: "已核准" 或 "已拒絕"}
    """
    df = _load_theme_list(ss)
    if df.empty:
        return 0
    updated = 0
    for idx, row in df.iterrows():
        if row["母題材"] in decisions:
            df.at[idx, "狀態"] = decisions[row["母題材"]]
            updated += 1
    if updated > 0:
        _write_theme_list(ss, df)
    return updated


def get_keyword_theme_map(ss, keyword_queue_df: pd.DataFrame = None) -> dict:
    """
    建立「母題材 → 相關股票清單」的反查表，供 topic_analyzer.py 的題材總覽使用
    只採計「已核准的母題材」+「已核准的關鍵字」，確保題材總覽只呈現真正審核通過的資料
    回傳：{母題材: [(股票代號, 股票名稱), ...]}
    """
    if keyword_queue_df is None:
        try:
            from keyword_generator import _load_keyword_queue
            keyword_queue_df = _load_keyword_queue(ss)
        except Exception:
            return {}

    if keyword_queue_df.empty or "母題材" not in keyword_queue_df.columns:
        return {}

    approved_themes = set(get_approved_themes(ss))
    approved_kws = keyword_queue_df[keyword_queue_df["狀態"] == "已核准"]

    result = {}
    for _, row in approved_kws.iterrows():
        theme = row.get("母題材", "").strip()
        if not theme or theme not in approved_themes:
            continue
        result.setdefault(theme, set()).add((row["股票代號"], row["股票名稱"]))

    return {theme: sorted(stocks) for theme, stocks in result.items()}


# ══════════════════════════════════════════════════════════════
# 第二階段 a：定期整併——AI審視母題材清單，建議合併語義重複的題材
# ══════════════════════════════════════════════════════════════

def _load_merge_queue(ss) -> pd.DataFrame:
    """讀取母題材整併建議佇列"""
    try:
        ws = _with_retry(lambda: ss.worksheet(SHEET_MERGE_QUEUE))
        vals = _with_retry(lambda: ws.get_all_values())
        if len(vals) < 2:
            return pd.DataFrame(columns=MERGE_COLS)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in MERGE_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=MERGE_COLS)
    except Exception as e:
        log.warning(f"讀取母題材整併建議失敗: {e}")
        return pd.DataFrame(columns=MERGE_COLS)


def _write_merge_queue(ss, df: pd.DataFrame):
    """整表覆寫回Sheets"""
    def _do_write():
        existing = [ws.title for ws in ss.worksheets()]
        if SHEET_MERGE_QUEUE not in existing:
            ws = ss.add_worksheet(title=SHEET_MERGE_QUEUE, rows=200, cols=10)
        else:
            ws = ss.worksheet(SHEET_MERGE_QUEUE)
        ws.clear()
        ws.append_row(df.columns.tolist())
        if not df.empty:
            ws.append_rows(df.fillna("").values.tolist(), value_input_option="USER_ENTERED")

    try:
        _with_retry(_do_write)
    except Exception as e:
        log.warning(f"寫入母題材整併建議失敗: {e}")


def suggest_theme_merges(ss, min_theme_count: int = 15) -> int:
    """
    每週執行一次：讓AI檢視目前所有已核准母題材，抓出語義重複的組合，建議合併
    只有母題材數量達到一定規模才值得做這個檢查（太少沒有整併的意義，也省AI呼叫）
    建議結果寫入「母題材整併建議」分頁，需人工審核才會真的生效
    回傳：本次新增幾筆整併建議
    """
    themes = get_approved_themes(ss)
    if len(themes) < min_theme_count:
        log.info(f"母題材整併檢查：目前只有{len(themes)}個已核准母題材，未達{min_theme_count}個門檻，跳過本次檢查")
        return 0

    existing_merge_df = _load_merge_queue(ss)
    already_suggested_themes = set()
    if not existing_merge_df.empty:
        pending_or_approved = existing_merge_df[existing_merge_df["狀態"] != MERGE_STATUS_REJECTED]
        for _, row in pending_or_approved.iterrows():
            group = str(row.get("建議合併組", "")).split("、")
            already_suggested_themes.update(g.strip() for g in group)

    themes_text = "、".join(themes)

    prompt = f"""你是台股產業分析師。以下是目前系統使用的母題材（用於歸類個股題材關鍵字）完整清單：

{themes_text}

請仔細檢視這份清單，找出**語義高度重疊、實質上代表同一件事**的母題材組合（例如「AI伺服器」跟「AI伺服器供應鏈」可能是重複的）。

規則：
- 只挑出真正重複、會讓使用者混淆「這兩個題材差在哪」的組合，不要為了湊數硬找
- 每組建議2-3個要合併的題材，並指定一個「保留名稱」（通常是較簡潔、較常用的那個）
- 如果清單裡沒有明顯重複的，就不用勉強建議

請用以下格式回傳，每行一組，用「|」分隔要合併的題材（用、分隔多個）與保留名稱，沒有建議就回傳「無」：
題材A、題材B|保留名稱
題材C、題材D、題材E|保留名稱

現在請檢視並給出建議："""

    result = call_claude(
        prompt,
        system="你是嚴謹的台股產業分析師，只在真正有語義重複時才建議合併，不會為了湊數勉強合併不相關的題材。",
        max_tokens=500,
    )
    if not result or result.strip() in ("無", "無建議"):
        log.info("母題材整併檢查：本次AI判斷沒有需要合併的重複題材")
        return 0

    today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    new_rows = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 1)
        group_raw = parts[0].strip()
        keep_name = parts[1].strip() if len(parts) > 1 else ""
        group_themes = [g.strip() for g in group_raw.split("、") if g.strip()]

        if len(group_themes) < 2 or not keep_name:
            continue
        if not all(t in themes for t in group_themes):
            continue  # 有題材不在目前清單裡，可能AI幻覺，跳過
        if any(t in already_suggested_themes for t in group_themes):
            continue  # 避免重複建議同一組

        new_rows.append({
            "建議合併組": "、".join(group_themes),
            "建議保留名稱": keep_name,
            "建議日期": today_str,
            "狀態": MERGE_STATUS_PENDING,
        })
        already_suggested_themes.update(group_themes)

    if new_rows:
        combined = pd.concat([existing_merge_df, pd.DataFrame(new_rows)], ignore_index=True) if not existing_merge_df.empty else pd.DataFrame(new_rows)
        _write_merge_queue(ss, combined)
        log.info(f"母題材整併檢查：新增 {len(new_rows)} 筆整併建議待審核")

    return len(new_rows)


def get_pending_merges(ss) -> pd.DataFrame:
    """取得所有待審核的整併建議，供Streamlit審核頁面顯示"""
    df = _load_merge_queue(ss)
    if df.empty:
        return df
    return df[df["狀態"] == MERGE_STATUS_PENDING].reset_index(drop=True)


def apply_merge_decisions(ss, decisions: dict) -> int:
    """
    套用管理者對整併建議的審核決定
    decisions: {建議合併組字串: "已核准" 或 "已拒絕"}
    核准時：把來源題材下所有已核准關鍵字重新指向保留名稱，來源題材狀態改為「已合併」
    """
    merge_df = _load_merge_queue(ss)
    if merge_df.empty:
        return 0

    updated = 0
    approved_merges = []  # [(來源題材list, 保留名稱), ...]

    for idx, row in merge_df.iterrows():
        group_key = row["建議合併組"]
        if group_key in decisions:
            merge_df.at[idx, "狀態"] = decisions[group_key]
            updated += 1
            if decisions[group_key] == MERGE_STATUS_APPROVED:
                source_themes = [t.strip() for t in group_key.split("、") if t.strip()]
                keep_name = row["建議保留名稱"]
                approved_merges.append((source_themes, keep_name))

    if updated > 0:
        _write_merge_queue(ss, merge_df)

    # 實際執行合併：重新指派關鍵字的母題材、更新母題材清單狀態
    if approved_merges:
        try:
            from keyword_generator import _load_keyword_queue, _write_keyword_queue
            kw_df = _load_keyword_queue(ss)
        except Exception as e:
            log.warning(f"整併執行失敗，無法讀取關鍵字審核佇列: {e}")
            kw_df = pd.DataFrame()

        theme_df = _load_theme_list(ss)

        for source_themes, keep_name in approved_merges:
            themes_to_merge = [t for t in source_themes if t != keep_name]  # 保留名稱本身不用改自己

            if not kw_df.empty and "母題材" in kw_df.columns:
                mask = kw_df["母題材"].isin(themes_to_merge)
                kw_df.loc[mask, "母題材"] = keep_name

            if not theme_df.empty:
                merge_mask = theme_df["母題材"].isin(themes_to_merge)
                theme_df.loc[merge_mask, "狀態"] = THEME_STATUS_MERGED

            log.info(f"母題材整併執行：{themes_to_merge} → 合併入「{keep_name}」")

        if not kw_df.empty:
            _write_keyword_queue(ss, kw_df)
        if not theme_df.empty:
            _write_theme_list(ss, theme_df)

    return updated


# ══════════════════════════════════════════════════════════════
# 第二階段 b：沉寂淘汰——長期無新聞熱度的母題材自動移到次要顯示區塊
# ══════════════════════════════════════════════════════════════

def update_theme_freshness(ss, trend_df: pd.DataFrame):
    """
    每次題材趨勢資料更新後呼叫：檢查有哪些母題材今天有新聞熱度（階段不是沉寂/衰退），
    更新「母題材清單」的「最後熱度日期」欄位
    trend_df: 題材趨勢資料（含「關鍵字」「階段」欄位）
    """
    if trend_df.empty or "關鍵字" not in trend_df.columns:
        return

    active_keywords = set(
        trend_df[~trend_df.get("階段", "").isin(["沉寂", "衰退"])]["關鍵字"].tolist()
    )
    if not active_keywords:
        return

    theme_df = _load_theme_list(ss)
    if theme_df.empty:
        return

    today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")
    updated = 0
    for idx, row in theme_df.iterrows():
        if row["母題材"] in active_keywords:
            theme_df.at[idx, "最後熱度日期"] = today_str
            updated += 1

    if updated > 0:
        _write_theme_list(ss, theme_df)
        log.info(f"母題材熱度更新：{updated} 個題材今日有新聞熱度")


def get_dormant_themes(ss, days_threshold: int = DORMANT_DAYS_THRESHOLD) -> list:
    """
    取得「已沉寂」的母題材清單：已核准，但最後熱度日期超過門檻天數（或從未有過熱度記錄）
    供 topic_analyzer.py 的母題材總覽把這些題材移到次要區塊顯示
    """
    theme_df = _load_theme_list(ss)
    if theme_df.empty:
        return []

    approved = theme_df[theme_df["狀態"] == THEME_STATUS_APPROVED].copy()
    if approved.empty:
        return []

    cutoff_date = (datetime.now(TW_TZ) - timedelta(days=days_threshold)).strftime("%Y-%m-%d")

    dormant = []
    for _, row in approved.iterrows():
        last_active = row.get("最後熱度日期", "")
        # 從未記錄過熱度、或最後熱度日期早於門檻，都視為沉寂
        if not last_active or last_active < cutoff_date:
            dormant.append(row["母題材"])

    return dormant