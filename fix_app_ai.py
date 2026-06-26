with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 加入 AI 報告到選單
old = '        "── 其他 ──",'
new = '        "── 其他 ──",\n        "🤖 每日AI總結",'

content = content.replace(old, new)

# 加入頁面內容
old2 = 'elif page == "📊 ETF 覆蓋分析":'
new2 = '''elif page == "🤖 每日AI總結":
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
        report = latest.get("AI分析報告", "")
        st.caption(f"📅 {date} 更新：{time_str}")
        st.markdown(report)
        st.divider()
        # 顯示歷史報告
        if len(df) > 1:
            with st.expander("📚 歷史報告"):
                for _, row in df.iloc[:-1].iloc[::-1].iterrows():
                    st.caption(f"📅 {row.get('日期','')} {row.get('更新時間','')}")
                    st.markdown(row.get("AI分析報告",""))
                    st.divider()

elif page == "📊 ETF 覆蓋分析":'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ AI 報告頁面加入成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
