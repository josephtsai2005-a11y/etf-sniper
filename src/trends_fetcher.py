"""
trends_fetcher.py v3
Google Trends 情緒指標 — 使用 pytrends（免費，不需要 API key）
"""
import pandas as pd
import numpy as np
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
            # 2026-09-16修正：原本用timeframe="now 7-d"，這是Google Trends/pytrends的一個
            # 常見誤區——"now 7-d"雖然名字裡有7天，但回傳的資料粒度是「小時」（168個小時
            # 資料點），不是「天」。下面compute_trends_signal()裡的group.tail(7)、
            # 「近3日均」「近7日均」「相對峰值%」這些欄位名稱跟計算邏輯，從一開始設計就是假設
            # 資料粒度是「天」（要看「最近7天」的散戶關注度變化），結果實際上只看到「最近7小時」
            # 這種極短時間內的雜訊——冷門財經關鍵字在任何一個小時裡搜尋量本來就經常是0，
            # 難怪散點圖上的點幾乎全部擠在原點附近、看不出真正的日級別趨勢。改成
            # timeframe="today 1-m"（1個月，日粒度），下面.tail(7)就會正確取到「最近7天」
            # 的每日搜尋量，數字才有意義。
            pytrends.build_payload([keyword], cat=0, timeframe="today 1-m", geo="TW")
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

def fetch_all_trends(extra_topics: Optional[dict] = None) -> pd.DataFrame:
    """
    批次抓取所有追蹤主題的 Google Trends
    extra_topics: 額外動態主題（例如已核准的個股AI關鍵字），格式同 TRENDS_TOPICS
                  會跟固定的10個大盤主題合併一起抓，但受節流限制不會無限增加job時間
    """
    all_dfs = []
    combined_topics = dict(TRENDS_TOPICS)
    if extra_topics:
        combined_topics.update(extra_topics)

    topics = list(combined_topics.keys())
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
    log.info(f"Google Trends 完成：{result['關鍵字'].nunique()} 個主題有資料（含{len(extra_topics) if extra_topics else 0}個動態個股關鍵字）")
    return result

def compute_trends_signal(trends_df: pd.DataFrame) -> pd.DataFrame:
    """計算散戶情緒訊號（反向指標：散戶越冷，法人布局空間越大）。

    2026-09-16重新設計：原本只有3級分類（散戶淡漠/散戶關注/散戶追捧），但app.py
    「散戶關注度 vs 搜尋趨勢」散點圖的顏色/圖例設計的是5級（💤淡漠/🌱萌芽/⚡追進/
    🔥爆買/📉退場），兩邊名稱完全對不上，導致色彩映射永遠套用不到、圖例塌縮成幾乎
    只剩一種顏色，看起來毫無區分度。這裡改成跟圖上30%/60%兩條門檻線的視覺設計完全
    對齊，並新增「退場」這個原本沒有的第5類。
    """
    if trends_df.empty:
        return pd.DataFrame()

    records = []
    for keyword, group in trends_df.groupby("關鍵字"):
        group = group.sort_values("日期")
        recent = group.tail(7)["搜尋量"].astype(float)
        values = recent.values
        n = len(values)
        current = recent.iloc[-1] if n > 0 else 0
        avg_3d = recent.tail(3).mean() if n >= 3 else current
        avg_7d = recent.mean()
        peak = recent.max()
        growth = ((current - avg_7d) / avg_7d * 100) if avg_7d > 0 else 0
        relative_peak = (current / peak * 100) if peak > 0 else 0

        # 峰值出現在這7天視窗裡的第幾天（0=最早、n-1=最後一天），用來判斷「退場」
        peak_idx = int(np.argmax(values)) if n > 0 else 0
        days_since_peak = (n - 1) - peak_idx if n > 0 else 0

        # 散戶情緒判斷（反向指標）——5級，門檻30/45/60跟散點圖的兩條參考線（30/60）對齊，
        # 45是新增的中間級距（萌芽/追進的分界）。
        # 先擋一個邊界情況：peak本身就很低（<10，例如「0,1,0,2,1,0,1」這種幾乎沒人搜尋
        # 的雜訊）時，current/peak算出來的百分比很容易被小分母放大成誤導性的高比例
        # （例如peak=2、current=1，relative_peak=50%，看起來像「散戶追進」，但其實只是
        # 兩次搜尋之間的雜訊，完全不代表真的有人在關注）——這種規模下相對峰值%這個指標
        # 本身就不可靠，一律視為淡漠。
        if peak < 10:
            sentiment = "💤 散戶淡漠"
            signal = "最佳布局期"
        elif relative_peak < 30 and peak >= 20 and days_since_peak >= 1:
            # 「退場」跟「淡漠」都是目前搜尋量很低（<30%峰值），差別在於：退場代表這個
            # 關鍵字這7天內「曾經」有過明顯高點（peak>=20，避免把幾乎沒人搜尋的雜訊也
            # 誤判成「曾經熱門」）、但已經退燒至少1天——這通常代表題材動能正在流失，
            # 該注意的是「還在場內的部位要不要獲利了結」；淡漠則是本來就一直沒人關注，
            # 才是「散戶還沒發現、法人可以低調布局」的最佳進場期，兩者訊號意義不同。
            sentiment = "📉 散戶退場"
            signal = "謹慎，熱度可能已過"
        elif relative_peak < 30:
            sentiment = "💤 散戶淡漠"
            signal = "最佳布局期"
        elif relative_peak < 45:
            sentiment = "🌱 散戶萌芽"
            signal = "觀察期"
        elif relative_peak < 60:
            sentiment = "⚡ 散戶追進"
            signal = "注意，散戶陸續進場"
        else:
            sentiment = "🔥 散戶爆買"
            signal = "危險，散戶已大量湧入"

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

