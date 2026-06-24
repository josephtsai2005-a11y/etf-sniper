f = open('main.py', encoding='utf-8')
c = f.read()
f.close()

# Fix: drop 排名 before inserting in _write_trends_to_sheets
old = 'def _write_trends_to_sheets(ss, trends_df, cross_df, trade_date):'
new = '''def _write_trends_to_sheets(ss, trends_df, cross_df, trade_date):
    # 確保排名欄不重複
    for df in [trends_df, cross_df]:
        if not df.empty and '排名' in df.columns:
            df.drop(columns=['排名'], inplace=True)
            df.insert(0, '排名', range(1, len(df)+1))'''

c = c.replace(old, new, 1)
open('main.py', 'w', encoding='utf-8').write(c)
print('fixed:', old in open('main.py', encoding='utf-8').read() == False)
