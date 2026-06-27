with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

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
    try:
        _client = get_client()
        _sid = st.secrets.get("SPREADSHEET_ID","") or os.environ.get("SPREADSHEET_ID","")
        _ss = _client.open_by_key(_sid)
        _ws = _ss.worksheet("每日AI總結")
        _vals = _ws.get_all_values()
        if len(_vals) < 2:
            st.warning("尚無 AI 報告（每日 23:00 後更新）")
        else:
            _headers = _vals[0]
            _rows = pd.DataFrame(_vals[1:], columns=_headers)
            _latest = _rows.iloc[-1]
            _date = _latest.get("日期","")
            _time = _latest.get("更新時間","")
            _p1 = _latest.get("AI分析報告（上）", _latest.get("AI分析報告",""))
            _p2 = _latest.get("AI分析報告（下）","")
            _report = _p1 + _p2
            st.caption(f"📅 {_date} 更新：{_time}")
            if _report.strip():
                st.markdown(_report)
            else:
                st.warning("報告內容為空，請等待 23:00 後更新")
            st.divider()
            if len(_rows) > 1:
                with st.expander("歷史報告"):
                    for _, _row in _rows.iloc[:-1].iloc[::-1].iterrows():
                        _rp1 = _row.get("AI分析報告（上）",_row.get("AI分析報告",""))
                        _rp2 = _row.get("AI分析報告（下）","")
                        st.caption(f"📅 {_row.get('日期','')} {_row.get('更新時間','')}")
                        st.markdown(_rp1 + _rp2)
                        st.divider()
    except Exception as _e:
        st.error(f"無法載入 AI 報告: {_e}")'''

if old in content:
    content = content.replace(old, new)
    print('✅ AI 報告頁面修復成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
