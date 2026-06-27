with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找 _write_news_to_sheets 那行
for i, line in enumerate(lines):
    if '_write_news_to_sheets(ss2, news_df, TRADE_DATE)' in line:
        insert_point = i + 1
        print(f'插入點：第 {i+1} 行')
        break

new_lines = [
    '\n',
    '            # ── AI 直接分析新聞影響個股 ──────────────────────\n',
    '            if ANTHROPIC_API_KEY:\n',
    '                try:\n',
    '                    import time as _tai\n',
    '                    log.info("AI 分析新聞對個股影響...")\n',
    '                    news_impact_df = analyze_news_impact(news_df, smart_df)\n',
    '                    if not news_impact_df.empty:\n',
    '                        _tai.sleep(5)\n',
    '                        SHEET_CROSS = "新聞×籌碼交叉"\n',
    '                        _ex = [ws.title for ws in ss2.worksheets()]\n',
    '                        if SHEET_CROSS not in _ex:\n',
    '                            ss2.add_worksheet(title=SHEET_CROSS, rows=500, cols=10)\n',
    '                        ws_cross = ss2.worksheet(SHEET_CROSS)\n',
    '                        ws_cross.clear()\n',
    '                        ws_cross.append_row([f"新聞×籌碼交叉 {TRADE_DATE}（AI語意分析）"])\n',
    '                        _tai.sleep(2)\n',
    '                        ws_cross.append_row(news_impact_df.columns.tolist())\n',
    '                        ws_cross.append_rows(news_impact_df.fillna("").values.tolist())\n',
    '                        log.info(f"AI新聞影響分析完成：{len(news_impact_df)} 筆")\n',
    '                except Exception as e:\n',
    '                    log.warning(f"AI新聞影響分析失敗: {e}")\n',
    '\n',
    '            # ── 題材總覽整合 ────────────────────────────────────\n',
    '            if ANTHROPIC_API_KEY:\n',
    '                try:\n',
    '                    import time as _tt\n',
    '                    log.info("建立題材總覽...")\n',
    '                    topic_df = build_topic_overview(ss2, smart_df, TRADE_DATE)\n',
    '                    if not topic_df.empty:\n',
    '                        ai_insight = ai_analyze_topic_overview(topic_df, TRADE_DATE)\n',
    '                        _tt.sleep(5)\n',
    '                        write_topic_overview_to_sheets(ss2, topic_df, ai_insight, TRADE_DATE)\n',
    '                        log.info(f"題材總覽完成：{len(topic_df)} 個題材")\n',
    '                except Exception as e:\n',
    '                    log.warning(f"題材總覽失敗: {e}")\n',
    '\n',
]

lines = lines[:insert_point] + new_lines + lines[insert_point:]

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('✅ AI新聞影響+題材總覽加入成功')
