import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet
from diff_analyzer import load_history_from_sheets, compute_daily_diff, compute_fund_flow, aggregate_stock_diff
import pandas as pd

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

print('讀取歷史資料...')
history_df = load_history_from_sheets(ss, days=3)
print(f'歷史資料：{len(history_df)} 筆，日期：{history_df["抓取時間"].unique() if not history_df.empty else "無"}')

from fetcher import fetch_all_etfs
print('抓取 6/25 資料...')
raw_df = fetch_all_etfs('20260625')
print(f'今日資料：{len(raw_df)} 筆')

diff_detail = compute_daily_diff(raw_df, history_df, '20260625')
print(f'差異比對結果：{len(diff_detail)} 筆')

if not diff_detail.empty:
    stock_diff = aggregate_stock_diff(diff_detail)
    print(f'聚合後：{len(stock_diff)} 檔有變動')
    
    # 寫入 Sheets
    import time
    from main import _write_diff_to_sheets
    time.sleep(3)
    _write_diff_to_sheets(ss, stock_diff, diff_detail, '20260625')
    print('✅ 持股異動明細寫入完成！')
