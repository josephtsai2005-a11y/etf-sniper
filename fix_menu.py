f = open('app.py', encoding='utf-8')
c = f.read()
f.close()

old = [
    '"etf-sniper-tw"',
]

# 找到 radio 的選項區段並重新排列
import re
pattern = r'(page = st\.radio\("頁面", \[)(.*?)(\])'

def reorder(m):
    items = re.findall(r'"[^"]*"', m.group(2))
    desired = [
        '"🏆 多方驗證名單"',
        '"⚡ 今日訊號"',
        '"🎯 今日聰明錢名單"',
        '"🏦 三大法人"',
        '"📰 題材趨勢"',
        '"🔗 新聞×籌碼交叉"',
        '"📊 ETF 覆蓋分析"',
        '"📈 個股查詢"',
        '"🗂️ 原始持股庫"',
    ]
    inner = ',\n        '.join(desired)
    return m.group(1) + '\n        ' + inner + ',\n    ' + m.group(3)

c = re.sub(pattern, reorder, c, flags=re.DOTALL)
open('app.py', 'w', encoding='utf-8').write(c)
print('done')
