f = open('main.py', encoding='utf-8')
c = f.read()
f.close()
# 在第一個 import 後面加入 pandas
old = 'import os'
new = 'import os\nimport pandas as pd'
if 'import pandas as pd' not in c:
    c = c.replace(old, new, 1)
    open('main.py', 'w', encoding='utf-8').write(c)
    print('pandas import added')
else:
    print('already exists')
