import os, sys, time
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet
from diff_analyzer import compute_daily_diff, compute_fund_flow, aggregate_stock_diff
from main import _write_diff_to_sheets
import pandas as pd

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

ws = ss.worksheet('盤後原始數據庫')
vals = ws.get_all_values()
headers = vals[0]
all_df = pd.DataFrame(vals[1:], columns=headers)

# 統一日期格式
all_df['抓取時間'] = all_df['抓取時間'].str.replace('-','')

print(f'日期: {sorted(all_df["抓取時間"].unique())}')

# 6/30 vs 6/27
today_df = all_df[all_df['抓取時間'] == '20260630'].copy()
hist_df = all_df[all_df['抓取時間'].isin(['20260627','20260626','20260625'])].copy()
print(f'今日: {len(today_df)}, 歷史: {len(hist_df)}')

diff_detail = compute_daily_diff(today_df, hist_df, '20260630')
print(f'差異: {len(diff_detail)} 筆')

if not diff_detail.empty:
    stock_diff = aggregate_stock_diff(diff_detail)
    print(f'聚合: {len(stock_diff)} 檔')
    time.sleep(3)
    _write_diff_to_sheets(ss, stock_diff, diff_detail, '20260630')
    print('✅ 6/30 持股異動寫入完成')
else:
    print('❌ 無差異')
