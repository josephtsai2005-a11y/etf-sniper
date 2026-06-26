with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    st.markdown("**🕒 15:30 核心資料**")
    page = st.radio("##core", [
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "📊 持股異動明細",
    ], label_visibility="collapsed")

    st.markdown("**🏦 16:45 法人資料**")
    page2 = st.radio("##inst", [
        "🏦 三大法人",
        "📈 基本面資料",
    ], label_visibility="collapsed")

    st.markdown("**📰 21:00 新聞分析**")
    page3 = st.radio("##news", [
        "🔗 新聞×籌碼交叉",
        "📰 題材趨勢",
        "🎯 題材位置",
        "📱 散戶情緒",
    ], label_visibility="collapsed")

    st.markdown("**其他**")
    page4 = st.radio("##other", [
        "📊 ETF 覆蓋分析",
        "🔍 個股查詢",
        "🗂️ 原始持股庫",
    ], label_visibility="collapsed")

    # 合併選擇
    _selected = [p for p in [page, page2, page3, page4] if p]
    page = _selected[0] if _selected else "🏆 多方驗證名單"'''

new = '''    all_pages = [
        "── 🕒 15:30 核心資料 ──",
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "📊 持股異動明細",
        "── 🏦 16:45 法人資料 ──",
        "🏦 三大法人",
        "📈 基本面資料",
        "── 📰 21:00 新聞分析 ──",
        "🔗 新聞×籌碼交叉",
        "📰 題材趨勢",
        "🎯 題材位置",
        "📱 散戶情緒",
        "── 其他 ──",
        "📊 ETF 覆蓋分析",
        "🔍 個股查詢",
        "🗂️ 原始持股庫",
    ]
    _separators = [p for p in all_pages if p.startswith("──")]
    page = st.radio("頁面", all_pages, label_visibility="collapsed")
    if page in _separators:
        st.stop()'''

if old in content:
    content = content.replace(old, new)
    print('✅ 選單修改成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
