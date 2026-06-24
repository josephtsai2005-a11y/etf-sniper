"""
trend_analyzer.py
題材生命週期分析
從歷史新聞時序資料計算每個關鍵字的成長曲線
偵測：萌芽 / 成長 / 爆發 / 衰退 四個階段
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


def compute_keyword_timeseries(news_history_df: pd.DataFrame) -> pd.DataFrame:
    """
    從歷史新聞庫計算每個關鍵字每日出現次數
    輸入：含「抓取日期」「命中關鍵字」的歷史新聞 DataFrame
    輸出：日期 × 關鍵字 的時序表
    """
    if news_history_df.empty:
        return pd.DataFrame()

    date_col    = "抓取日期"
    keyword_col = "命中關鍵字"

    if date_col not in news_history_df.columns or keyword_col not in news_history_df.columns:
        log.warning("缺少必要欄位")
        return pd.DataFrame()

    rows = []
    for _, row in news_history_df.iterrows():
        date = row[date_col]
        keywords = [k.strip() for k in str(row[keyword_col]).split(",") if k.strip()]
        for kw in keywords:
            rows.append({"日期": date, "關鍵字": kw, "計數": 1})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    pivot = df.groupby(["日期", "關鍵字"])["計數"].sum().unstack(fill_value=0)
    pivot = pivot.sort_index()
    return pivot


def detect_lifecycle_stage(series: pd.Series, window: int = 7) -> str:
    """
    判斷題材生命週期階段
    series：單一關鍵字的時序（日期為 index，計數為 value）
    """
    if len(series) < 3:
        return "📊 資料不足"

    values = series.values
    n = len(values)

    # 近3日 vs 近7日（或全部）
    recent3 = np.mean(values[-3:]) if n >= 3 else np.mean(values)
    recent7 = np.mean(values[-min(7, n):])
    peak    = np.max(values)
    latest  = values[-1]

    # 成長率
    if recent7 > 0:
        growth_rate = (recent3 - recent7) / recent7
    else:
        growth_rate = 0

    # 判斷階段
    if recent3 == 0 and recent7 == 0:
        return "💤 沉寂"
    elif latest < peak * 0.3 and peak > 5:
        return "📉 衰退"
    elif growth_rate > 2.0 or (recent3 > 10 and growth_rate > 0.5):
        return "🔥 爆發"
    elif growth_rate > 0.5:
        return "⚡ 成長"
    elif recent3 > 0:
        return "🌱 萌芽"
    else:
        return "💤 沉寂"


def compute_trend_report(pivot_df: pd.DataFrame) -> pd.DataFrame:
    """
    對所有關鍵字計算趨勢報告
    回傳：關鍵字、當前階段、近3日均量、近7日均量、成長率、峰值
    """
    if pivot_df.empty:
        return pd.DataFrame()

    records = []
    for keyword in pivot_df.columns:
        series = pivot_df[keyword].fillna(0)
        values = series.values

        n       = len(values)
        recent1 = int(values[-1]) if n >= 1 else 0
        recent3 = round(np.mean(values[-3:]), 1) if n >= 3 else round(np.mean(values), 1)
        recent7 = round(np.mean(values[-min(7, n):]), 1)
        peak    = int(np.max(values))
        total   = int(np.sum(values))

        growth_rate = round((recent3 - recent7) / recent7 * 100, 1) if recent7 > 0 else 0
        stage = detect_lifecycle_stage(series)

        # 趨勢方向
        if n >= 2:
            delta = values[-1] - values[-2]
            trend = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        else:
            trend = "→"

        records.append({
            "關鍵字":    keyword,
            "階段":      stage,
            "今日篇數":  recent1,
            "近3日均":   recent3,
            "近7日均":   recent7,
            "成長率%":   growth_rate,
            "峰值篇數":  peak,
            "累計篇數":  total,
            "趨勢":      trend,
        })

    df = pd.DataFrame(records)

    # 排序：爆發 > 成長 > 萌芽 > 衰退 > 沉寂，同階段依成長率排
    stage_order = {
        "🔥 爆發": 0, "⚡ 成長": 1, "🌱 萌芽": 2,
        "📉 衰退": 3, "💤 沉寂": 4, "📊 資料不足": 5
    }
    df["階段排序"] = df["階段"].map(stage_order).fillna(5)
    df = df.sort_values(["階段排序", "成長率%"], ascending=[True, False])
    df = df.drop("階段排序", axis=1).reset_index(drop=True)
    df.insert(0, "排名", range(1, len(df) + 1))

    return df


def match_keywords_to_stocks(
    trend_df: pd.DataFrame,
    smart_df: pd.DataFrame,
    stock_keyword_map: Optional[Dict] = None
) -> pd.DataFrame:
    """
    將新聞熱詞對應到個股
    stock_keyword_map: {股票代號: [相關關鍵字列表]}
    """
    if trend_df.empty or smart_df.empty:
        return pd.DataFrame()

    # 預設個股關鍵字對應表
    DEFAULT_MAP = {
        "2330": ["台積電法說", "先進製程", "CoWoS", "NVIDIA", "GB200", "HBM"],
        "2454": ["AI伺服器", "NVIDIA", "GB200", "先進製程"],
        "2383": ["CoWoS", "先進封裝", "先進製程"],
        "2308": ["電源管理", "AI伺服器", "電動車"],
        "6223": ["CoWoS", "先進封裝", "矽光子"],
        "3037": ["CoWoS", "先進封裝", "PCB"],
        "2327": ["被動元件", "電動車", "AI伺服器"],
        "2345": ["網通", "400G", "AI伺服器"],
        "3017": ["散熱", "AI伺服器", "液冷"],
        "6274": ["散熱", "AI伺服器", "液冷"],
        "2059": ["鉸鏈", "筆電", "AI PC"],
        "2368": ["MLCC", "被動元件", "電動車"],
        "5274": ["散熱", "AI伺服器"],
        "2360": ["IC設計", "電源管理"],
        "3711": ["封測", "先進封裝", "CoWoS"],
    }

    kw_map = stock_keyword_map or DEFAULT_MAP

    # 爆發/成長中的關鍵字
    hot_keywords = set(
        trend_df[trend_df["階段"].isin(["🔥 爆發", "⚡ 成長"])]["關鍵字"].tolist()
    )

    records = []
    for _, stock_row in smart_df.iterrows():
        code = str(stock_row.get("股票代號", ""))
        name = stock_row.get("股票名稱", "")

        related_kws = kw_map.get(code, [])
        matched_hot = [kw for kw in related_kws if kw in hot_keywords]

        if matched_hot:
            # 找對應的成長率
            matched_trends = trend_df[trend_df["關鍵字"].isin(matched_hot)]
            max_growth = matched_trends["成長率%"].max() if not matched_trends.empty else 0
            stages = matched_trends["階段"].tolist()

            records.append({
                "股票代號":    code,
                "股票名稱":    name,
                "持有ETF數":  stock_row.get("持有ETF數", 0),
                "訊號":       stock_row.get("訊號", ""),
                "相關熱詞":   " / ".join(matched_hot),
                "熱詞數":     len(matched_hot),
                "最高成長率%": round(max_growth, 1),
                "題材階段":   " / ".join(set(stages)),
                "綜合強度":   f"籌碼{'✅' if int(stock_row.get('持有ETF數',0)) >= 5 else '⚪'} "
                              f"題材{'✅' if matched_hot else '⚪'}",
            })

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records)
    result = result.sort_values(
        ["熱詞數", "最高成長率%", "持有ETF數"],
        ascending=[False, False, False]
    ).reset_index(drop=True)
    result.insert(0, "排名", range(1, len(result) + 1))

    log.info(f"新聞×籌碼交叉：{len(result)} 檔個股有新聞題材支撐")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("trend_analyzer 模組載入成功")
    log.info("需要至少 3 天的新聞歷史資料才能計算生命週期")
