with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在法人寫入前加 sleep
old = '''            # 寫入 Sheets
            _write_institutional_to_sheets(ss2, inst_df, cross_df, TRADE_DATE)'''
new = '''            # 寫入 Sheets
            import time as _t; _t.sleep(15)
            _write_institutional_to_sheets(ss2, inst_df, cross_df, TRADE_DATE)'''

if old in content:
    content = content.replace(old, new)
    print('✅ 法人寫入 sleep 加入')
else:
    print('❌ 找不到法人寫入')

# 在基本面寫入前加 sleep
old2 = '''            # 寫入 Sheets
            _write_fundamental_to_sheets(ss2, fundamental_df, TRADE_DATE)'''
new2 = '''            # 寫入 Sheets
            import time as _t; _t.sleep(15)
            _write_fundamental_to_sheets(ss2, fundamental_df, TRADE_DATE)'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ 基本面寫入 sleep 加入')
else:
    print('❌ 找不到基本面寫入')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
