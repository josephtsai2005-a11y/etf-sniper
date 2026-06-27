with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'elif page == "新聞×籌碼交叉":' in line:
        start = i
        print(f'找到第 {i+1} 行')
        break

# 找結束位置（下一個 elif）
for i, line in enumerate(lines[start+1:], start+1):
    if line.startswith('elif page') or line.startswith('# 頁面'):
        end = i
        print(f'結束第 {i+1} 行')
        break

new_block = '''elif page == "新聞×籌碼交叉":
    st.title("新聞 × 籌碼 交叉驗證")
    st.caption("Claude AI 語意分析新聞 + ETF籌碼交叉 = 高機率標的")
    cross_df = load_sheet(SHEET_CROSS)
    if cross_df.empty:
        st.warning("尚無交叉驗證資料（每日 21:00 後更新）")
        st.stop()

    is_ai_version = "影響方向" in cross_df.columns

    if is_ai_version:
        st.success("✅ AI語意分析版本")
        pos = cross_df[cross_df["影響方向"] == "正面"] if "影響方向" in cross_df.columns else pd.DataFrame()
        neg = cross_df[cross_df["影響方向"] == "負面"] if "影響方向" in cross_df.columns else pd.DataFrame()
        high = cross_df[cross_df["影響程度"] == "高"] if "影響程度" in cross_df.columns else pd.DataFrame()
        c1, c2, c3 = st.columns(3)
        c1.metric("正面影響", f"{len(pos)} 筆")
        c2.metric("負面影響", f"{len(neg)} 筆")
        c3.metric("高度影響", f"{len(high)} 筆")
        st.divider()
        st.subheader("正面影響標的")
        if not pos.empty:
            avail = [c for c in ["股票代號","股票名稱","新聞摘要","影響程度","原因"] if c in pos.columns]
            st.dataframe(pos[avail].astype(str), use_container_width=True)
        st.subheader("負面影響標的（需注意）")
        if not neg.empty:
            avail = [c for c in ["股票代號","股票名稱","新聞摘要","影響程度","原因"] if c in neg.columns]
            st.dataframe(neg[avail].astype(str), use_container_width=True)
        else:
            st.info("今日無負面影響標的")
    else:
        st.info("💡 同時滿足「新聞題材發酵」+「多檔ETF持有」的個股")
        st.dataframe(cross_df.astype(str), use_container_width=True)

'''

lines = lines[:start] + [new_block] + lines[end:]
with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('✅ 完成')