def classify_topic_position(news_stage: str, retail_relative_peak) -> str:
    """
    題材位置分類（2026-09-16新增）：新聞熱度階段 × 散戶搜尋熱度，交叉出「新聞熱但
    散戶還沒追」這種法人可能正在低調布局的時機。

        新聞熱 = 階段屬於「🔥 爆發」或「⚡ 成長」（trend_analyzer.py::
                 detect_lifecycle_stage()算出的生命週期階段；萌芽/衰退/沉寂/
                 資料不足都算「冷」）
        搜尋熱 = 相對峰值% >= 30（沿用「散戶關注度 vs 搜尋趨勢」散點圖同一條
                 「散戶開始注意」門檻線，兩張圖對「熱/冷」的判斷標準保持一致，
                 不會出現兩張圖各講各的話）

    交叉出四種題材位置：
        新聞熱 + 搜尋冷 → 🎯 法人期（新聞有動能但散戶還沒追，最適合觀察進場）
        新聞熱 + 搜尋熱 → ⚠️ 過熱期（新聞跟散戶都已經熱，追高風險增加）
        新聞冷 + 搜尋冷 → 💤 未發酵（題材還沒真正起來，先觀望）
        新聞冷 + 搜尋熱 → 📉 退燒中（新聞降溫但散戶還在追，注意動能減弱）
    """
    news_hot = news_stage in ("🔥 爆發", "⚡ 成長")
    try:
        retail_hot = float(retail_relative_peak) >= 30
    except (TypeError, ValueError):
        retail_hot = False

    if news_hot and not retail_hot:
        return "🎯 法人期"
    if news_hot and retail_hot:
        return "⚠️ 過熱期"
    if not news_hot and not retail_hot:
        return "💤 未發酵"
    return "📉 退燒中"


def cross_news_and_trends(news_trend_df: pd.DataFrame, trends_signal_df: pd.DataFrame) -> pd.DataFrame:
    """新聞趨勢與散戶情緒交叉分析。

    2026-09-16修正：原本這裡只做了「兩張表資料並排」的合併，從沒有真正算出app.py
    「題材位置分析（新聞×搜尋）」頁面要顯示的「題材位置」分類欄位——也就是說，這個
    功能標題寫著「新聞熱但搜尋冷＝法人期＝最佳進場時機」，但核心判斷邏輯從未實作，
    頁面上只看得到標題文字跟一片空白（`pos_avail`永遠算不出任何欄位可以顯示）。
    這裡補上真正的分類邏輯（見classify_topic_position()），並把app.py「題材位置
    分析」表格需要的「主題」「新聞篇數」「當前搜尋量」欄位都對齊好、加上「排名」。
    """
    if news_trend_df.empty or trends_signal_df.empty:
        return pd.DataFrame()
    try:
        merged = pd.merge(
            news_trend_df,
            trends_signal_df[["主題","散戶關注度","進場訊號","當前搜尋量","相對峰值%"]],
            left_on="關鍵字", right_on="主題", how="left"
        )
        merged = merged.drop(columns=["主題","排名"], errors="ignore")
        merged = merged.rename(columns={"關鍵字": "主題", "今日篇數": "新聞篇數"})
        merged = merged.loc[:, ~merged.columns.duplicated()]

        merged["題材位置"] = merged.apply(
            lambda r: classify_topic_position(r.get("階段", ""), r.get("相對峰值%")),
            axis=1,
        )

        # 排序：法人期（最值得注意）> 過熱期 > 退燒中 > 未發酵，同分類內依新聞成長率%排序
        position_order = {"🎯 法人期": 0, "⚠️ 過熱期": 1, "📉 退燒中": 2, "💤 未發酵": 3}
        merged["_題材位置排序"] = merged["題材位置"].map(position_order).fillna(9)
        sort_cols = ["_題材位置排序"]
        ascending = [True]
        if "成長率%" in merged.columns:
            sort_cols.append("成長率%")
            ascending.append(False)
        merged = merged.sort_values(sort_cols, ascending=ascending).drop(columns=["_題材位置排序"])
        merged = merged.reset_index(drop=True)
        merged.insert(0, "排名", range(1, len(merged) + 1))

        return merged
    except Exception as e:
        log.warning(f"cross_news_and_trends 失敗: {e}")
        return pd.DataFrame()