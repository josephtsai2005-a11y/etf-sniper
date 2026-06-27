with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在散戶情緒頁面前加入題材總覽
old = '''elif page == "散戶情緒":'''

new = '''elif page == "題材總覽":
    st.title("題材總覽")
    st.caption("ETF布局題材 × 新聞熱度 × 散戶情緒反向指標")
    df = load_sheet("題材總覽")
    if df.empty:
        st.warning("尚無題材總覽資料（每日 21:00 後更新）")
    else:
        # 顯示 AI 洞察
        if len(df) > 0 and "AI分析" in str(df.iloc[0].values):
            st.info(str(df.iloc[0].values[0]).replace("AI分析：",""))
            df = df.iloc[1:].reset_index(drop=True)
        # ETF有布局的題材
        etf_df = df[df.get("ETF布局數","0").astype(str) != "0"] if "ETF布局數" in df.columns else pd.DataFrame()
        if not etf_df.empty:
            st.subheader(f"ETF有布局的題材（{len(etf_df)} 個）")
            avail = [c for c in ["題材","階段","今日篇數","趨勢","散戶關注","進場訊號","ETF相關持股","ETF布局數"] if c in etf_df.columns]
            st.dataframe(etf_df[avail].astype(str), use_container_width=True)
        st.divider()
        st.subheader("所有題材")
        avail = [c for c in ["題材","階段","今日篇數","近3日均","趨勢","散戶關注","進場訊號"] if c in df.columns]
        st.dataframe(df[avail].astype(str), use_container_width=True)

elif page == "散戶情緒":'''

if old in content:
    content = content.replace(old, new, 1)
    print('✅ 題材總覽頁面加入成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
