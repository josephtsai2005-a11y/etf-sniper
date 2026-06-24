f = open('trends_fetcher.py', encoding='utf-8')
c = f.read()
f.close()

old = '    merged.insert(0, "排名", range(1, len(merged)+1))'
new = '    if "排名" in merged.columns:\n        merged = merged.drop(columns=["排名"])\n    merged.insert(0, "排名", range(1, len(merged)+1))'

if old in c:
    c = c.replace(old, new, 1)
    open('trends_fetcher.py', 'w', encoding='utf-8').write(c)
    print('SUCCESS')
else:
    print('ERROR: not found')
