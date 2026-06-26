import os, sys, time
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet
from diff_analyzer import load_history_from_sheets, compute_daily_diff, compute_fund_flow, aggregate_stock_diff
from main import _write_diff_to_sheets

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

print('讀取歷史資料...')
history_df = load_history_from_sheets(ss, days=5)
print(f'日期：{sorted(history_df["抓取時間"].unique())}')

today_df = history_df[history_df['抓取時間'] == '20260626'].copy()
print(f'6/26 資料：{len(today_df)} 筆')

diff_detail = compute_daily_diff(today_df, history_df, '20260626')
print(f'差異：{len(diff_detail)} 筆')

if not diff_detail.empty:
    stock_diff = aggregate_stock_diff(diff_detail)
    print(f'聚合：{len(stock_diff)} 檔有變動')
    time.sleep(3)
    _write_diff_to_sheets(ss, stock_diff, diff_detail, '20260626')
    print('✅ 持股異動明細寫入完成！')
