import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from fetcher import fetch_all_etfs
from sheets_writer import get_client, get_or_create_spreadsheet
import time

print('抓取資料...')
raw_df = fetch_all_etfs('20260625')
print(f'筆數: {len(raw_df)}')
print(f'欄位: {raw_df.columns.tolist()}')

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])
ws = ss.worksheet('盤後原始數據庫')

all_vals = ws.get_all_values()
print(f'現有行數: {len(all_vals)}')

raw_cols = ['股票代號','股票名稱','權重%','持股數','ETF代碼','資料來源','抓取時間']
avail = [c for c in raw_cols if c in raw_df.columns]
print(f'可用欄位: {avail}')

# 檢查是否已有今日資料
dates = [r[avail.index('抓取時間')] for r in all_vals[1:] if len(r) > avail.index('抓取時間')]
print(f'現有日期: {set(dates)}')
