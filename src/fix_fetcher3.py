with open('fetcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 fetch_all_etfs 內的呼叫加入 trade_date
old1 = '        df = fetch_etfinfo_holdings(code)\n        if not df.empty:'
new1 = '        df = fetch_etfinfo_holdings(code, trade_date=trade_date)\n        if not df.empty:'

count = content.count(old1)
print(f'找到 {count} 個匹配')
content = content.replace(old1, new1)

with open('fetcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('儲存完成')
