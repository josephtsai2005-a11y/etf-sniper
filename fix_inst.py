with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    display_cols = ["排名","股票代號","外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數","法人訊號"]'
new = '    display_cols = ["排名","股票代號","股票名稱","外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數","法人訊號"]'

if old in content:
    content = content.replace(old, new)
    print('✅ 完成')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
