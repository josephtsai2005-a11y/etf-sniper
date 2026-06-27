with open('ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    try:
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
        return pd.DataFrame()'''

new = '''    try:
        result = result.strip().replace("`json","").replace("`","")
        data = json.loads(result)

        # 支援多種 JSON 格式
        impacts = (data.get("影響清單") or 
                   data.get("news_stock_impact") or 
                   data.get("impacts") or 
                   data.get("analysis") or [])

        rows = []
        for item in impacts:
            # 支援多種欄位名稱
            affected = (item.get("影響股票") or 
                       item.get("affected_stocks") or [])
            
            news_summary = (item.get("新聞摘要") or 
                           item.get("news","")[:30])
            direction = (item.get("影響方向") or 
                        item.get("impact_direction","中性"))
            degree = (item.get("影響程度") or 
                     item.get("impact_level","中"))
            reason = (item.get("原因") or 
                     item.get("reason",""))

            for stock in affected:
                # 支援字串或字典格式
                if isinstance(stock, dict):
                    code = str(stock.get("code",""))
                    stock_name = stock.get("name","")
                    reason2 = stock.get("reason", reason)
                else:
                    code = str(stock)
                    stock_name = ""
                    reason2 = reason

                if not stock_name:
                    name_match = smart_df[smart_df["股票代號"].astype(str)==code]["股票名稱"].values
                    stock_name = name_match[0] if len(name_match) > 0 else ""

                rows.append({
                    "股票代號": code,
                    "股票名稱": stock_name,
                    "新聞摘要": news_summary,
                    "影響方向": direction,
                    "影響程度": degree,
                    "原因": reason2,
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
        import traceback
        log.debug(traceback.format_exc())
        return pd.DataFrame()'''

if old in content:
    content = content.replace(old, new)
    print('✅ 解析邏輯修復成功')
else:
    print('❌ 找不到')

with open('ai_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
