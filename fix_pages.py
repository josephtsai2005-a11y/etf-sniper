with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_pages = '''
elif page == "📊 持股異動明細":
    st.title("📊 持股異動明細")
    st.caption("ETF 每日持股變動明細")
    df = load_sheet("持股異動明細")
    if df.empty:
        st.warning("尚無持股異動明細（每日 15:30 後更新）")
    else:
        st.dataframe(df, use_container_width=True)

elif page == "📈 基本面資料":
    st.title("📈 基本面資料")
    st.caption("月營收、本益比、成長率")
    df = load_sheet("基本面資料")
    if df.empty:
        st.warning("尚無基本面資料（每日 16:45 後更新）")
    else:
        st.dataframe(df, use_container_width=True)

elif page == "🎯 題材位置":
    st.title("🎯 題材位置")
    st.caption("新聞題材與散戶情緒交叉分析")
    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        st.dataframe(df, use_container_width=True)
'''

# 在最後一個 elif 後面加入
old = 'elif page == "🗂️ 原始持股庫":'
new = new_pages + 'elif page == "🗂️ 原始持股庫":'

if old in content:
    content = content.replace(old, new)
    print('✅ 三個新頁面加入成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
