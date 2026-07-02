"""
trends_fetcher.py v3
Google Trends 情緒指標 — 使用 pytrends（免費，不需要 API key）
"""
import pandas as pd
import time
import logging
import os
from datetime import datetime
from typing import Optional
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

# 追蹤主題
TRENDS_TOPICS = {
    "CoWoS":    "CoWoS",
    "AI伺服器":  "AI伺服器",
    "HBM":      "HBM記憶體",
    "液冷散熱":  "液冷散熱",
    "NVIDIA":   "NVIDIA",
    "Fed":      "聯準會",
    "台幣匯率":  "新台幣匯率",
    "除權息":   "除權息",
    "主動ETF":  "主動式ETF",
    "電動車":   "電動車",
}

def fetch_trends_pytrends(keyword: str, retries: int = 3) -> pd.DataFrame:
    """用 pytrends 抓取單一關鍵字的 Google Trends"""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.error("pytrends 未安裝，請執行 pip install pytrends")
        return pd.DataFrame()

    for attempt in range(retries):
        try:
            pytrends = TrendReq(hl="zh-TW", tz=480, timeout=(10, 25))
            pytrends.build_payload([keyword], cat=0, timeframe="now 7-d", geo="TW")
            df = pytrends.interest_over_time()
            if df.empty:
                log.warning(f"  {keyword}: 無資料")
                return pd.DataFrame()
            df = df.reset_index()
            df = df.rename(columns={"date": "日期", keyword: "搜尋量"})
            df["關鍵字"] = keyword
            df["日期"] = df["日期"].astype(str).str[:10]
            df = df[["日期", "搜尋量", "關鍵字"]]
            log.info(f"  {keyword}: {len(df)} 個時間點")
            return df
        except Exception as e:
            log.warning(f"  {keyword} 第{attempt+1}次失敗: {e}")
            if attempt < retries - 1:
                time.sleep(30)
    return pd.DataFrame()

def fetch_all_trends() -> pd.DataFrame:
    """批次抓取所有追蹤主題的 Google Trends"""
    all_dfs = []
    topics = list(TRENDS_TOPICS.keys())
    total = len(topics)

    for i, keyword in enumerate(topics, 1):
        log.info(f"  [{i}/{total}] 抓取: {keyword}")
        df = fetch_trends_pytrends(keyword)
        if not df.empty:
            all_dfs.append(df)
        # pytrends 需要等待避免被封鎖
        if i < total:
            time.sleep(15)

    if not all_dfs:
        log.warning("Google Trends 全部失敗")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    log.info(f"Google Trends 完成：{result['關鍵字'].nunique()} 個主題有資料")
    return result

def compute_trends_signal(trends_df: pd.DataFrame) -> pd.DataFrame:
    """計算散戶情緒訊號"""
    if trends_df.empty:
        return pd.DataFrame()

    records = []
    for keyword, group in trends_df.groupby("關鍵字"):
        group = group.sort_values("日期")
        recent = group.tail(7)["搜尋量"].astype(float)
        current = recent.iloc[-1] if len(recent) > 0 else 0
        avg_3d = recent.tail(3).mean() if len(recent) >= 3 else current
        avg_7d = recent.mean()
        peak = recent.max()
        growth = ((current - avg_7d) / avg_7d * 100) if avg_7d > 0 else 0
        relative_peak = (current / peak * 100) if peak > 0 else 0

        # 散戶情緒判斷（反向指標）
        if relative_peak < 30:
            sentiment = "散戶淡漠"
            signal = "最佳布局期"
        elif relative_peak < 60:
            sentiment = "散戶關注"
            signal = "觀察期"
        else:
            sentiment = "散戶追捧"
            signal = "謹慎期"

        records.append({
            "排名": 0,
            "主題": keyword,
            "散戶關注度": sentiment,
            "進場訊號": signal,
            "當前搜尋量": int(current),
            "近3日均": round(avg_3d, 1),
            "近7日均": round(avg_7d, 1),
            "搜尋成長%": round(growth, 1),
            "峰值": int(peak),
            "相對峰值%": round(relative_peak, 1),
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.sort_values("相對峰值%")
    df["排名"] = range(1, len(df) + 1)
    return df

def cross_news_and_trends(news_trend_df: pd.DataFrame, trends_signal_df: pd.DataFrame) -> pd.DataFrame:
    """新聞趨勢與散戶情緒交叉分析"""
    if news_trend_df.empty or trends_signal_df.empty:
        return pd.DataFrame()
    try:
        merged = pd.merge(
            news_trend_df,
            trends_signal_df[["主題","散戶關注度","進場訊號","相對峰值%"]],
            left_on="關鍵字", right_on="主題", how="left"
        )
        merged = merged.drop(columns=["主題"], errors="ignore")
        merged = merged.loc[:, ~merged.columns.duplicated()]
        return merged
    except Exception as e:
        log.warning(f"cross_news_and_trends 失敗: {e}")
        return pd.DataFrame()
