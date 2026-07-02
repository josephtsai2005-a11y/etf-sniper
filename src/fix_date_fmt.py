with open('diff_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        df = df[df.apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)]
        # 找日期欄
        date_col = next((c for c in df.columns if "日期" in c or "抓取" in c), None)
        if not date_col:
            return df
        dates = sorted(df[date_col].unique())[-days:]
        return df[df[date_col].isin(dates)].copy()'''

new = '''        df = df[df.apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)]
        # 找日期欄
        date_col = next((c for c in df.columns if "日期" in c or "抓取" in c), None)
        if not date_col:
            return df
        # 統一日期格式（移除橫線）
        df[date_col] = df[date_col].astype(str).str.replace("-","")
        dates = sorted(df[date_col].unique())[-days:]
        return df[df[date_col].isin(dates)].copy()'''

if old in content:
    content = content.replace(old, new)
    print('✅ 日期格式修復成功')
else:
    print('❌ 找不到')

with open('diff_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
