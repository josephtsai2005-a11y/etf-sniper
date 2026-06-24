"""
news_fetcher.py v3
財經新聞抓取 — 聚焦五個核心方向：
1. 供應鏈/產業訊號
2. 法說會/財報展望
3. Fed/總體政策
4. 美股盤後重點
5. Google Trends（情緒指標）
"""
import requests
import pandas as pd
import feedparser
import time
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

# ── RSS 新聞來源（分層）────────────────────────────────────────
RSS_SOURCES = {
    # ── 層級一：核心（已確認可用）──
    "Yahoo財經":       ("https://tw.news.yahoo.com/rss/finance",         1),
    "Yahoo財經_股市":  ("https://tw.stock.yahoo.com/rss",                1),
    "鉅亨_台股RSS":    ("https://news.cnyes.com/rss/tw_stock",           1),
    "鉅亨_科技RSS":    ("https://news.cnyes.com/rss/tech",               1),

    # ── 層級二：輔助──
    "鉅亨_美股RSS":    ("https://news.cnyes.com/rss/us_stock",           2),
    "鉅亨_頭條RSS":    ("https://news.cnyes.com/rss/headline",           2),
    "鉅亨_基金RSS":    ("https://news.cnyes.com/rss/fund",               2),

    # ── 層級三：情緒──
    "Yahoo財經_國際":  ("https://tw.news.yahoo.com/rss/world",           3),
    "Yahoo科技":       ("https://tw.news.yahoo.com/rss/tech",            3),
}

# ══════════════════════════════════════════════════════════════
# 核心關鍵字庫（五個方向）
# ══════════════════════════════════════════════════════════════
CORE_KEYWORDS = {

    # ── 方向一：供應鏈 / 產業訊號 ──────────────────────────────
    # AI 基礎建設
    "AI伺服器":      ["AI伺服器", "AI server", "AI機架", "GPU伺服器"],
    "CoWoS":         ["CoWoS", "晶圓級封裝", "先進封裝", "WoW"],
    "HBM":           ["HBM", "HBM3", "HBM4", "高頻寬記憶體"],
    "GB200":         ["GB200", "GB300", "Blackwell", "Rubin"],
    "液冷散熱":      ["液冷", "液態冷卻", "浸沒式冷卻", "冷板"],

    # 半導體製程
    "先進製程":      ["2奈米", "2nm", "3奈米", "A16", "N2", "先進製程"],
    "半導體設備":    ["ASML", "科林", "應材", "科睿", "曝光機"],
    "矽光子":        ["矽光子", "silicon photonics", "光連接", "光模組"],
    "CoWoS產能":     ["CoWoS產能", "封裝產能", "先進封裝產能"],

    # 網通
    "800G":          ["800G", "1.6T", "高速乙太網", "InfiniBand"],
    "400G":          ["400G", "高速網路", "交換器", "switch"],

    # 電源
    "電源管理":      ["電源管理", "Power IC", "PMIC", "電壓調節"],
    "儲能":          ["儲能", "電池", "磷酸鐵鋰", "ESS"],

    # 車用
    "電動車":        ["電動車", "EV", "Tesla", "BYD", "車用電子", "電動化"],
    "自駕車":        ["自駕", "ADAS", "FSD", "自動駕駛", "L3", "L4"],

    # ── 方向二：法說會 / 財報 ───────────────────────────────────
    "台積電":        ["台積電", "TSMC", "台積法說", "TSMC法說"],
    "法說會":        ["法說會", "法人說明會", "earnings call", "業績發表"],
    "財報":          ["財報", "季報", "年報", "EPS", "獲利創新高", "獲利衰退"],
    "展望":          ["展望", "下半年展望", "全年展望", "正向看法", "調高目標"],
    "調升評等":      ["調升", "Buy", "強力買進", "目標價調高", "上調評等"],
    "調降評等":      ["調降", "Sell", "賣出", "目標價調降", "下調評等"],

    # ── 方向三：Fed / 總體政策 ──────────────────────────────────
    "Fed":           ["Fed", "聯準會", "FOMC", "鮑爾", "Powell"],
    "升降息":        ["升息", "降息", "利率決議", "暫停升息", "寬鬆"],
    "通膨":          ["通膨", "CPI", "PCE", "物價", "通貨膨脹"],
    "美中科技戰":    ["晶片禁令", "出口管制", "實體清單", "制裁", "脫鉤"],
    "美中關係":      ["美中", "中美", "關稅", "貿易戰", "地緣政治"],
    "台幣匯率":      ["台幣", "新台幣", "匯率", "升值", "貶值", "外匯"],

    # ── 方向四：美股盤後重點 ────────────────────────────────────
    "NVIDIA":        ["NVIDIA", "輝達", "英偉達", "黃仁勳"],
    "Apple":         ["Apple", "蘋果", "iPhone", "Vision Pro"],
    "Microsoft":     ["Microsoft", "微軟", "Azure", "Copilot"],
    "Amazon":        ["Amazon", "AWS", "亞馬遜"],
    "Google":        ["Google", "Alphabet", "Gemini", "TPU"],
    "Meta":          ["Meta", "Facebook", "Llama"],
    "那斯達克":      ["那斯達克", "Nasdaq", "費半", "SOX", "科技股"],
    "標普500":       ["標普", "S&P500", "道瓊", "VIX", "恐慌指數"],

    # ── 方向五：台股特有情緒指標 ────────────────────────────────
    "外資動向":      ["外資買超", "外資賣超", "外資連買", "外資連賣"],
    "投信動向":      ["投信買超", "投信賣超", "投信連買"],
    "除權息":        ["除權", "除息", "配息", "殖利率", "填權"],
    "融資融券":      ["融資", "融券", "借券", "放空"],
    "主動式ETF":     ["主動式ETF", "主動ETF", "00981", "00403"],
}

