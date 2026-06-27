with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    # 用 session_state 追蹤最後點選的分組
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

new = '''    # 追蹤最後點選的分組和選項
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

if old in content:
    content = content.replace(old, new)
    print('✅ 紅點修復成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
