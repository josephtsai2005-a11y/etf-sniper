with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    for p in ["新聞×籌碼交叉","題材總覽","散戶情緒"]:'
new = '    for p in ["新聞×籌碼交叉","散戶情緒","題材總覽"]:'

if old in content:
    content = content.replace(old, new)
    print('✅ 順序調整成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
