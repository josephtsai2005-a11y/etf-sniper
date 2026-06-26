import requests, pandas as pd

# 一次抓全市場
params = {"response": "json", "date": "20260626", "selectType": "ALL"}
resp = requests.get("https://www.twse.com.tw/fund/TWT38U", params=params, timeout=15)
data = resp.json()

fields = data.get("fields", [])
rows = data.get("data", [])
df = pd.DataFrame(rows, columns=fields)
print(f'欄位: {fields}')
print(f'筆數: {len(df)}')
print(df.head(3))

# 過濾目標股票
targets = ['2330','2454','2383','6223','2308']
# 找證券代號欄
code_col = [c for c in df.columns if '代號' in c or '代碼' in c]
print(f'代號欄: {code_col}')
