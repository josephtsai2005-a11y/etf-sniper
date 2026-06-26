with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在頁面判斷最前面加入分隔線防護
old = 'if page == "🏆 多方驗證名單":'
new = '''# 分隔線項目不做任何事
if page.startswith("—"):
    st.info("請選擇上方的功能頁面")
    st.stop()

if page == "🏆 多方驗證名單":'''

if old in content:
    content = content.replace(old, new)
    print('✅ 分隔線防護加入')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
