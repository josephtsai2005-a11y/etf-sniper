f = open('main.py', encoding='utf-8')
c = f.read()
f.close()
old = '    for sheet_name, df in [("散戶情緒", trends_df), ("題材位置", cross_df)]:'
new = '''    trends_df = trends_df.copy()
    cross_df  = cross_df.copy() if not cross_df.empty else cross_df
    for df in [trends_df, cross_df]:
        if not df.empty and "排名" in df.columns:
            df.drop(columns=["排名"], inplace=True)
    for sheet_name, df in [("散戶情緒", trends_df), ("題材位置", cross_df)]:'''
c = c.replace(old, new, 1)
open('main.py', 'w', encoding='utf-8').write(c)
print('fixed:', '排名' in c)
