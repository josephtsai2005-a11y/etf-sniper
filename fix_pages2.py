with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修復 AI 報告頁面的欄位讀取
old = '''elif page == "每日AI總結":
    st.title("🤖 每日 AI 投資報告")
    st.caption("由 Claude AI 整合 ETF籌碼、法人、基本面、題材、美股，產生專業投資分析")
    df = load_sheet("每日AI總結")
    if df.empty:
        st.warning("尚無 AI 報告（每日 23:00 後更新）")
    else:
        # 顯示最新一筆
        latest = df.iloc[-1]
        date = latest.get("日期", "")
        time_str = latest.get("更新時間", "")
        # 合併兩欄報告
        part1 = latest.get("AI分析報告（上）", latest.get("AI分析報告", ""))
        part2 = latest.get("AI分析報告（下）", "")
        report = part1 + part2
        st.caption(f"📅 {date} 更新：{time_str}")
        st.markdown(report)
        st.divider()
        # 顯示歷史報告
        if len(df) > 1:
            with st.expander("📚 歷史報告"):
                for _, row in df.iloc[:-1].iloc[::-1].iterrows():
                    st.caption(f"📅 {row.get('日期','')} {row.get('更新時間','')}")
                    st.markdown(row.get("AI分析報告",""))
                    st.divider()'''

new = '''elif page == "每日AI總結":
    st.title("每日 AI 投資報告")
    st.caption("由 Claude AI 整合 ETF籌碼、法人、基本面、題材、美股，產生專業投資分析")
    ws_ai = None
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

if old in content:
    content = content.replace(old, new)
    print('✅ AI 報告頁面修復成功')
else:
    print('❌ 找不到')

# 同時修復 page 名稱對應（移除 emoji 後需要更新）
pages_to_fix = [
    ('elif page == "🏆 多方驗證名單":', 'elif page == "多方驗證名單":'),
    ('elif page == "⚡ 今日訊號":', 'elif page == "今日訊號":'),
    ('elif page == "🎯 今日聰明錢名單":', 'elif page == "聰明錢名單":'),
    ('elif page == "📊 持股異動明細":', 'elif page == "持股異動明細":'),
    ('elif page == "🏦 三大法人":', 'elif page == "三大法人":'),
    ('elif page == "📈 基本面資料":', 'elif page == "基本面資料":'),
    ('elif page == "🔗 新聞×籌碼交叉":', 'elif page == "新聞×籌碼交叉":'),
    ('elif page == "📰 題材趨勢":', 'elif page == "題材趨勢":'),
    ('elif page == "🎯 題材位置":', 'elif page == "題材位置":'),
    ('elif page == "📱 散戶情緒":', 'elif page == "散戶情緒":'),
    ('elif page == "📊 ETF 覆蓋分析":', 'elif page == "ETF 覆蓋分析":'),
    ('elif page == "🔍 個股查詢":', 'elif page == "個股查詢":'),
    ('elif page == "🗂️ 原始持股庫":', 'elif page == "原始持股庫":'),
    ('if page == "🏆 多方驗證名單":', 'if page == "多方驗證名單":'),
]

for old_p, new_p in pages_to_fix:
    if old_p in content:
        content = content.replace(old_p, new_p)
        print(f'✅ {new_p}')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
