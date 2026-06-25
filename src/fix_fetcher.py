with open('fetcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '                "抓取時間": datetime.now(__import__("pytz").timezone("Asia/Taipei")).strftime("%Y%m%d"),'
new = '                "抓取時間": trade_date if trade_date else datetime.now(__import__("pytz").timezone("Asia/Taipei")).strftime("%Y%m%d"),'

if old in content:
    content = content.replace(old, new)
    print('✅ fetcher.py 修復成功')
else:
    print('❌ 找不到目標')

with open('fetcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
