with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 load_sheet 函數後加入補充名稱的輔助函數
old = 'def num_cols('
new = '''def enrich_with_name(df, smart_df=None):
    """從聰明錢名單補入股票名稱"""
    if "股票名稱" in df.columns and df["股票名稱"].astype(str).str.strip().ne("").any():
        return df
    if smart_df is None:
        smart_df = load_sheet("聰明錢名單")
    if not smart_df.empty and "股票代號" in smart_df.columns and "股票名稱" in smart_df.columns:
        name_map = smart_df.set_index("股票代號")["股票名稱"].to_dict()
        df["股票名稱"] = df["股票代號"].astype(str).map(name_map).fillna("")
    return df

def num_cols('''

if old in content:
    content = content.replace(old, new)
    print('✅ enrich_with_name 加入')
else:
    print('❌ 找不到')

# 修復基本面資料頁面
old2 = '''    df = load_sheet("基本面資料")
    if df.empty:
        st.warning("尚無基本面資料（每日 16:45 後更新）")
    else:
        display_cols = ["股票代號","股票名稱","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"]
        avail = [c for c in display_cols if c in df.columns]
        st.dataframe(df[avail].astype(str), use_container_width=True)'''

new2 = '''    df = load_sheet("基本面資料")
    if df.empty:
        st.warning("尚無基本面資料（每日 16:45 後更新）")
    else:
        df = enrich_with_name(df)
        display_cols = ["股票代號","股票名稱","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"]
        avail = [c for c in display_cols if c in df.columns]
        st.dataframe(df[avail].astype(str), use_container_width=True)'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ 基本面補名稱')
else:
    print('❌ 基本面找不到')

# 修復三大法人頁面
old3 = '''    num_cols(inst_df, ["外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數"])'''
new3 = '''    inst_df = enrich_with_name(inst_df)
    num_cols(inst_df, ["外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數"])'''

if old3 in content:
    content = content.replace(old3, new3)
    print('✅ 三大法人補名稱')
else:
    print('❌ 三大法人找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
