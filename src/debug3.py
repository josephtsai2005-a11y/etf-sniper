import os
os.environ['SERPAPI_KEY'] = 'f3cac931b1aef6569aeb036181983d36c1f4207db625a404e6460ec6d108bdf5'
from trends_fetcher import fetch_all_trends, compute_trends_signal
from trend_analyzer import compute_keyword_timeseries, compute_trend_report
from news_fetcher import fetch_all_news, tag_articles
from trends_fetcher import cross_news_and_trends
import pandas as pd

# 模擬 main.py 的流程
trends_raw = fetch_all_trends()
trends_signal = compute_trends_signal(trends_raw)
print('1. trends_signal 排名:', '排名' in trends_signal.columns)

# 模擬新聞交叉
news_df = fetch_all_news(hours_back=26)
news_df = tag_articles(news_df)

import gspread
from google.oauth2.service_account import Credentials
creds = Credentials.from_service_account_file(
    r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json',
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)
ss = gspread.authorize(creds).open_by_key('1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s')

ws_news = ss.worksheet('新聞歷史庫')
vals = ws_news.get_all_values()
news_hist = pd.DataFrame(vals[1:], columns=vals[0]) if len(vals)>1 else pd.DataFrame()
print('2. news_hist rows:', len(news_hist))

pivot = compute_keyword_timeseries(news_hist)
news_trend = compute_trend_report(pivot)
print('3. news_trend 排名:', '排名' in news_trend.columns)

cross_df2 = cross_news_and_trends(news_trend, trends_signal)
print('4. cross_df2 排名:', '排名' in cross_df2.columns)
print('5. cross_df2 cols:', cross_df2.columns.tolist()[:5])

# 模擬寫入
ws = ss.worksheet('散戶情緒') if '散戶情緒' in [w.title for w in ss.worksheets()] else None
if ws:
    ws.clear()
    ws.append_row(['test'])
    import time; time.sleep(2)
    # 移除排名再寫入
    ts = trends_signal.copy()
    if '排名' in ts.columns: ts = ts.drop(columns=['排名'])
    ws.append_row(ts.columns.tolist())
    time.sleep(1)
    ws.append_rows(ts.fillna('').values.tolist())
    print('SUCCESS 散戶情緒')
