f = open('main.py', encoding='utf-8')
c = f.read()
f.close()
# 找到 Google Trends 區段
idx = c.find('[7] 抓取 Google Trends')
print(c[idx:idx+800])
