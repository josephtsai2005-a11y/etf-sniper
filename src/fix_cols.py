with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '            raw_cols = ["股票代號","股票名稱","ETF代碼","ETF名稱","持股數(張)","持股比例%","抓取時間"]'
new = '            raw_cols = ["股票代號","股票名稱","權重%","持股數","ETF代碼","資料來源","抓取時間"]'

if old in content:
    content = content.replace(old, new)
    print("✅ 欄位修復成功")
else:
    print("❌ 找不到，印出現有欄位行")
    for i, line in enumerate(content.split(chr(10))):
        if 'raw_cols' in line:
            print(f"  行{i+1}: {line}")

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
