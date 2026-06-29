with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找基本面資料的 display_cols
old = '"股票代號","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"'
new = '"股票代號","股票名稱","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"'

if old in content:
    content = content.replace(old, new)
    print('✅ 完成')
else:
    print('❌ 找不到')
    # 找相關行
    for i, line in enumerate(content.split(chr(10))):
        if '月營收' in line and 'display' in content.split(chr(10))[max(0,i-2):i+1][-1]:
            print(f'  {i+1}: {line}')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
