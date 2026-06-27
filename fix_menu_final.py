with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 更新選單結構
old = '''    st.markdown("#### 15:30 核心資料")
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
    for p in ["新聞×籌碼交叉","散戶情緒","題材總覽"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p
    st.markdown("---")
    st.markdown("#### 其他")
    for p in ["每日AI總結","ETF 覆蓋分析","個股查詢","原始持股庫"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p'''

new = '''    st.markdown("#### 15:30 核心資料")
    for p in ["多方驗證名單","今日訊號","聰明錢名單","持股異動明細",
              "三大法人","基本面資料","ETF 覆蓋分析","個股查詢","原始持股庫"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p
    st.markdown("---")
    st.markdown("#### 21:00 新聞分析")
    for p in ["新聞×籌碼交叉","散戶情緒","題材總覽"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p
    st.markdown("---")
    st.markdown("#### 23:00 AI報告")
    for p in ["每日AI總結"]:
        if st.button(p, key=f"btn_{p}", use_container_width=True):
            st.session_state.selected_page = p'''

if old in content:
    content = content.replace(old, new)
    print('✅ 選單更新成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
