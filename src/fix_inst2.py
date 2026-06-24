f = open('institutional_fetcher.py', encoding='utf-8')
c = f.read()
f.close()
old = '        result["股票名稱"]   = filtered[name_col].astype(str).str.strip() if name_col else ""'
new = '        result["股票名稱"]   = filtered[name_col].astype(str).str.strip() if name_col else pd.Series("", index=filtered.index)'
if old in c:
    c = c.replace(old, new, 1)
    open('institutional_fetcher.py', 'w', encoding='utf-8').write(c)
    print('fixed')
else:
    print('not found')
