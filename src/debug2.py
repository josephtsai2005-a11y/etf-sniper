import os, sys
os.environ['SERPAPI_KEY'] = 'f3cac931b1aef6569aeb036181983d36c1f4207db625a404e6460ec6d108bdf5'
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'
os.environ['TZ'] = 'Asia/Taipei'

sys.path.insert(0, '.')
from trends_fetcher import fetch_all_trends, compute_trends_signal, cross_news_and_trends
from trend_analyzer import compute_keyword_timeseries, compute_trend_report
import pandas as pd
import traceback
import gspread
from google.oauth2.service_account import Credentials

creds = Credentials.from_service_account_file(
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']
)
client = gspread.authorize(creds)
ss = client.open_by_key(os.environ['SPREADSHEET_ID'])

try:
    trends_raw = fetch_all_trends()
    trends_signal = compute_trends_signal(trends_raw)
    print('trends_signal cols:', trends_signal.columns.tolist())
    
    ws = ss.worksheet('散戶情緒') if '散戶情緒' in [w.title for w in ss.worksheets()] else ss.add_worksheet('散戶情緒', 500, 15)
    ws.clear()
    ws.append_row(['test'])
    import time; time.sleep(2)
    ws.append_row(trends_signal.columns.tolist())
    time.sleep(2)
    rows = trends_signal.fillna('').values.tolist()
    ws.append_rows(rows)
    print('SUCCESS')
except Exception as e:
    traceback.print_exc()
