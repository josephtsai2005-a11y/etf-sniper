import os, sys, time
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from fetcher import fetch_all_etfs
from sheets_writer import get_client, get_or_create_spreadsheet

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])
ws = ss.worksheet('盤後原始數據庫')

raw_cols = ['股票代號','股票名稱','權重%','持股數','ETF代碼','資料來源','抓取時間']

print('抓取 20260625...')
df = fetch_all_etfs('20260625')
print(f'筆數: {len(df)}')
avail = [c for c in raw_cols if c in df.columns]
rows = df[avail].fillna('').values.tolist()
print(f'準備寫入 {len(rows)} 筆...')
time.sleep(5)
ws.append_rows(rows, value_input_option='USER_ENTERED')
print('✅ 20260625 寫入完成！')