# ── 個股關鍵字對應表 ──────────────────────────────────────────
STOCK_KEYWORD_MAP = {
    # AI 伺服器供應鏈
    "2330": ["台積電", "先進製程", "CoWoS", "CoWoS產能", "NVIDIA", "GB200", "HBM", "Apple"],
    "2454": ["AI伺服器", "NVIDIA", "GB200", "先進製程", "那斯達克"],
    "2383": ["CoWoS", "CoWoS產能", "先進製程", "矽光子"],
    "6223": ["CoWoS", "CoWoS產能", "半導體設備"],
    "3037": ["CoWoS", "先進封裝", "PCB"],
    "3711": ["CoWoS", "先進封裝", "封測"],

    # 散熱
    "3017": ["液冷散熱", "AI伺服器", "散熱"],
    "6274": ["液冷散熱", "AI伺服器", "散熱"],

    # 網通
    "2345": ["800G", "400G", "AI伺服器", "網通"],
    "4977": ["800G", "400G", "光模組", "矽光子"],

    # 電源
    "2308": ["電源管理", "AI伺服器", "電動車", "台達電"],
    "2360": ["電源管理", "IC設計"],

    # 記憶體
    "4863": ["HBM", "記憶體", "DRAM"],

    # 被動元件
    "2327": ["電動車", "AI伺服器", "被動元件"],
    "2368": ["被動元件", "MLCC", "電動車"],

    # 車用
    "6269": ["電動車", "自駕車", "車用電子"],
    "2059": ["電動車", "自駕車", "鉸鏈"],

    # 金融/外資影響
    "2882": ["外資動向", "Fed", "升降息"],
    "2881": ["外資動向", "Fed", "升降息"],
    "2891": ["外資動向", "Fed", "台幣匯率"],

    # 其他高持有ETF個股
    "2303": ["台積電", "先進製程", "外資動向"],
    "2344": ["AI伺服器", "網通", "電源管理"],
    "2408": ["半導體設備", "先進製程"],
    "5274": ["液冷散熱", "AI伺服器"],
    "2059": ["電動車", "自駕車"],
}


