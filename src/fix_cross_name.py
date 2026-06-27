with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 把舊版關鍵字交叉改名，不再覆蓋 AI 版
old = '    for sheet_name, df in [("題材趨勢", trend_df), ("新聞×籌碼交叉"'
new = '    for sheet_name, df in [("題材趨勢", trend_df), ("新聞×籌碼交叉(關鍵字版)"'

if old in content:
    content = content.replace(old, new)
    print('✅ 舊版改名成功')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
