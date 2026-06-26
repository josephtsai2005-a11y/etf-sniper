with open('trend_analyzer.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找 records = [] 那行
for i, line in enumerate(lines):
    if 'records = []' in line and i > 140:
        start = i
        break

# 找 if not records 那行
for i, line in enumerate(lines):
    if 'if not records:' in line and i > 140:
        end = i
        break

print(f'替換範圍: {start+1} ~ {end}')

new_block = [
    '    records = []\n',
    '    for _, stock_row in smart_df.iterrows():\n',
    '        code = str(stock_row.get("股票代號", ""))\n',
    '        name = str(stock_row.get("股票名稱", ""))\n',
    '        # 1. DEFAULT_MAP 關鍵字\n',
    '        related_kws = list(kw_map.get(code, []))\n',
    '        # 2. 股票名稱直接比對（自動）\n',
    '        for kw in all_kw:\n',
    '            if name and len(name) >= 2 and name in kw:\n',
    '                if kw not in related_kws:\n',
    '                    related_kws.append(kw)\n',
    '        matched_hot = [kw for kw in related_kws if kw in hot_keywords]\n',
    '        if matched_hot:\n',
    '            matched_trends = trend_df[trend_df["關鍵字"].isin(matched_hot)]\n',
    '            max_growth = matched_trends["成長率%"].max() if not matched_trends.empty else 0\n',
    '            stages = matched_trends["階段"].tolist()\n',
    '            records.append({\n',
    '                "股票代號":    code,\n',
    '                "股票名稱":    name,\n',
    '                "持有ETF數":  stock_row.get("持有ETF數", 0),\n',
    '                "訊號":       stock_row.get("訊號", ""),\n',
    '                "相關熱詞":   " / ".join(matched_hot),\n',
    '                "熱詞數":     len(matched_hot),\n',
    '                "最高成長率%": round(max_growth, 1),\n',
    '                "題材階段":   " / ".join(set(stages)),\n',
    '                "綜合強度":   f"籌碼({\'✅\' if int(stock_row.get(\'持有ETF數\',0)) >= 5 else \'⚪\'}) "\n',
    '                              f"題材({\'✅\' if matched_hot else \'⚪\'})",\n',
    '            })\n',
]

lines = lines[:start] + new_block + lines[end:]

with open('trend_analyzer.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('✅ records 替換完成')
