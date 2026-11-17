"""
sector_flow_analyzer.py（2026-11-17新增）
「主動式ETF資金輪動」功能第一階段：把每日ETF持股加碼/減碼彙總（diff_analyzer.
aggregate_stock_diff()的輸出）按產業分類加總，算出「這幾天主動式ETF整體在加碼/減碼
哪個產業」——資料來源是這些ETF基金經理人自己真實的持股變動，不是AI推論的輪動敘述
（詳見claude/discussion_20261015_rotation_narrative_and_journal_tab_design.md：
系統原本完全沒有真正的資金輪動偵測機制，AI報告裡的「輪動」文字純粹是經驗法則推理）。

跟後續第二階段（全市場法人資金流向，依官方三大法人買賣超資料按產業彙總）互補：
- 這裡：涵蓋範圍限於目前追蹤的主動式ETF有持有的股票，但是「真實持股變動」，可靠度高
- 法人版：涵蓋全市場，但反映的是「法人整體」資金流向，不是專指主動式ETF
兩者各自標明資料來源與涵蓋範圍，不混成一個分數，延續專案一貫的「兩層可靠度」設計理念
（對照ai_analyzer.py的build_affordable_picks_section() vs generate_related_stocks()）。
"""
import pandas as pd
import logging

log = logging.getLogger(__name__)

SHEET_INDUSTRY_MAP = "產業分類對照表"
SHEET_SECTOR_FLOW  = "ETF產業資金流"
UNCLASSIFIED_LABEL = "⚠️ 未分類"


def load_industry_map(ss) -> dict:
    """
    讀取「產業分類對照表」分頁（由etf_registry.refresh_industry_classification()
    每季更新），回傳 {股票代號: 產業類別} 的字典。

    分頁不存在/讀取失敗/資料為空，都回傳空字典——呼叫端compute_etf_sector_flow()遇到
    空字典時，全部股票都會落在「⚠️ 未分類」，不會讓整個每日流程因為這份輔助資料缺失而
    失敗，也不會悄悄假裝有分類結果。
    """
    try:
        ws = ss.worksheet(SHEET_INDUSTRY_MAP)
        all_vals = ws.get_all_values()
        if len(all_vals) < 2:
            log.warning("產業分類對照表為空，本次「ETF產業資金流」全部歸入未分類")
            return {}
        df = pd.DataFrame(all_vals[1:], columns=all_vals[0])
        if "股票代號" not in df.columns or "產業類別" not in df.columns:
            log.warning("產業分類對照表欄位不符預期，本次「ETF產業資金流」全部歸入未分類")
            return {}
        df["股票代號"] = df["股票代號"].astype(str).str.strip()
        return dict(zip(df["股票代號"], df["產業類別"]))
    except Exception as e:
        log.warning(f"讀取產業分類對照表失敗（本次「ETF產業資金流」全部歸入未分類）: {e}")
        return {}


def compute_etf_sector_flow(stock_diff: pd.DataFrame, industry_map: dict) -> pd.DataFrame:
    """
    把aggregate_stock_diff()的輸出（每檔股票的加碼/減碼ETF數、總變動張數、總資金動向）
    按產業分類加總，算出產業層級的淨訊號排行。

    回傳欄位：排名、產業類別、加碼ETF數合計、減碼ETF數合計、淨訊號
    （=加碼ETF數合計-減碼ETF數合計）、總變動張數、總資金動向（若stock_diff有此欄）、
    涉及股票數，依資金動向（或淨訊號）排序。
    """
    if stock_diff is None or stock_diff.empty:
        return pd.DataFrame()

    df = stock_diff.copy()
    df["股票代號"] = df["股票代號"].astype(str).str.strip()
    df["產業類別"] = df["股票代號"].map(industry_map).fillna(UNCLASSIFIED_LABEL)

    has_amount = "總資金動向" in df.columns
    agg_dict = {
        "加碼ETF數合計": ("加碼ETF數", "sum"),
        "減碼ETF數合計": ("減碼ETF數", "sum"),
        "總變動張數":    ("總變動張數", "sum"),
        "涉及股票數":    ("股票代號", "nunique"),
    }
    if has_amount:
        agg_dict["總資金動向"] = ("總資金動向", "sum")

    agg = df.groupby("產業類別").agg(**agg_dict).reset_index()
    agg["淨訊號"] = agg["加碼ETF數合計"] - agg["減碼ETF數合計"]

    sort_col = "總資金動向" if has_amount else "淨訊號"
    agg = agg.sort_values(sort_col, ascending=False).reset_index(drop=True)
    agg.insert(0, "排名", range(1, len(agg) + 1))

    unclassified_n = agg.loc[agg["產業類別"] == UNCLASSIFIED_LABEL, "涉及股票數"].sum()
    if unclassified_n:
        log.info(f"ETF產業資金流：{int(unclassified_n)} 檔股票無產業分類資料，歸入「{UNCLASSIFIED_LABEL}」")

    return agg