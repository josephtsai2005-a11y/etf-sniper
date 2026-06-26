with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        report = latest.get("AI分析報告", "")
        st.caption(f"📅 {date} 更新：{time_str}")
        st.markdown(report)'''

new = '''        # 合併兩欄報告
        part1 = latest.get("AI分析報告（上）", latest.get("AI分析報告", ""))
        part2 = latest.get("AI分析報告（下）", "")
        report = part1 + part2
        st.caption(f"📅 {date} 更新：{time_str}")
        st.markdown(report)'''

if old in content:
    content = content.replace(old, new)
    print('✅ app.py 更新成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
