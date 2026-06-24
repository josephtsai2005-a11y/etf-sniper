f = open('main.py', encoding='utf-8')
c = f.read()
f.close()

# 只改這一行，其他不動
old = '                    cross_df2 = cross_news_and_trends(news_trend2, trends_signal)\n'
new = '                    cross_df2 = cross_news_and_trends(news_trend2, trends_signal)\n                    if not cross_df2.empty and "排名" in cross_df2.columns:\n                        cross_df2 = cross_df2.drop(columns=["排名"])\n'

if old in c:
    c = c.replace(old, new, 1)
    open('main.py', 'w', encoding='utf-8').write(c)
    print('SUCCESS: 只修改了一行')
else:
    print('ERROR: 找不到目標字串，main.py 未修改')
