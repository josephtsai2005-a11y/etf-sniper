"""
topic_analyzer.py
題材總覽：整合題材趨勢 + 題材位置 + ETF覆蓋 + AI分析
"""
import os
import json
import logging
import pandas as pd

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

    # 建立 ETF 題材對應表（從聰明錢名單推導）
    # 每個股票代號對應的題材，從 DEFAULT_MAP 取得
    from trend_analyzer import match_keywords_to_stocks
    
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

        # 找 ETF 持有的相關股票
        etf_stocks = []
        if not smart_df.empty:
            from trend_analyzer import DEFAULT_MAP_REVERSE
            related = DEFAULT_MAP_REVERSE.get(keyword, [])
            for code in related:
                match_s = smart_df[smart_df["股票代號"].astype(str) == str(code)]
                if not match_s.empty:
                    etf_stocks.append(f"{code} {match_s.iloc[0].get('股票名稱','')}")

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
    """寫入題材總覽到 Sheets"""
    import time
    SHEET = "題材總覽"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET not in existing:
        ss.add_worksheet(title=SHEET, rows=500, cols=15)
    ws = ss.worksheet(SHEET)
    ws.clear()
    ws.append_row([f"題材總覽 {trade_date}　AI洞察已整合"])
    if ai_insight:
        ws.append_row([f"AI分析：{ai_insight}"])
        ws.append_row([])
    if not df.empty:
        time.sleep(3)
        ws.append_row(df.columns.tolist())
        ws.append_rows(df.fillna("").values.tolist())
    log.info(f"題材總覽寫入完成：{len(df)} 個題材")
