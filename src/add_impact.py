with open('ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_func = '''
def analyze_news_impact(news_df, smart_df):
    """Claude 直接分析新聞對個股的影響（語意理解，不用關鍵字）"""
    if news_df.empty or smart_df.empty:
        return pd.DataFrame()

    titles = news_df["標題"].dropna().head(80).tolist()
    news_str = "\\n".join([f"- {t}" for t in titles])

    stocks = smart_df[["股票代號","股票名稱"]].head(30).drop_duplicates()
    stock_str = "\\n".join([f"{r['股票代號']} {r['股票名稱']}" for _, r in stocks.iterrows()])

    prompt = f"""你是台灣股市分析師。請分析以下新聞對台股個股的影響。

今日財經新聞標題：
{news_str}

ETF重倉股票清單：
{stock_str}

請分析每則重要新聞對上述股票的影響，只回傳 JSON，格式如下：
{{"影響清單": [{{"新聞摘要": "20字內", "影響股票": ["代號1"], "影響方向": "正面/負面/中性", "影響程度": "高/中/低", "原因": "30字內"}}]}}

規則：只列有明確影響的新聞，影響股票只列清單內代號，最多15則，只回傳JSON。"""

    result = call_claude(prompt, max_tokens=2000)
    if not result:
        return pd.DataFrame()

    try:
        result = result.strip().replace("`json","").replace("`","")
        data = json.loads(result)
        impacts = data.get("影響清單", [])
        rows = []
        for item in impacts:
            for code in item.get("影響股票", []):
                name_match = smart_df[smart_df["股票代號"].astype(str)==str(code)]["股票名稱"].values
                rows.append({
                    "股票代號": code,
                    "股票名稱": name_match[0] if len(name_match) > 0 else "",
                    "新聞摘要": item.get("新聞摘要",""),
                    "影響方向": item.get("影響方向",""),
                    "影響程度": item.get("影響程度",""),
                    "原因": item.get("原因",""),
                })
        df = pd.DataFrame(rows)
        if not df.empty:
            order = {"高":0,"中":1,"低":2}
            df["_sort"] = df["影響程度"].map(order).fillna(3)
            df = df.sort_values(["影響方向","_sort"]).drop(columns=["_sort"])
        log.info(f"AI新聞影響分析完成：{len(df)} 筆")
        return df
    except Exception as e:
        log.warning(f"AI新聞影響解析失敗: {e}")
        return pd.DataFrame()

'''

# 加在 generate_investment_report 之前
old = 'def generate_investment_report('
if old in content:
    content = content.replace(old, new_func + 'def generate_investment_report(', 1)
    print('✅ analyze_news_impact 加入成功')
else:
    print('❌ 找不到')

with open('ai_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
