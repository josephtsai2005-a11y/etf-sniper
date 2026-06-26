with open('ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 加入獨立的受惠股函數
new_func = '''
def generate_related_stocks(smart_df: pd.DataFrame, trend_df: pd.DataFrame) -> str:
    """獨立呼叫：產生產業輪動受惠股推薦"""
    if smart_df.empty:
        return ""

    # 準備強勢股資料
    top_stocks = []
    for _, row in smart_df.head(10).iterrows():
        top_stocks.append(f"- {row.get('股票代號','')} {row.get('股票名稱','')}（{row.get('持有ETF數','')}檔ETF持有，訊號：{row.get('訊號','')}）")
    stocks_str = "\\n".join(top_stocks)

    # 準備題材資料
    themes = []
    if not trend_df.empty and "關鍵字" in trend_df.columns:
        themes = trend_df.head(5)["關鍵字"].tolist()
    themes_str = "、".join(themes) if themes else "AI伺服器、半導體、散熱"

    prompt = f"""今日台股ETF主動式基金重倉強勢股：
{stocks_str}

今日熱門題材：{themes_str}

請推薦10檔產業輪動受惠股（這些股票不在ETF持倉內，但可能因產業輪動受益）：

條件：
1. 優先選股價在500元以下的標的
2. 必須與上述強勢股的產業主題直接相關
3. 說明與主力題材的關聯性

請用以下格式回覆：
### 🔄 產業輪動受惠股（10檔）

| 排名 | 代號 | 名稱 | 關聯題材 | 股價區間 | 受益原因 |
|------|------|------|----------|----------|----------|
| 1 | XXXX | XXX | XXX | XXX元以下 | XXX |
...

注意：以上僅供參考，非買賣建議。"""

    return call_claude(prompt, max_tokens=1500)

'''

# 插入在 generate_investment_report 之前
old = 'def generate_investment_report('
content = content.replace(old, new_func + 'def generate_investment_report(', 1)

# 在主報告函數裡加入受惠股
old2 = '    log.info("呼叫 Claude API...")\n    return call_claude(prompt, system=system_prompt, max_tokens=2000)'
new2 = '''    log.info("呼叫 Claude API 產生主報告...")
    main_report = call_claude(prompt, system=system_prompt, max_tokens=2000)

    # 獨立呼叫產生受惠股
    log.info("呼叫 Claude API 產生受惠股推薦...")
    smart_df = data.get("聰明錢名單", pd.DataFrame())
    trend_df = data.get("題材趨勢", pd.DataFrame())
    related = generate_related_stocks(smart_df, trend_df)

    return main_report + "\\n\\n" + related if related else main_report'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ 受惠股獨立呼叫加入成功')
else:
    print('❌ 找不到')

with open('ai_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
