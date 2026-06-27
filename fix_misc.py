with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修復個股查詢頁面名稱
content = content.replace('elif page == "📈 個股查詢":', 'elif page == "個股查詢":')
print('✅ 個股查詢修復')

# 2. 修復題材位置欄位名稱（移除重複欄位處理，改用第一行當標題）
old = '''    df = load_sheet("題材位置")
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

new = '''    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        try:
            df = df.astype(str)
            # 修復重複欄位名稱
            seen = {}
            new_cols = []
            for c in df.columns:
                if c in seen:
                    seen[c] += 1
                    new_cols.append(f"{c}_{seen[c]}")
                else:
                    seen[c] = 0
                    new_cols.append(c)
            df.columns = new_cols
            st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.warning(f"顯示錯誤: {e}")
            st.write(df)'''

if old in content:
    content = content.replace(old, new)
    print('✅ 題材位置欄位修復')
else:
    print('❌ 題材位置找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
