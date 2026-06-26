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
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "A92VPBM3BPP8MXQN")

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


def fetch_all_us_market() -> dict:
    """抓取所有市場資料（免費版每分鐘5次）"""
    results = {}
    total = sum(len(v) for v in MARKET_TARGETS.values())
    count = 0

    for category, symbols in MARKET_TARGETS.items():
        results[category] = []
        for symbol, name in symbols.items():
            count += 1
            log.info(f"  [{count}/{total}] 抓取 {symbol} ({name})...")
            data = fetch_quote(symbol)
            if data:
                data["name"] = name
                results[category].append(data)
                arrow = "▲" if data["change_pct"] > 0 else "▼" if data["change_pct"] < 0 else "—"
                log.info(f"    {name}: {data['price']} {arrow}{abs(data['change_pct']):.2f}%")
            time.sleep(13)  # 每分鐘5次限制，保守設13秒

    return results


def format_us_market_for_ai(us_data: dict) -> str:
    """格式化給 AI 分析用"""
    if not us_data:
        return "（無美股資料）"

    lines = []
    for category, items in us_data.items():
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
