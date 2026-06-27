with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('elif page == "🤖 每日AI總結":', 'elif page == "每日AI總結":')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('✅ 完成')
