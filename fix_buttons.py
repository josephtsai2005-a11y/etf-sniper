with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到整個 sidebar radio 區塊
old = '''    st.markdown("#### 15:30 核心資料")
    page = st.radio("core", [
        "多方驗證名單",
        "今日訊號",
        "聰明錢名單",
        "持股異動明細",
    ], label_visibility="collapsed", key="core")

    st.markdown("---")
    st.markdown("#### 16:45 法人資料")
    page2 = st.radio("inst", [
        "三大法人",
        "基本面資料",
    ], label_visibility="collapsed", key="inst")

    st.markdown("---")
    st.markdown("#### 21:00 新聞分析")
    page3 = st.radio("news", [
        "新聞×籌碼交叉",
        "題材趨勢",
        "題材位置",
        "散戶情緒",
    ], label_visibility="collapsed", key="news")

    st.markdown("---")
    st.markdown("#### 其他")
    page4 = st.radio("other", [
        "每日AI總結",
        "ETF 覆蓋分析",
        "個股查詢",
        "原始持股庫",
    ], label_visibility="collapsed", key="other")'''

new = '''    st.markdown("#### 15:30 核心資料")
    for p in ["多方驗證名單","今日訊號","聰明錢名單","持股異動明細"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p
    st.markdown("---")
    st.markdown("#### 16:45 法人資料")
    for p in ["三大法人","基本面資料"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p
    st.markdown("---")
    st.markdown("#### 21:00 新聞分析")
    for p in ["新聞×籌碼交叉","題材趨勢","題材位置","散戶情緒"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p
    st.markdown("---")
    st.markdown("#### 其他")
    for p in ["每日AI總結","ETF 覆蓋分析","個股查詢","原始持股庫"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p'''

if old in content:
    content = content.replace(old, new)
    print('✅ 選單改為按鈕')
else:
    print('❌ 找不到')

# 移除舊的 session_state 追蹤邏輯，改用簡單版
old2 = '''    # 追蹤最後點選的分組和選項
    if "selected_page" not in st.session_state:
        st.session_state.selected_page = "多方驗證名單"
        st.session_state.last_group = "core"

    prev_page = page
    prev_page2 = page2
    prev_page3 = page3
    prev_page4 = page4

    if page != st.session_state.get("prev_core", page):
        st.session_state.selected_page = page
        st.session_state.last_group = "core"
    elif page2 != st.session_state.get("prev_inst", page2):
        st.session_state.selected_page = page2
        st.session_state.last_group = "inst"
    elif page3 != st.session_state.get("prev_news", page3):
        st.session_state.selected_page = page3
        st.session_state.last_group = "news"
    elif page4 != st.session_state.get("prev_other", page4):
        st.session_state.selected_page = page4
        st.session_state.last_group = "other"

    st.session_state.prev_core = page
    st.session_state.prev_inst = page2
    st.session_state.prev_news = page3
    st.session_state.prev_other = page4

    page = st.session_state.selected_page'''

new2 = '''    if "selected_page" not in st.session_state:
        st.session_state.selected_page = "多方驗證名單"
    page = st.session_state.selected_page'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ session_state 簡化')
else:
    print('❌ session_state 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
