import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'
os.environ['ANTHROPIC_API_KEY'] = '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'

from news_fetcher import fetch_all_news, tag_articles
from fetcher import fetch_all_etfs, aggregate_smart_money
from ai_analyzer import analyze_news_impact
import requests, json

# 抓資料
news_df = fetch_all_news(hours_back=26)
news_df = tag_articles(news_df)
raw_df = fetch_all_etfs('20260627')
smart_df = aggregate_smart_money(raw_df)

print(f'新聞: {len(news_df)} 篇')
print(f'股票: {len(smart_df)} 檔')

# 直接測試 API 呼叫
titles = news_df['標題'].dropna().head(80).tolist()
news_str = '\n'.join([f'- {t}' for t in titles])
stocks = smart_df[['股票代號','股票名稱']].head(30).drop_duplicates()
stock_str = '\n'.join([f'{r["股票代號"]} {r["股票名稱"]}' for _, r in stocks.iterrows()])

key = os.environ['ANTHROPIC_API_KEY']
headers = {'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
body = {
    'model': 'claude-sonnet-4-6',
    'max_tokens': 2000,
    'messages': [{'role': 'user', 'content': f'新聞:\n{news_str[:500]}\n\n股票:\n{stock_str}\n\n只回傳JSON分析影響'}],
}
resp = requests.post('https://api.anthropic.com/v1/messages', headers=headers, json=body, timeout=30)
data = resp.json()
print(f'status: {resp.status_code}')
print(f'keys: {list(data.keys())}')
if 'content' in data:
    print(f'content type: {data["content"][0]["type"]}')
    print(data['content'][0]['text'][:200])
else:
    print(data)
