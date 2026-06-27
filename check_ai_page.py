with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找 AI 報告頁面
for i, line in enumerate(content.split('\n')):
    if 'AI' in line and 'page' in line and 'elif' in line:
        print(f'{i+1}: {line}')
    if '每日AI' in line and 'page' in line:
        print(f'{i+1}: {line}')