def fetch_rss(source_name: str, url: str, priority: int = 1,
              hours_back: int = 26) -> List[Dict]:
    """抓取單一 RSS 來源"""
    articles = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ETFSniper/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        feed = feedparser.parse(resp.content)

        cutoff = datetime.now(TW_TZ) - timedelta(hours=hours_back)

        for entry in feed.entries[:50]:  # 最多取 50 篇
            pub_time = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import calendar
                ts = calendar.timegm(entry.published_parsed)
                pub_time = datetime.fromtimestamp(ts, TW_TZ)

            if pub_time and pub_time < cutoff:
                continue

            title   = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            # 去除 HTML 標籤
            summary = re.sub(r"<[^>]+>", "", summary)[:300]
            link    = entry.get("link", "")

            if not title or len(title) < 5:
                continue

            articles.append({
                "來源":      source_name,
                "優先級":    priority,
                "標題":      title,
                "摘要":      summary,
                "連結":      link,
                "發布時間":  pub_time.strftime("%Y-%m-%d %H:%M") if pub_time else "",
                "抓取日期":  datetime.now(TW_TZ).strftime("%Y%m%d"),
                "抓取時間":  datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M"),
            })

        log.info(f"  {source_name} (優先級{priority}): {len(articles)} 篇")

    except Exception as e:
        log.debug(f"  {source_name} 失敗: {e}")

    return articles


def fetch_cnyes_api(category: str, source_name: str, priority: int = 1,
                    limit: int = 30, hours_back: int = 26) -> List[Dict]:
    """
    鉅亨網 JSON API 抓取
    category: tw_stock / us_stock / tech / headline / fund
    """
    url = f"https://api.cnyes.com/media/api/v1/newslist/category/{category}"
    params = {"limit": limit}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://news.cnyes.com/",
    }
    articles = []
    cutoff = datetime.now(TW_TZ) - timedelta(hours=hours_back)

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", {}).get("data", [])

        for item in items:
            # 發布時間（Unix timestamp）
            pub_ts = item.get("publishAt") or item.get("updated_at")
            pub_time = None
            if pub_ts:
                pub_time = datetime.fromtimestamp(int(pub_ts), TW_TZ)
                if pub_time < cutoff:
                    continue

            title   = item.get("title", "").strip()
            summary = re.sub(r"<[^>]+>", "", item.get("summary", "") or "")[:300]
            link    = f"https://news.cnyes.com/news/id/{item.get('newsId', '')}"

            if not title or len(title) < 5:
                continue

            articles.append({
                "來源":     source_name,
                "優先級":   priority,
                "標題":     title,
                "摘要":     summary,
                "連結":     link,
                "發布時間": pub_time.strftime("%Y-%m-%d %H:%M") if pub_time else "",
                "抓取日期": datetime.now(TW_TZ).strftime("%Y%m%d"),
                "抓取時間": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M"),
            })

        log.info(f"  {source_name} (鉅亨API): {len(articles)} 篇")

    except Exception as e:
        log.error(f"  {source_name} 鉅亨API失敗: {e}")

    return articles


def fetch_all_news(hours_back: int = 26, max_priority: int = 3) -> pd.DataFrame:
    """批次抓取所有新聞來源"""
    all_articles = []

    # RSS 來源
    for source_name, (url, priority) in RSS_SOURCES.items():
        if priority > max_priority:
            continue
        articles = fetch_rss(source_name, url, priority, hours_back)
        all_articles.extend(articles)
        time.sleep(0.5)

    # 鉅亨網 JSON API（更穩定）
    cnyes_categories = [
        ("tw_stock",  "鉅亨_台股",   1),
        ("us_stock",  "鉅亨_美股",   2),
        ("tech",      "鉅亨_科技",   1),
        ("headline",  "鉅亨_頭條",   2),
    ]
    for cat, name, pri in cnyes_categories:
        if pri > max_priority:
            continue
        articles = fetch_cnyes_api(cat, name, pri, limit=30, hours_back=hours_back)
        all_articles.extend(articles)
        time.sleep(0.8)

    if not all_articles:
        log.warning("所有來源均無新聞")
        return pd.DataFrame()

    df = pd.DataFrame(all_articles)
    df = df.drop_duplicates(subset=["標題"])
    df = df.sort_values(["優先級", "發布時間"], ascending=[True, False])
    log.info(f"新聞抓取完成：共 {len(df)} 篇（去重後）")
    return df


