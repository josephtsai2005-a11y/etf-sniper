"""
theme_manager.py
母題材（Master Theme）清單管理

設計核心：「AI做重活、人類做守門」
  - AI生成個股關鍵字時，會被要求優先從「現有已核准母題材清單」裡挑一個最合適的
  - 只有真的沒有合適選項，AI才能「建議」一個全新母題材——但這個建議不會馬上生效，
    會進入「待審核」狀態，需要管理者在Streamlit核准後才會變成正式的母題材
  - 這樣可以避免母題材本身也像關鍵字一樣無限增生、失控發散
  - 之後（第二階段）會再加上「定期整併」機制，讓語義重複的母題材可以合併

母題材清單存在「母題材清單」分頁，欄位：母題材、建立日期、狀態、來源關鍵字（首次被建議時的關鍵字，供審核參考）
"""
import logging
import pandas as pd
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_THEME_LIST = "母題材清單"
THEME_COLS = ["母題材", "建立日期", "狀態", "來源關鍵字"]
THEME_STATUS_PENDING = "待審核"
THEME_STATUS_APPROVED = "已核准"
THEME_STATUS_REJECTED = "已拒絕"

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
        ws = ss.worksheet(SHEET_THEME_LIST)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return _init_seed_themes(ss)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in THEME_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except Exception:
        return _init_seed_themes(ss)


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
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_THEME_LIST not in existing:
        ws = ss.add_worksheet(title=SHEET_THEME_LIST, rows=500, cols=10)
    else:
        ws = ss.worksheet(SHEET_THEME_LIST)
    ws.clear()
    ws.append_row(df.columns.tolist())
    if not df.empty:
        ws.append_rows(df.fillna("").values.tolist(), value_input_option="USER_ENTERED")


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
