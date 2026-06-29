with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    df = load_sheet("基本面資料")
    if df.empty:
        st.warning("尚無基本面資料（每日 16:45 後更新）")
    else:
        st.dataframe(df, use_container_width=True)'''

new = '''    df = load_sheet("基本面資料")
    if df.empty:
        st.warning("尚無基本面資料（每日 16:45 後更新）")
    else:
        display_cols = ["股票代號","股票名稱","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"]
        avail = [c for c in display_cols if c in df.columns]
        st.dataframe(df[avail].astype(str), use_container_width=True)'''

if old in content:
    content = content.replace(old, new)
    print('✅ 完成')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
