with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 加入 import
old = 'from ai_analyzer import generate_investment_report, write_ai_report_to_sheets, generate_stock_keywords\nfrom us_market_fetcher import fetch_all_us_market, format_us_market_for_ai, get_market_sentiment_summary'
if old not in content:
    old2 = 'from trends_fetcher import fetch_all_trends, compute_trends_signal, cross_news_and_trends'
    new2 = '''from trends_fetcher import fetch_all_trends, compute_trends_signal, cross_news_and_trends
from ai_analyzer import generate_investment_report, write_ai_report_to_sheets, generate_stock_keywords
from us_market_fetcher import fetch_all_us_market, format_us_market_for_ai, get_market_sentiment_summary'''
    if old2 in content:
        content = content.replace(old2, new2)
        print('✅ import 加入')
    else:
        print('❌ import 找不到')
else:
    print('✅ import 已存在')

# 加入環境變數
old3 = 'LINE_TOKEN       = os.environ.get("LINE_NOTIFY_TOKEN", "")'
if 'ALPHA_VANTAGE_KEY' not in content:
    new3 = '''LINE_TOKEN        = os.environ.get("LINE_NOTIFY_TOKEN", "")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "A92VPBM3BPP8MXQN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")'''
    content = content.replace(old3, new3)
    print('✅ 環境變數加入')

# 加入 AI 模式（在 news return 之後）
old4 = '''    if RUN_MODE == "news":
        log.info("RUN_MODE=news，新聞階段完成")
        log.info("===== 全部完成 =====")
        return'''

new4 = '''    if RUN_MODE == "news":
        log.info("RUN_MODE=news，新聞階段完成")
        log.info("===== 全部完成 =====")
        return

    # ── AI 模式：整合所有資料 + 美股 → 產生投資報告 ─────────────
    if RUN_MODE == "ai":
        log.info("[AI] 開始產生每日投資報告...")
        try:
            import time as _t
            import os as _os
            _os.environ["ALPHA_VANTAGE_KEY"] = ALPHA_VANTAGE_KEY
            _os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

            log.info("[AI] 抓取美股資料（約4分鐘）...")
            us_data = fetch_all_us_market()
            us_text = format_us_market_for_ai(us_data)
            us_summary = get_market_sentiment_summary(us_data)
            log.info(f"[AI] 美股摘要：{us_summary}")

            log.info("[AI] 產生投資報告...")
            report = generate_investment_report(ss2, TRADE_DATE, us_text)

            if report:
                _t.sleep(5)
                write_ai_report_to_sheets(ss2, report, TRADE_DATE)
                send_line_notify(f"\\n📊 {TRADE_DATE} AI投資報告\\n\\n{report[:300]}...\\n\\n完整報告請看 Sheets")
                log.info("[AI] 報告完成！")
            else:
                log.warning("[AI] 報告產生失敗")
        except Exception as e:
            log.warning(f"AI 模式失敗: {e}")
            import traceback
            log.debug(traceback.format_exc())
        log.info("===== 全部完成 =====")
        return'''

if old4 in content:
    content = content.replace(old4, new4)
    print('✅ AI 模式加入')
else:
    print('❌ AI 模式找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
