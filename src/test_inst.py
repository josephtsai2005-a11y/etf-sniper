import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from institutional_fetcher import fetch_batch_institutional
stock_codes = ['2330','2454','2383','6223','2308','3037','3017','2327','2345']
print(f'抓取法人資料：{stock_codes}')
df = fetch_batch_institutional(stock_codes, '20260626')
print(f'結果：{len(df)} 筆')
if not df.empty:
    print(df.head())
else:
    print('❌ 無資料')
