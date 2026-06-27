with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    all_pages = [
        "── 15:30 核心資料 ──",
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "📊 持股異動明細",
        "── 16:45 法人資料 ──",
        "🏦 三大法人",
        "📈 基本面資料",
        "── 21:00 新聞分析 ──",
        "🔗 新聞×籌碼交叉",
        "📰 題材趨勢",
        "🎯 題材位置",
        "📱 散戶情緒",
        "── 其他 ──",
        "🤖 每日AI總結",
        "📊 ETF 覆蓋分析",
        "🔍 個股查詢",
        "🗂️ 原始持股庫",
    ]
    _separators = [p for p in all_pages if p.startswith("──")]
    page = st.radio("頁面", all_pages, label_visibility="collapsed")
    if page in _separators:
        st.stop()'''

new = '''    st.markdown("#### 🕒 15:30 核心資料")
    page = st.radio("core", [
        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "📊 持股異動明細",
    ], label_visibility="collapsed", key="core")

    st.markdown("---")
    st.markdown("#### 🏦 16:45 法人資料")
    page2 = st.radio("inst", [
        "🏦 三大法人",
        "📈 基本面資料",
    ], label_visibility="collapsed", key="inst")

    st.markdown("---")
    st.markdown("#### 📰 21:00 新聞分析")
    page3 = st.radio("news", [
        "🔗 新聞×籌碼交叉",
        "📰 題材趨勢",
        "🎯 題材位置",
        "📱 散戶情緒",
    ], label_visibility="collapsed", key="news")

    st.markdown("---")
    st.markdown("#### 其他")
    page4 = st.radio("other", [
        "🤖 每日AI總結",
        "📊 ETF 覆蓋分析",
        "🔍 個股查詢",
        "🗂️ 原始持股庫",
    ], label_visibility="collapsed", key="other")

    # 用 session_state 追蹤最後點選的分組
    import streamlit as _st
    if "last_group" not in st.session_state:
        st.session_state.last_group = "core"

    # 偵測哪個分組被改變
    if "prev_core" not in st.session_state:
        st.session_state.prev_core = page
        st.session_state.prev_inst = page2
        st.session_state.prev_news = page3
        st.session_state.prev_other = page4

    if page != st.session_state.prev_core:
        st.session_state.last_group = "core"
        st.session_state.prev_core = page
    elif page2 != st.session_state.prev_inst:
        st.session_state.last_group = "inst"
        st.session_state.prev_inst = page2
    elif page3 != st.session_state.prev_news:
        st.session_state.last_group = "news"
        st.session_state.prev_news = page3
    elif page4 != st.session_state.prev_other:
        st.session_state.last_group = "other"
        st.session_state.prev_other = page4

    group_map = {"core": page, "inst": page2, "news": page3, "other": page4}
    page = group_map[st.session_state.last_group]'''

if old in content:
    content = content.replace(old, new)
    print('✅ 選單修改成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
