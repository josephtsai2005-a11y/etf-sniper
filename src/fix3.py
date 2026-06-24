f = open('main.py', encoding='utf-8')
c = f.read()
f.close()
old = '                _write_trends_to_sheets(ss2, trends_signal, cross_df2, TRADE_DATE)'
new = '''                for _df in [trends_signal, cross_df2]:
                    if not _df.empty and "排名" in _df.columns:
                        _df.drop(columns=["排名"], inplace=True)
                _write_trends_to_sheets(ss2, trends_signal, cross_df2, TRADE_DATE)'''
c = c.replace(old, new, 1)
open('main.py', 'w', encoding='utf-8').write(c)
print('fixed')
