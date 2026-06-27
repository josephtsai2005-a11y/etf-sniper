with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        df = df.astype(str)
        st.dataframe(df, use_container_width=True)'''

new = '''    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        df = df.astype(str)
        df.columns = [f"{c}_{i}" if df.columns.tolist().count(c) > 1 else c 
                      for i, c in enumerate(df.columns)]
        try:
            st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.write(df.to_dict())'''

if old in content:
    content = content.replace(old, new)
    print('✅ 題材位置修復')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
