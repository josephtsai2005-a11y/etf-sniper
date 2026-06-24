f = open('main.py', encoding='utf-8')
c = f.read()
f.close()

old = '''def _write_trends_to_sheets(ss, trends_df, cross_df, trade_date):
    # 確保排名欄不重複
    for df in [trends_df, cross_df]:
        if not df.empty and '排名' in df.columns:
            df.drop(columns=['排名'], inplace=True)
            df.insert(0, '排名', range(1, len(df)+1))
    """寫入 Google Trends 資料到 Sheets"""
    import time
    trends_df = trends_df.copy()
    cross_df  = cross_df.copy() if not cross_df.empty else cross_df
    for df in [trends_df, cross_df]:
        if not df.empty and "排名" in df.columns:
            df.drop(columns=["排名"], inplace=True)'''

new = '''def _write_trends_to_sheets(ss, trends_df, cross_df, trade_date):
    """寫入 Google Trends 資料到 Sheets"""
    import time
    trends_df = trends_df.copy()
    cross_df  = cross_df.copy() if not cross_df.empty else cross_df
    for df in [trends_df, cross_df]:
        if not df.empty and "排名" in df.columns:
            df.drop(columns=["排名"], inplace=True)'''

c = c.replace(old, new, 1)
open('main.py', 'w', encoding='utf-8').write(c)
print('fixed, occurrences:', c.count('insert(0, chr(39)排名'))
