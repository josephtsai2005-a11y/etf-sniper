"""
us_market_fetcher.py
美股市場資料抓取 - 經濟面、市場面、產業面
來源：Alpha Vantage (免費)
"""
import os
import requests
import pandas as pd
import logging
import time
from datetime import datetime, timedelta
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

# 完整市場追蹤清單
MARKET_TARGETS = {
    "大盤指數": {
        "SPY":  "S&P500",
        "QQQ":  "Nasdaq科技",
        "DIA":  "道瓊工業",
        "IWM":  "羅素2000小型股",
        "VIX":  "恐慌指數",
    },
    "經濟指標": {
        "TLT":  "20年美債(利率方向)",
        "GLD":  "黃金(避險情緒)",
        "UUP":  "美元指數",
        "USO":  "原油",
    },
    "產業ETF": {
        "SOXX": "費城半導體(影響台積電)",
        "XLK":  "科技股",
        "XLE":  "能源股",
        "XLF":  "金融股",
    },
    "台股連動": {
        "NVDA": "NVIDIA(AI供應鏈)",
        "TSM":  "台積電ADR",
    },
}

def fetch_quote(symbol: str) -> dict:
    """抓取單一報價"""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol,
        "apikey": ALPHA_VANTAGE_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        quote = data.get("Global Quote", {})
        if not quote:
            return {}
        pct = quote.get("10. change percent", "0%").replace("%","").strip()
        return {
            "symbol":    symbol,
            "price":     float(quote.get("05. price", 0)),
            "change":    float(quote.get("09. change", 0)),
            "change_pct": float(pct) if pct else 0,
            "volume":    quote.get("06. volume", 0),
            "date":      quote.get("07. latest trading day", ""),
        }
    except Exception as e:
        log.error(f"{symbol} 失敗: {e}")
        return {}

# yfinance的代號跟Alpha Vantage不完全一樣的少數例外（指數類通常要加^前綴）
YFINANCE_SYMBOL_OVERRIDES = {
    "VIX": "^VIX",
}