def extract_keywords(text: str) -> List[str]:
    """從文字中提取命中的核心關鍵字"""
    matched = []
    text_lower = text.lower()
    for keyword, patterns in CORE_KEYWORDS.items():
        for pattern in patterns:
            if pattern.lower() in text_lower:
                matched.append(keyword)
                break
    return list(set(matched))


def tag_articles(df: pd.DataFrame) -> pd.DataFrame:
    """對每篇新聞標記命中的關鍵字"""
    if df.empty:
        return df
    df = df.copy()
    full_text = df["標題"] + " " + df.get("摘要", pd.Series("", index=df.index)).fillna("")
    df["命中關鍵字"] = full_text.apply(lambda t: ",".join(extract_keywords(t)))
    df["關鍵字數"]   = df["命中關鍵字"].apply(lambda x: len([k for k in x.split(",") if k]) if x else 0)

    # 方向分類
    direction_map = {
        "供應鏈":   ["AI伺服器","CoWoS","HBM","GB200","液冷散熱","先進製程","半導體設備","矽光子","800G","400G","電源管理","電動車","自駕車"],
        "法說財報": ["台積電","法說會","財報","展望","調升評等","調降評等"],
        "總體政策": ["Fed","升降息","通膨","美中科技戰","美中關係","台幣匯率"],
        "美股動態": ["NVIDIA","Apple","Microsoft","Amazon","Google","Meta","那斯達克","標普500"],
        "台股情緒": ["外資動向","投信動向","除權息","融資融券","主動式ETF"],
    }
    def get_direction(keywords_str):
        kws = set(keywords_str.split(","))
        matched_dirs = []
        for dir_name, dir_kws in direction_map.items():
            if any(k in kws for k in dir_kws):
                matched_dirs.append(dir_name)
        return "/".join(matched_dirs) if matched_dirs else ""

    df["新聞方向"] = df["命中關鍵字"].apply(get_direction)
    return df


def auto_extract_hot_words(df: pd.DataFrame, top_n: int = 20) -> List[str]:
    """自動提取今日高頻詞彙"""
    if df.empty or "標題" not in df.columns:
        return []

    all_text = " ".join(df["標題"].tolist())
    stop_words = {
        "今日","明日","昨日","台灣","美國","中國","市場","公司",
        "分析","預期","報告","數據","影響","關注","表示","指出",
        "認為","可能","如果","因此","由於","以上","以下","相關",
        "目前","已經","將會","仍然","繼續","持續","根據","顯示"
    }
    word_freq = {}
    for i in range(len(all_text)-1):
        for length in [2, 3, 4]:
            if i + length > len(all_text):
                break
            word = all_text[i:i+length]
            if re.match(r'^[\u4e00-\u9fff]{2,}$', word) and word not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

    # 排除已在核心庫的詞
    existing = set()
    for patterns in CORE_KEYWORDS.values():
        existing.update(p.lower() for p in patterns)

    hot = [
        w for w, cnt in sorted(word_freq.items(), key=lambda x: -x[1])
        if cnt >= 3 and w.lower() not in existing and len(w) >= 2
    ][:top_n]
    return hot


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log.info("=== 測試新聞抓取 v3 ===")

    df = fetch_all_news(hours_back=26)
    if not df.empty:
        df = tag_articles(df)

        print(f"\n共 {len(df)} 篇新聞")
        print(f"有命中關鍵字：{(df['關鍵字數']>0).sum()} 篇")

        print("\n=== 各方向新聞數 ===")
        for direction in ["供應鏈","法說財報","總體政策","美股動態","台股情緒"]:
            count = df["新聞方向"].str.contains(direction, na=False).sum()
            print(f"  {direction}：{count} 篇")

        print("\n=== 命中關鍵字的新聞（前15篇）===")
        tagged = df[df["關鍵字數"] > 0][["來源","標題","命中關鍵字","新聞方向"]].head(15)
        print(tagged.to_string(index=False))

        hot = auto_extract_hot_words(df)
        print(f"\n=== 自動偵測熱詞 ===")
        print(hot)
    else:
        print("無新聞資料")
