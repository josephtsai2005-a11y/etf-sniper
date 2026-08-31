"""
topic_analyzer.py
題材總覽：整合題材趨勢 + 題材位置 + ETF覆蓋 + AI分析
"""
import os
import json
import logging
import pandas as pd
from retry_utils import retry_sheets_write

log = logging.getLogger(__name__)


def build_topic_overview(ss, smart_df: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    """
    整合所有題材資料，產生題材總覽
    """
    # 讀取題材趨勢
    trend_df = pd.DataFrame()
    try:
        ws = ss.worksheet("題材趨勢")
        vals = ws.get_all_values()
        if len(vals) >= 2:
            trend_df = pd.DataFrame(vals[2:], columns=vals[1])
    except Exception as e:
        log.warning(f"讀取題材趨勢失敗: {e}")

    # 讀取題材位置（含散戶情緒）
    position_df = pd.DataFrame()
    try:
        ws = ss.worksheet("題材位置")
        vals = ws.get_all_values()
        if len(vals) >= 2:
            position_df = pd.DataFrame(vals[2:], columns=vals[1])
    except Exception as e:
        log.warning(f"讀取題材位置失敗: {e}")

    if trend_df.empty:
        return pd.DataFrame()

    # 建立 ETF/AI關鍵字 題材對應表
    # 舊機制：DEFAULT_MAP_REVERSE（僅18檔手動清單）
    # 新機制：已核准的AI關鍵字，依母題材分組（theme_manager.py），涵蓋所有追蹤股票
    # 兩者合併使用，新機制涵蓋不到的地方由舊機制補（互為備援，不會讓資料變少）
    from trend_analyzer import DEFAULT_MAP_REVERSE
    try:
        from theme_manager import get_keyword_theme_map
        ai_theme_map = get_keyword_theme_map(ss)
    except Exception as e:
        log.warning(f"讀取AI母題材對照表失敗，僅使用舊版DEFAULT_MAP: {e}")
        ai_theme_map = {}

    # 整合資料
    records = []
    for _, row in trend_df.iterrows():
        keyword = row.get("關鍵字", "")
        if not keyword:
            continue

        # 找對應的散戶情緒資料
        sent_row = pd.Series()
        if not position_df.empty and "主題" in position_df.columns:
            match = position_df[position_df["主題"] == keyword]
            if not match.empty:
                sent_row = match.iloc[0]

        # 找 ETF 持有的相關股票：新機制（母題材對照）+ 舊機制（DEFAULT_MAP_REVERSE）合併，去重
        etf_stocks = []
        seen_codes = set()

        # 新機制：這個新聞熱詞剛好等於某個已核准母題材時，帶入該題材下所有股票
        if keyword in ai_theme_map:
            for code, sname in ai_theme_map[keyword]:
                if code not in seen_codes:
                    etf_stocks.append(f"{code} {sname}")
                    seen_codes.add(code)

        # 舊機制：DEFAULT_MAP_REVERSE 補充（涵蓋新機制還沒歸類到的部分）
        if not smart_df.empty:
            related = DEFAULT_MAP_REVERSE.get(keyword, [])
            for code in related:
                if code in seen_codes:
                    continue
                match_s = smart_df[smart_df["股票代號"].astype(str) == str(code)]
                if not match_s.empty:
                    etf_stocks.append(f"{code} {match_s.iloc[0].get('股票名稱','')}")
                    seen_codes.add(code)

        records.append({
            "題材": keyword,
            "階段": row.get("階段", ""),
            "今日篇數": row.get("今日篇數", 0),
            "近3日均": row.get("近3日均", 0),
            "趨勢": row.get("趨勢", ""),
            "散戶關注": sent_row.get("散戶關注度", "") if not sent_row.empty else "",
            "進場訊號": sent_row.get("進場訊號", "") if not sent_row.empty else "",
            "ETF相關持股": " / ".join(etf_stocks[:3]) if etf_stocks else "",
            "ETF布局數": len(etf_stocks),
        })

    df = pd.DataFrame(records)
    # 排序：ETF有布局 + 熱度上升 優先
    df["_sort"] = df["ETF布局數"].astype(int) * -1
    df = df.sort_values("_sort").drop(columns=["_sort"])
    return df


def ai_analyze_topic_overview(overview_df: pd.DataFrame, trade_date: str) -> str:
    """
    用 Claude 分析題材總覽，產生投資洞察
    """
    from ai_analyzer import call_claude

    if overview_df.empty:
        return ""

    rows = []
    for _, row in overview_df.head(15).iterrows():
        rows.append(
            f"題材:{row['題材']} | 階段:{row['階段']} | 今日:{row['今日篇數']}篇 | "
            f"趨勢:{row['趨勢']} | 散戶:{row['散戶關注']} | "
            f"進場:{row['進場訊號']} | ETF持股:{row['ETF相關持股']}"
        )
    data_str = "\n".join(rows)

    prompt = f"""今日（{trade_date}）台股題材分析資料：

{data_str}

請分析：
1. 哪些題材 ETF 有明確布局（ETF相關持股不為空）且熱度上升？
2. 哪些題材散戶淡漠但 ETF 在布局（最佳反向指標）？
3. 哪些題材已經過熱（散戶追捧），應該迴避？
4. 今日最值得關注的 2-3 個題材，說明理由

用繁體中文，簡潔有力，每點不超過50字。"""

    return call_claude(prompt, max_tokens=800)


def write_topic_overview_to_sheets(ss, df: pd.DataFrame, ai_insight: str, trade_date: str):
    """寫入題材總覽到 Sheets（含重試保護——這裡整合了AI分析結果，重跑一次要重新呼叫Claude API，
    成本比純資料寫入高，值得多花點時間重試）"""
    SHEET = "題材總覽"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET not in existing:
        ss.add_worksheet(title=SHEET, rows=500, cols=15)
    ws = ss.worksheet(SHEET)

    all_rows = [[f"題材總覽 {trade_date}　AI洞察已整合"]]
    if ai_insight:
        all_rows.append([f"AI分析：{ai_insight}"])
        all_rows.append([])
    if not df.empty:
        all_rows.append(df.columns.tolist())
        all_rows.extend(df.fillna("").values.tolist())

    def _do_write():
        ws.clear()
        ws.append_rows(all_rows, value_input_option="USER_ENTERED")

    retry_sheets_write(_do_write, retries=2, label="題材總覽寫入")
    log.info(f"題材總覽寫入完成：{len(df)} 個題材")


def build_master_theme_overview(ss):
    """
    母題材總覽：直接依「已核准母題材」彙整，不依賴新聞熱詞文字剛好對上母題材名稱
    這是解決「446個細顆粒度關鍵字看不清楚」問題的核心呈現——
    把散落在58檔股票底下、語義重疊的細關鍵字，收斂到20-30個母題材層級

    第二階段新增：區分「活躍」與「已沉寂」（連續30天無新聞熱度）題材，
    沉寂題材移到次要顯示區塊，不刪除資料，熱度回升會自動移回活躍區塊

    回傳：(活躍題材df, 沉寂題材df)，欄位皆為：母題材、涵蓋股票數、相關股票、關鍵字數
    """
    try:
        from theme_manager import get_keyword_theme_map, get_dormant_themes
        from keyword_generator import _load_keyword_queue
    except Exception as e:
        log.warning(f"母題材總覽建立失敗: {e}")
        return pd.DataFrame(), pd.DataFrame()

    theme_map = get_keyword_theme_map(ss)
    if not theme_map:
        return pd.DataFrame(), pd.DataFrame()

    dormant_themes = set(get_dormant_themes(ss))

    queue_df = _load_keyword_queue(ss)
    approved_kws = queue_df[queue_df["狀態"] == "已核准"] if not queue_df.empty else pd.DataFrame()

    active_records = []
    dormant_records = []
    for theme, stocks in theme_map.items():
        kw_count = 0
        if not approved_kws.empty and "母題材" in approved_kws.columns:
            kw_count = len(approved_kws[approved_kws["母題材"] == theme])

        stock_display = " / ".join(f"{code} {name}" for code, name in stocks[:6])
        if len(stocks) > 6:
            stock_display += f" ...等{len(stocks)}檔"

        record = {
            "母題材": theme,
            "涵蓋股票數": len(stocks),
            "相關股票": stock_display,
            "關鍵字數": kw_count,
        }

        if theme in dormant_themes:
            dormant_records.append(record)
        else:
            active_records.append(record)

    active_df = pd.DataFrame(active_records)
    if not active_df.empty:
        active_df = active_df.sort_values("涵蓋股票數", ascending=False).reset_index(drop=True)

    dormant_df = pd.DataFrame(dormant_records)
    if not dormant_df.empty:
        dormant_df = dormant_df.sort_values("涵蓋股票數", ascending=False).reset_index(drop=True)

    return active_df, dormant_df