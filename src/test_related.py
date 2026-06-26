import os, sys
sys.path.insert(0, '.')
os.environ['ANTHROPIC_API_KEY'] = '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'

from ai_analyzer import call_claude

# 直接測試受惠股功能
prompt = """今日台股ETF重倉強勢股：
- 2345 智邦（網通/AI伺服器，11檔ETF持有）
- 3017 奇鋐（散熱/液冷，12檔ETF持有）
- 2330 台積電（先進製程/CoWoS，20檔ETF持有）

請推薦10檔相關受惠股（不在ETF持倉內，股價500元以下），說明與上述主題的關聯性。
格式：代號 名稱 | 關聯題材 | 股價區間 | 受益原因"""

result = call_claude(prompt, max_tokens=1000)
print(result)
