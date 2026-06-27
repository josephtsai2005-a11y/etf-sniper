with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''elif page == "新聞×籌碼交叉":
    st.title("🔗 新聞 × 籌碼 交叉驗證")
    st.caption("新聞題材發酵 + 法人同步建倉 = 高機率標的")
    cross_df = load_sheet(SHEET_CROSS)
    if cross_df.empty:
        st.warning("尚無交叉驗證資料（需累積新聞資料後自動產出）")
        st.stop()
    num_cols(cross_df, ["持有ETF數", "熱詞數", "最高成長率%"])
    st.info("💡 同時滿足「新聞題材發酵」+ 「多檔ETF持有」的個股，是最值得關注的標的")
    # 摘要
    c1, c2 = st.columns(2)
    c1.metric("題材+籌碼雙重確認", f"{len(cross_df)} 檔")
    c2.metric("高ETF共識(≥5檔)", f"{(pd.to_numeric(cross_df.get('持有ETF數',pd.Series()), errors='coerce') >= 5).sum()} 檔")
    st.divider()
    display_cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "訊號",
                    "相關熱詞", "熱詞數", "最高成長率%", "題材階段", "綜合強度"]'''

new = '''elif page == "新聞×籌碼交叉":
    st.title("新聞 × 籌碼 交叉驗證")
    st.caption("Claude AI 語意分析新聞 + ETF籌碼交叉 = 高機率標的")
    cross_df = load_sheet(SHEET_CROSS)
    if cross_df.empty:
        st.warning("尚無交叉驗證資料（每日 21:00 後更新）")
        st.stop()

    # 判斷是 AI 版還是舊版
    is_ai_version = "影響方向" in cross_df.columns

    if is_ai_version:
        st.success("✅ AI語意分析版本")
        # AI 版摘要
        pos = cross_df[cross_df.get("影響方向","") == "正面"] if "影響方向" in cross_df.columns else pd.DataFrame()
        neg = cross_df[cross_df.get("影響方向","") == "負面"] if "影響方向" in cross_df.columns else pd.DataFrame()
        high = cross_df[cross_df.get("影響程度","") == "高"] if "影響程度" in cross_df.columns else pd.DataFrame()
        c1, c2, c3 = st.columns(3)
        c1.metric("正面影響", f"{len(pos)} 筆")
        c2.metric("負面影響", f"{len(neg)} 筆")
        c3.metric("高度影響", f"{len(high)} 筆")
        st.divider()

        # 分組顯示
        st.subheader("正面影響標的")
        pos_df = cross_df[cross_df["影響方向"] == "正面"].copy() if "影響方向" in cross_df.columns else pd.DataFrame()
        if not pos_df.empty:
            avail = [c for c in ["股票代號","股票名稱","新聞摘要","影響程度","原因"] if c in pos_df.columns]
            st.dataframe(pos_df[avail].astype(str), use_container_width=True)

        st.subheader("負面影響標的（需注意）")
        neg_df = cross_df[cross_df["影響方向"] == "負面"].copy() if "影響方向" in cross_df.columns else pd.DataFrame()
        if not neg_df.empty:
            avail = [c for c in ["股票代號","股票名稱","新聞摘要","影響程度","原因"] if c in neg_df.columns]
            st.dataframe(neg_df[avail].astype(str), use_container_width=True)
        else:
            st.info("今日無負面影響標的")
    else:
        st.info("💡 同時滿足「新聞題材發酵」+「多檔ETF持有」的個股")
        c1, c2 = st.columns(2)
        c1.metric("題材+籌碼雙重確認", f"{len(cross_df)} 檔")
        c2.metric("高ETF共識(≥5檔)", f"{(pd.to_numeric(cross_df.get('持有ETF數',pd.Series()), errors='coerce') >= 5).sum()} 檔")
        st.divider()
        display_cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "訊號",
                    "相關熱詞", "熱詞數", "最高成長率%", "題材階段", "綜合強度"]'''

if old in content:
    content = content.replace(old, new)
    print('✅ 新聞×籌碼交叉頁面更新成功')
else:
    print('❌ 找不到')

# 加入題材總覽到選單
old2 = '    for p in ["新聞×籌碼交叉","題材趨勢","題材位置","散戶情緒"]:'
new2 = '    for p in ["新聞×籌碼交叉","題材總覽","散戶情緒"]:'

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ 選單更新成功')
else:
    print('❌ 選單找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
