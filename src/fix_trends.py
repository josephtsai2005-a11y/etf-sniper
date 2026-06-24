f = open('trends_fetcher.py', encoding='utf-8')
c = f.read()
f.close()
old = '    df.insert(0, "排名", range(1, len(df)+1))\n    return df'
new = '    if "排名" not in df.columns:\n        df.insert(0, "排名", range(1, len(df)+1))\n    return df'
c = c.replace(old, new)
open('trends_fetcher.py', 'w', encoding='utf-8').write(c)
print('fixed:', c.count('if \"排名\" not in'))
