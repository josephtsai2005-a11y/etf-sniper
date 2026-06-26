with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    page = st.radio("頁面", [
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🏦 三大法人",
        "📰 題材趨勢",
        "🔗 新聞×籌碼交叉",
        "📱 散戶情緒",
        "🎯 今日聰明錢名單",
        "📊 ETF 覆蓋分析",
        "📈 個股查詢",
        "🗂️ 原始持股庫",
    ])'''

new = '''    st.caption("🕒 15:30 核心資料")
    page = st.radio("頁面", [
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "📊 持股異動明細",
        "— 16:45 法人資料 —",
        "🏦 三大法人",
        "📈 基本面資料",
        "— 21:00 新聞分析 —",
        "🔗 新聞×籌碼交叉",
        "📰 題材趨勢",
        "🎯 題材位置",
        "📱 散戶情緒",
        "— 其他 —",
        "📊 ETF 覆蓋分析",
        "🔍 個股查詢",
        "🗂️ 原始持股庫",
    ])'''

if old in content:
    content = content.replace(old, new)
    print('✅ 選單修改成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
