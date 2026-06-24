import os
os.environ['SERPAPI_KEY'] = 'f3cac931b1aef6569aeb036181983d36c1f4207db625a404e6460ec6d108bdf5'
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from trends_fetcher import fetch_all_trends, compute_trends_signal
import traceback

try:
    raw = fetch_all_trends()
    signal = compute_trends_signal(raw)
    print('signal columns:', signal.columns.tolist())
    print('排名 in signal:', '排名' in signal.columns)
    print(signal.head(3))
except Exception as e:
    traceback.print_exc()
