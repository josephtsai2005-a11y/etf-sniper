import re
f = open('main.py', encoding='utf-8')
c = f.read()
f.close()

# 在每個 _write 函式呼叫前加 30 秒等待
old1 = '        write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)'
new1 = '        import time as _t; _t.sleep(10)\n        write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)'

old2 = '            _write_diff_to_sheets(ss2, stock_diff, diff_detail, TRADE_DATE)'
new2 = '            import time as _t; _t.sleep(30)\n            _write_diff_to_sheets(ss2, stock_diff, diff_detail, TRADE_DATE)'

old3 = '            _write_news_to_sheets(ss2, news_df, TRADE_DATE)'
new3 = '            import time as _t; _t.sleep(30)\n            _write_news_to_sheets(ss2, news_df, TRADE_DATE)'

old4 = '            _write_trends_to_sheets(ss2, trends_signal, cross_df2, TRADE_DATE)'
new4 = '            import time as _t; _t.sleep(30)\n            _write_trends_to_sheets(ss2, trends_signal, cross_df2, TRADE_DATE)'

for old, new in [(old1,new1),(old2,new2),(old3,new3),(old4,new4)]:
    if old in c:
        c = c.replace(old, new, 1)
        print('fixed:', old[:50])
    else:
        print('not found:', old[:50])

open('main.py', 'w', encoding='utf-8').write(c)
