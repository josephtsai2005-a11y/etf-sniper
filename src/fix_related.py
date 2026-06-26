with open('ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '### 💡 明日觀察清單（3-5點）\n\n報告約 700-900 字。若資料不足請明確說明，不要強行推薦。"""'

new = '''### 💡 明日觀察清單（3-5點）

### 🔄 產業輪動受惠股（10檔）
基於今日ETF重倉股的產業主題，推薦10檔相關但股價較低的受惠股。
這些股票不在ETF持倉內，但可能因產業輪動受益。

針對每檔提供：
- 股票代號與名稱
- 與主力題材的關聯性（為什麼會受益）
- 股價區間參考（相對主力股更親民）
- 風險提示

注意：
- 優先選股價在 500 元以下的標的
- 必須與今日強勢題材直接相關
- 說明是供參考，非買賣建議
- 若無足夠依據，寧可少推薦

報告約 900-1200 字。若資料不足請明確說明，不要強行推薦。"""'''

if old in content:
    content = content.replace(old, new)
    print('✅ 受惠股推薦加入成功')
else:
    print('❌ 找不到')

with open('ai_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
