f = open('main.py', encoding='utf-8')
c = f.read()
f.close()

old = '                cross_df2 = cross_news_and_trends(news_trend2, trends_signal)'
new = '''                cross_df2 = cross_news_and_trends(news_trend2, trends_signal)
                # 強制移除重複排名欄
                cross_df2 = cross_df2.loc[:,~cross_df2.columns.duplicated()]
                if "排名" in cross_df2.columns:
                    cross_df2 = cross_df2.drop(columns=["排名"])'''

c = c.replace(old, new, 1)
open('main.py', 'w', encoding='utf-8').write(c)
print('fixed')
