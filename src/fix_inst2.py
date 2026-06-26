with open('institutional_fetcher.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找 fetch_batch_institutional 的內容起始行
start = None
end = None
for i, line in enumerate(lines):
    if 'records = []' in line and start is None:
        start = i
    if 'log.info(f"批次法人資料完成' in line:
        end = i
        break

print(f'替換範圍: {start+1} ~ {end+1}')

new_lines = [
    '    # 一次抓全市場再過濾\n',
    '    all_df = fetch_all_institutional(trade_date)\n',
    '    if all_df.empty:\n',
    '        log.warning("批次法人資料：無結果")\n',
    '        return pd.DataFrame()\n',
    '    codes = [str(c).strip() for c in stock_codes]\n',
    '    df = all_df[all_df["證券代號"].isin(codes)].copy()\n',
    '    df = df.rename(columns={"證券代號":"股票代號"})\n',
    '    log.info(f"批次法人資料完成：{len(df)}/{len(stock_codes)} 筆")\n',
    '    return df\n',
]

lines = lines[:start] + new_lines + lines[end+1:]

with open('institutional_fetcher.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('✅ 完成')
