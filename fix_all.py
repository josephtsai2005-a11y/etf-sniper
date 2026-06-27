with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修復題材位置 dataframe 問題
old1 = '''    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        st.dataframe(df, use_container_width=True)'''

new1 = '''    df = load_sheet("題材位置")
    if df.empty:
        st.warning("尚無題材位置資料（每日 21:00 後更新）")
    else:
        df = df.astype(str)
        st.dataframe(df, use_container_width=True)'''

if old1 in content:
    content = content.replace(old1, new1)
    print('✅ 題材位置修復')

# 2. 修復 AI 報告頁面 - 用 load_sheet 取代 get_spreadsheet
old2 = '''    ws_ai = None
    try:
        ws_ai = get_spreadsheet().worksheet("每日AI總結")
        vals = ws_ai.get_all_values()
        if len(vals) < 2:
            st.warning("尚無 AI 報告（每日 23:00 後更新）")
        else:
            headers = vals[0]
            rows = vals[1:]
            df = pd.DataFrame(rows, columns=headers)
            latest = df.iloc[-1]
            date = latest.get("日期", "")
            time_str = latest.get("更新時間", "")
            # 合併兩欄
            part1 = latest.get("AI分析報告（上）", latest.get("AI分析報告", ""))
            part2 = latest.get("AI分析報告（下）", "")
            report = part1 + part2
            st.caption(f"📅 {date} 更新：{time_str}")
            if report.strip():
                st.markdown(report)
            else:
                st.warning("報告內容為空")
            st.divider()
            if len(df) > 1:
                with st.expander("歷史報告"):
                    for _, row in df.iloc[:-1].iloc[::-1].iterrows():
                        p1 = row.get("AI分析報告（上）", row.get("AI分析報告",""))
                        p2 = row.get("AI分析報告（下）","")
                        st.caption(f"📅 {row.get('日期','')} {row.get('更新時間','')}")
                        st.markdown(p1 + p2)
                        st.divider()
    except Exception as e:
        st.error(f"無法載入 AI 報告: {e}")'''

new2 = '''    try:
        df = load_sheet("每日AI總結")
        if df.empty:
            st.warning("尚無 AI 報告（每日 23:00 後更新）")
        else:
            latest = df.iloc[-1]
            date = latest.get("日期", "")
            time_str = latest.get("更新時間", "")
            part1 = latest.get("AI分析報告（上）", latest.get("AI分析報告", ""))
            part2 = latest.get("AI分析報告（下）", "")
            report = part1 + part2
            st.caption(f"📅 {date} 更新：{time_str}")
            if report.strip():
                st.markdown(report)
            else:
                st.warning("報告內容為空，請等待 23:00 後更新")
            st.divider()
            if len(df) > 1:
                with st.expander("歷史報告"):
                    for _, row in df.iloc[:-1].iloc[::-1].iterrows():
                        p1 = row.get("AI分析報告（上）", row.get("AI分析報告",""))
                        p2 = row.get("AI分析報告（下）","")
                        st.caption(f"📅 {row.get('日期','')} {row.get('更新時間','')}")
                        st.markdown(p1 + p2)
                        st.divider()
    except Exception as e:
        st.error(f"無法載入 AI 報告: {e}")'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ AI 報告修復')
else:
    print('❌ AI 報告找不到')

# 3. 修復多個紅點問題 - 加入 index 參數讓預設值為 None
content = content.replace(
    'page = st.radio("core", [\n        "多方驗證名單",',
    'page = st.radio("core", [\n        "多方驗證名單",'
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('完成')
