import requests
params = {"response": "json", "date": "20260626", "selectType": "ALL"}
resp = requests.get("https://www.twse.com.tw/fund/TWT38U", params=params, timeout=15)
data = resp.json()
print(f'stat: {data.get("stat")}')
print(f'資料筆數: {len(data.get("data", []))}')
print(f'第一筆: {data.get("data", [[]])[0][:3] if data.get("data") else "無"}')
