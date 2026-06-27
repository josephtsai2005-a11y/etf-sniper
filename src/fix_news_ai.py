with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 加入 import
old = 'from ai_analyzer import generate_investment_report, write_ai_report_to_sheets, generate_stock_keywords'
new = '''from ai_analyzer import generate_investment_report, write_ai_report_to_sheets, generate_stock_keywords, analyze_news_impact
from topic_analyzer import build_topic_overview, ai_analyze_topic_overview, write_topic_overview_to_sheets'''

if old in content:
    content = content.replace(old, new)
    print('✅ import 加入')
else:
    print('❌ import 找不到')

# 在新聞寫入後，加入 AI 新聞影響分析
old2 = '''            # ── AI 自動產生個股關鍵字 ──────────────────────────
            if ANTHROPIC_API_KEY:'''

new2 = '''            # ── AI 直接分析新聞影響個股 ──────────────────────
            if ANTHROPIC_API_KEY:
                try:
                    log.info("AI 分析新聞對個股影響...")
                    news_impact_df = analyze_news_impact(news_df, smart_df)
                    if not news_impact_df.empty:
                        import time as _t2
                        _t2.sleep(5)
                        # 寫入新聞×籌碼交叉分頁
                        SHEET_CROSS = "新聞×籌碼交叉"
                        _existing = [ws.title for ws in ss2.worksheets()]
                        if SHEET_CROSS not in _existing:
                            ss2.add_worksheet(title=SHEET_CROSS, rows=500, cols=10)
                        ws_cross = ss2.worksheet(SHEET_CROSS)
                        ws_cross.clear()
                        ws_cross.append_row([f"新聞×籌碼交叉 {TRADE_DATE}（AI語意分析）"])
                        _t2.sleep(2)
                        ws_cross.append_row(news_impact_df.columns.tolist())
                        ws_cross.append_rows(news_impact_df.fillna("").values.tolist())
                        log.info(f"AI新聞影響分析完成：{len(news_impact_df)} 筆")
                except Exception as e:
                    log.warning(f"AI新聞影響分析失敗: {e}")

            # ── 題材總覽整合 ────────────────────────────────────
            if ANTHROPIC_API_KEY:
                try:
                    log.info("建立題材總覽...")
                    topic_df = build_topic_overview(ss2, smart_df, TRADE_DATE)
                    if not topic_df.empty:
                        ai_insight = ai_analyze_topic_overview(topic_df, TRADE_DATE)
                        import time as _t3
                        _t3.sleep(5)
                        write_topic_overview_to_sheets(ss2, topic_df, ai_insight, TRADE_DATE)
                        log.info(f"題材總覽完成：{len(topic_df)} 個題材")
                except Exception as e:
                    log.warning(f"題材總覽失敗: {e}")

            # ── AI 自動產生個股關鍵字 ──────────────────────────
            if ANTHROPIC_API_KEY:'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ AI新聞影響+題材總覽加入')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
