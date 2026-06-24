f = open('main.py', encoding='utf-8')
c = f.read()
f.close()
old = '                _write_trends_to_s'
# Find full line
idx = c.find('_write_trends_to_sheets(ss2, trends_signal, cross_df2, TRADE_DATE)')
print('found at:', idx)
print(c[idx-50:idx+100])
