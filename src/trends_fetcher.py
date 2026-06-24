"""
trends_fetcher.py v2
Google Trends 情緒指標 — 使用 SerpAPI（穩定，免費100次/月）
申請：https://serpapi.com/users/sign_up
"""
import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

# SerpAPI Key（從環境變數讀取）
SERP_API_KEY = os.environ.get("SERPAPI_KEY", "")

# ── 追蹤主題 ─────────────────────────────────────────────────
TRENDS_TOPICS = {
    "CoWoS":    "CoWoS 先進封裝",
    "AI伺服器":  "AI伺服器",
    "HBM":      "HBM記憶體",
    "液冷散熱":  "液冷散熱",
    "NVIDIA":   "NVIDIA 輝達",
    "Fed":      "聯準會 降息",
    "台幣匯率":  "新台幣 匯率",
    "除權息":   "除權息 存股",
    "主動ETF":  "主動式ETF",
    "電動車":   "電動車 台股",
}


def fetch_trends_serpapi(keyword: str, api_key: str = "") -> pd.DataFrame:
    """
    用 SerpAPI 抓取單一關鍵字的 Google Trends
    """
    key = api_key or SERP_API_KEY
    if not key:
        log.warning("缺少 SERPAPI_KEY，跳過 Google Trends")
        return pd.DataFrame()

    url = "https://serpapi.com/search"
    params = {
        "engine":       "google_trends",
        "q":            keyword,
        "data_type":    "TIMESERIES",
        "date":         "now 7-d",
        "geo":          "TW",
        "hl":           "zh-TW",
        "api_key":      key,
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        timeline = data.get("interest_over_time", {}).get("timeline_data", [])
        if not timeline:
            return pd.DataFrame()

        records = []
        for point in timeline:
            dt_str = point.get("date", "")
            values = point.get("values", [])
            if values:
                val = int(values[0].get("extracted_value", 0))
                records.append({"日期": dt_str[:10], "搜尋量": val, "關鍵字": keyword})

        df = pd.DataFrame(records)
        log.info(f"  {keyword}: {len(df)} 個時間點")
        return df

    except Exception as e:
        log.debug(f"  {keyword} SerpAPI 失敗: {e}")
        return pd.DataFrame()


def fetch_all_trends(api_key: str = "") -> pd.DataFrame:
    """
    批次抓取所有追蹤主題的 Google Trends
    """
    key = api_key or SERP_API_KEY
    if not key:
        log.warning("缺少 SERPAPI_KEY，Google Trends 跳過")
        return pd.DataFrame()

    log.info(f"抓取 Google Trends：{len(TRENDS_TOPICS)} 個主題...")
    all_frames = []

    for topic, keyword in TRENDS_TOPICS.items():
        df = fetch_trends_serpapi(keyword, key)
        if not df.empty:
            df["主題"] = topic
            all_frames.append(df)
        time.sleep(1.0)

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    log.info(f"Google Trends 完成：{combined['主題'].nunique()} 個主題有資料")
    return combined


def compute_trends_signal(trends_df: pd.DataFrame) -> pd.DataFrame:
    """
    計算每個主題的散戶關注度訊號
    核心邏輯：
    搜尋量低 = 散戶還不知道 = 法人布局期 = 好進場時機
    搜尋量高 = 散戶瘋狂追進 = 法人出貨期 = 危險
    """
    if trends_df.empty:
        return pd.DataFrame()

    records = []
    for topic in trends_df["主題"].unique():
        sub = trends_df[trends_df["主題"] == topic].sort_values("日期")
        values = sub["搜尋量"].fillna(0).values

        if len(values) == 0:
            continue

        n       = len(values)
        latest  = int(values[-1])
        recent3 = round(float(values[-3:].mean()), 1) if n >= 3 else float(latest)
        recent7 = round(float(values[-7:].mean()), 1) if n >= 7 else recent3
        peak    = int(values.max())
        growth  = round((recent3 - recent7) / recent7 * 100, 1) if recent7 > 0 else 0

        # 散戶關注度判斷
        relative = latest / peak if peak > 0 else 0
        if relative >= 0.8:
            retail_stage = "🔥 散戶爆買"
            signal = "⚠️ 追高風險高"
        elif growth > 50:
            retail_stage = "⚡ 散戶追進"
            signal = "📊 觀察法人是否仍在"
        elif growth > 0:
            retail_stage = "🌱 散戶萌芽"
            signal = "✅ 法人期可進場"
        elif relative < 0.2:
            retail_stage = "💤 散戶淡漠"
            signal = "✅ 最佳布局期"
        else:
            retail_stage = "📉 散戶退場"
            signal = "🔄 等待下一輪"

        records.append({
            "主題":       topic,
            "散戶關注度": retail_stage,
            "進場訊號":   signal,
            "當前搜尋量": latest,
            "近3日均":    recent3,
            "近7日均":    recent7,
            "搜尋成長%":  growth,
            "峰值":       peak,
            "相對峰值%":  round(relative * 100, 1),
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    order = {"💤 散戶淡漠":0,"🌱 散戶萌芽":1,"⚡ 散戶追進":2,"🔥 散戶爆買":3,"📉 散戶退場":4}
    df["排序"] = df["散戶關注度"].map(order).fillna(5)
    df = df.sort_values("排序").drop("排序", axis=1).reset_index(drop=True)
    if "排名" not in df.columns:
        df.insert(0, "排名", range(1, len(df)+1))
    return df


def cross_news_and_trends(news_trend_df: pd.DataFrame, trends_signal_df: pd.DataFrame) -> pd.DataFrame:
    """
    新聞熱度 × Google Trends 交叉分析
    找出最佳題材位置：新聞熱但搜尋冷 = 法人期
    """
    if news_trend_df.empty or trends_signal_df.empty:
        return pd.DataFrame()

    news = news_trend_df.copy()
    gtr  = trends_signal_df.copy()

    if "關鍵字" in news.columns:
        news = news.rename(columns={"關鍵字": "主題"})

    merged = news.merge(
        gtr[["主題","散戶關注度","進場訊號","當前搜尋量","相對峰值%"]],
        on="主題", how="outer"
    )

    merged["新聞篇數"]   = pd.to_numeric(merged.get("今日篇數", 0), errors="coerce").fillna(0)
    merged["當前搜尋量"] = pd.to_numeric(merged.get("當前搜尋量", 0), errors="coerce").fillna(0)

    def position(row):
        news_hot   = float(row.get("新聞篇數", 0)) > 3
        search_low = float(row.get("當前搜尋量", 0)) < 30
        search_hot = float(row.get("當前搜尋量", 0)) >= 60

        if news_hot and search_low:
            return "🎯 最佳進場（法人期）"
        elif news_hot and not search_hot:
            return "⚡ 成長期（持續觀察）"
        elif news_hot and search_hot:
            return "⚠️ 爆發期（謹慎追高）"
        elif not news_hot and search_hot:
            return "📉 衰退期（法人出貨）"
        else:
            return "💤 蟄伏期（等待布局）"

    merged["題材位置"] = merged.apply(position, axis=1)

    order = {"🎯 最佳進場（法人期）":0,"⚡ 成長期（持續觀察）":1,
             "⚠️ 爆發期（謹慎追高）":2,"📉 衰退期（法人出貨）":3,"💤 蟄伏期（等待布局）":4}
    merged["排序"] = merged["題材位置"].map(order).fillna(5)
    merged = merged.sort_values("排序").drop("排序", axis=1).reset_index(drop=True)
    if "排名" in merged.columns:
        merged = merged.drop(columns=["排名"])
    merged.insert(0, "排名", range(1, len(merged)+1))

    return merged


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        print("請設定環境變數 SERPAPI_KEY")
        print("申請免費 Key：https://serpapi.com/users/sign_up")
        exit(1)

    log.info("=== 測試 Google Trends (SerpAPI) ===")
    df = fetch_trends_serpapi("CoWoS", api_key)
    if not df.empty:
        print(f"成功！{len(df)} 個時間點")
        print(df.to_string(index=False))
    else:
        print("無資料")
