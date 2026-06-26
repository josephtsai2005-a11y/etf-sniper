with open('fetcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = 'def fetch_etfinfo_holdings(etf_code: str) -> pd.DataFrame:'
new = 'def fetch_etfinfo_holdings(etf_code: str, trade_date: str = None) -> pd.DataFrame:'

if old in content:
    content = content.replace(old, new)
    print('✅ 函數簽名修復')
else:
    print('❌ 找不到')

with open('fetcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
