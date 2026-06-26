import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet
from collections import Counter

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])
ws = ss.worksheet('新聞歷史庫')
vals = ws.get_all_values()
print(f'總行數: {len(vals)}')
dates = [r[0] for r in vals[1:] if r]
cnt = Counter(dates)
print(f'日期分布: {cnt.most_common(5)}')
