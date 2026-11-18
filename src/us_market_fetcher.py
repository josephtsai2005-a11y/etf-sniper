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

    2026-11-18新增（詳見claude/todo_20261113_us_market_direction_mismatch.md
    根因確認）：Alpha Vantage免費版GLOBAL_QUOTE在美股剛收盤（這個系統固定約台北
    時間05:02查詢，等於美東下午4:02，收盤後僅2分鐘）查詢時，常常還沒更新到當天
    收盤，回傳的是前一個交易日的舊資料——實測2026-11-18那次，15個symbol全部一致
    停在前一天。這裡加入資料新鮮度檢查，結果附加進回傳dict的"_freshness"欄位，
    不影響既有的symbol資料結構，呼叫端（format_us_market_for_ai）會依此在文字裡
    明確標註警告，不讓AI把過期資料誤當成最新收盤分析。
    """
    results = {}
    total = sum(len(v) for v in MARKET_TARGETS.values())
    count = 0
    actual_dates = set()

    for category, symbols in MARKET_TARGETS.items():
        results[category] = []
        for symbol, name in symbols.items():
            count += 1
            log.info(f"  [{count}/{total}] 抓取 {symbol} ({name})...")
            data = fetch_quote(symbol)
            if data:
                data["name"] = name
                results[category].append(data)
                if data.get("date"):
                    actual_dates.add(data["date"])
                arrow = "▲" if data["change_pct"] > 0 else "▼" if data["change_pct"] < 0 else "—"
                log.info(f"    {name}: {data['price']} {arrow}{abs(data['change_pct']):.2f}% （資料日期: {data.get('date','')}）")
            time.sleep(13)  # 每分鐘5次限制，保守設13秒

    expected_date = _expected_us_trading_date()
    is_stale = bool(actual_dates) and expected_date not in actual_dates
    results["_freshness"] = {
        "expected_date": expected_date,
        "actual_dates": sorted(actual_dates),
        "is_stale": is_stale,
    }
    if is_stale:
        log.warning(f"⚠️ 美股資料新鮮度異常：預期交易日 {expected_date}，實際抓到的日期是 "
                    f"{sorted(actual_dates)}，疑似Alpha Vantage尚未更新到最新收盤")

    return results


def format_us_market_for_ai(us_data: dict) -> str:
    """格式化給 AI 分析用"""
    if not us_data:
        return "（無美股資料）"

    freshness = us_data.get("_freshness", {})
    lines = []
    if freshness.get("is_stale"):
        lines.extend([
            f"⚠️ 資料新鮮度警告：以下數據實際的資料日期是 {'、'.join(freshness.get('actual_dates', []))}，"
            f"不是預期的最新交易日 {freshness.get('expected_date','')}。這極可能是資料來源（Alpha Vantage）",
            "尚未更新到當日收盤，底下的漲跌幅應視為「前一交易日」的數據，不是最新收盤——分析時請明確",
            "告知這是有疑慮、可能非最新的資料，不要當成確定的最新收盤方向直接下結論或據此推薦操作。",
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
            lines.append(f"  {name}: {price:.2f} {arrow}{abs(pct):.2f}% {sentiment}")
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
