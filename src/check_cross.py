import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet
from main import _load_news_history
from trend_analyzer import compute_keyword_timeseries, compute_trend_report, match_keywords_to_stocks
import pandas as pd

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

news_history = _load_news_history(ss)
print(f'新聞歷史: {len(news_history)} 筆')

pivot = compute_keyword_timeseries(news_history)
trend_df = compute_trend_report(pivot)
print(f'題材趨勢: {len(trend_df)} 個關鍵字')

smart_df = pd.DataFrame({'股票代號':['2330','2454','2383'],'股票名稱':['台積電','聯發科','台光電']})
cross_df = match_keywords_to_stocks(trend_df, smart_df)
print(f'新聞x籌碼交叉: {len(cross_df)} 筆')
print(cross_df.head())