def fetch_quote_yfinance(symbol: str) -> dict:
    """
    2026-11-19新增：yfinance備援查詢——只有在Alpha Vantage抓到的資料被判定為
    過期（資料日期不等於預期交易日）時才會呼叫這個函式，重查那一檔。

    yfinance是非官方套件（爬Yahoo Finance網頁/內部API），Yahoo隨時可能改版讓它
    失效，所以只當備援、不是主力：Alpha Vantage運作正常時完全不會用到這個函式，
    失敗時安全退回使用Alpha Vantage原本抓到的（即使過期的）資料，搭配既有的
    新鮮度警告標註，不會讓整個流程因為備援失敗而掛掉。
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning(f"{symbol} yfinance備援失敗：套件未安裝")
        return {}

    yf_symbol = YFINANCE_SYMBOL_OVERRIDES.get(symbol, symbol)
    try:
        hist = yf.Ticker(yf_symbol).history(period="5d")
        if hist is None or hist.empty:
            return {}
        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else None
        price = float(last["Close"])
        change_pct = 0.0
        change = 0.0
        if prev is not None and float(prev["Close"]) != 0:
            change = price - float(prev["Close"])
            change_pct = change / float(prev["Close"]) * 100
        return {
            "symbol": symbol,
            "price": price,
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
            "volume": int(last.get("Volume", 0) or 0),
            "date": hist.index[-1].strftime("%Y-%m-%d"),
        }
    except Exception as e:
        log.warning(f"{symbol} yfinance備援查詢失敗: {e}")
        return {}

def _expected_us_trading_date(now_tw: datetime = None) -> str:
    """
    推算「這次查詢時，預期應該拿到的美股最新收盤交易日」（美東日期，格式YYYY-MM-DD）。

    2026-11-18新增（詳見claude/todo_20261113_us_market_direction_mismatch.md根因
    確認）：這個系統固定在台北時間約05:00~05:10查詢美股資料，對應美東時間剛好是
    前一天下午4點左右（剛收盤2分鐘）。所以預期的交易日＝台北「今天」往回推一天，
    再往回跳過週末（美股週六週日休市）。

    ⚠️ 已知限制：這裡只處理週末，沒有內建完整的美股休市日曆（感恩節、耶誕節等）。
    遇到美股國定假日時，這裡算出來的「預期日期」會比實際最新交易日早算一天，導致
    下面的新鮮度檢查多出一次「資料疑似過期」的假警報——這是已知、可接受的取捨：
    寧可偶爾多一次不必要的警示，也不要完全不驗證、悄悄用到真正過期的資料。
    """
    if now_tw is None:
        now_tw = datetime.now(TW_TZ)
    d = now_tw.date() - timedelta(days=1)
    while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")

def fetch_all_us_market() -> dict:
    """抓取所有市場資料（免費版每分鐘5次）

    2026-11-18新增、2026-11-19修正（詳見claude/todo_20261113_us_market_direction_
    mismatch.md根因確認）：Alpha Vantage免費版GLOBAL_QUOTE在美股剛收盤查詢時，
    常常還沒更新到當天收盤，回傳前一個交易日的舊資料。這裡逐檔檢查每個symbol的
    資料日期是否等於預期交易日（_expected_us_trading_date()），不是整批用set判斷
    ——2026-11-19實測發現15檔裡只有1檔（台積電ADR）過期，用set判斷會被其餘14檔
    正常的資料「稀釋」掉，誤判整批新鮮、警告完全不會觸發，所以改成逐檔各自判斷。
    偵測到過期時，先嘗試用yfinance重查那一檔（fetch_quote_yfinance()），成功且
    日期吻合就改用新資料；備援也失敗的話，維持使用過期的Alpha Vantage資料，並
    記進results["_freshness"]["stale_items"]，供format_us_market_for_ai()在文字
    裡明確標註警告，不讓AI把過期資料誤當成最新收盤分析。
    """
    results = {}
    total = sum(len(v) for v in MARKET_TARGETS.values())
    count = 0
    expected_date = _expected_us_trading_date()
    stale_items = []  # [(name, symbol, actual_date), ...]：最終仍過期（含備援也失敗）的項目

    for category, symbols in MARKET_TARGETS.items():
        results[category] = []
        for symbol, name in symbols.items():
            count += 1
            log.info(f"  [{count}/{total}] 抓取 {symbol} ({name})...")
            data = fetch_quote(symbol)
            if data:
                data["name"] = name
                actual_date = data.get("date", "")
                data["is_stale"] = bool(actual_date) and actual_date != expected_date

                if data["is_stale"]:
                    log.info(f"    {name} 資料過期（{actual_date}），嘗試yfinance備援重查...")
                    fallback = fetch_quote_yfinance(symbol)
                    if fallback and fallback.get("date") == expected_date:
                        fallback["name"] = name
                        fallback["is_stale"] = False
                        fallback["data_source"] = "yfinance備援"
                        data = fallback
                        log.info(f"    {name} 備援成功，改用yfinance資料（{fallback['date']}）")
                    else:
                        stale_items.append((name, symbol, actual_date))
                        log.warning(f"    {name} yfinance備援也沒拿到最新資料，維持Alpha Vantage過期資料並標註警告")

                results[category].append(data)
                arrow = "▲" if data["change_pct"] > 0 else "▼" if data["change_pct"] < 0 else "—"
                stale_mark = "  ⚠️過期" if data.get("is_stale") else ""
                src_mark = f"  [來源:{data['data_source']}]" if data.get("data_source") else ""
                log.info(f"    {name}: {data['price']} {arrow}{abs(data['change_pct']):.2f}% （資料日期: {data.get('date','')}）{stale_mark}{src_mark}")
            time.sleep(13)  # 每分鐘5次限制，保守設13秒

    results["_freshness"] = {
        "expected_date": expected_date,
        "stale_items": stale_items,
    }
    if stale_items:
        detail = "、".join(f"{name}({symbol}):{d}" for name, symbol, d in stale_items)
        log.warning(f"⚠️ 美股資料新鮮度異常：預期交易日 {expected_date}，以下 {len(stale_items)} 檔過期（yfinance備援也失敗）: {detail}")

    return results


def format_us_market_for_ai(us_data: dict) -> str:
    """格式化給 AI 分析用"""
    if not us_data:
        return "（無美股資料）"

    freshness = us_data.get("_freshness", {})
    stale_items = freshness.get("stale_items", [])
    lines = []
    if stale_items:
        stale_desc = "、".join(
            f"{name}（實際資料日期{d}，不是{freshness.get('expected_date','')}）"
            for name, symbol, d in stale_items
        )
        lines.extend([
            f"⚠️ 資料新鮮度警告：以下項目不是最新收盤，是前一交易日的舊資料：{stale_desc}。",
            "分析時請針對這幾項明確標註「此為前一交易日數據，非最新收盤」，不要當成當日確定",
            "方向直接下結論或據此推薦操作；下面清單裡每一項後面若有「⚠️非最新收盤」標記，",
            "就是指這一項；沒有標記的項目資料日期正常，可視為最新收盤。",
            "",
        ])

    for category, items in us_data.items():
        if category == "_freshness":
            continue
        if not items:
            continue
        lines.append(f"【{category}】")
        for item in items:
            name = item.get("name", item.get("symbol",""))
            price = item.get("price", 0)
            pct = item.get("change_pct", 0)
            arrow = "▲" if pct > 0 else "▼" if pct < 0 else "—"
            sentiment = ""
            # 自動加入市場解讀
            sym = item.get("symbol","")
            if sym == "VIX":
                if price > 30:
                    sentiment = "⚠️ 極度恐慌"
                elif price > 20:
                    sentiment = "😰 市場緊張"
                else:
                    sentiment = "😊 市場平穩"
            elif sym == "TLT":
                if pct > 0.5:
                    sentiment = "→ 市場預期降息"
                elif pct < -0.5:
                    sentiment = "→ 利率上升壓力"
            elif sym == "GLD":
                if pct > 0.5:
                    sentiment = "→ 避險需求上升"
            elif sym == "UUP":
                if pct > 0.3:
                    sentiment = "→ 美元強勢，新興市場承壓"
                elif pct < -0.3:
                    sentiment = "→ 美元走弱，有利台幣"
            stale_mark = " ⚠️非最新收盤" if item.get("is_stale") else ""
            lines.append(f"  {name}: {price:.2f} {arrow}{abs(pct):.2f}% {sentiment}{stale_mark}")
        lines.append("")

    return "\n".join(lines)


def get_market_sentiment_summary(us_data: dict) -> str:
    """產生市場情緒快速摘要"""
    if not us_data:
        return "無法取得美股資料"

    summary = []

    # 大盤方向
    spy = next((i for i in us_data.get("大盤指數",[]) if i["symbol"]=="SPY"), None)
    qqq = next((i for i in us_data.get("大盤指數",[]) if i["symbol"]=="QQQ"), None)
    vix = next((i for i in us_data.get("大盤指數",[]) if i["symbol"]=="VIX"), None)

    if spy:
        direction = "上漲" if spy["change_pct"] > 0 else "下跌"
        summary.append(f"S&P500 {direction} {abs(spy['change_pct']):.2f}%")
    if qqq:
        direction = "上漲" if qqq["change_pct"] > 0 else "下跌"
        summary.append(f"Nasdaq {direction} {abs(qqq['change_pct']):.2f}%")
    if vix:
        summary.append(f"VIX {vix['price']:.1f}（{'恐慌' if vix['price']>20 else '平穩'}）")

    # 半導體
    soxx = next((i for i in us_data.get("產業ETF",[]) if i["symbol"]=="SOXX"), None)
    nvda = next((i for i in us_data.get("台股連動",[]) if i["symbol"]=="NVDA"), None)
    if soxx:
        summary.append(f"費半 {'▲' if soxx['change_pct']>0 else '▼'}{abs(soxx['change_pct']):.2f}%")
    if nvda:
        summary.append(f"NVIDIA {'▲' if nvda['change_pct']>0 else '▼'}{abs(nvda['change_pct']):.2f}%")

    return " | ".join(summary)
