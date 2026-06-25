import os, sys, time
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])
ws = ss.worksheet('盤後原始數據庫')

# 找到抓取時間欄（G欄=第7欄）
all_vals = ws.get_all_values()
print(f'現有行數: {len(all_vals)}')

# 找出所有 20260626 的行（585行之後）
rows_to_fix = []
for i, row in enumerate(all_vals[1:], start=2):
    if len(row) >= 7 and row[6] == '20260626':
        rows_to_fix.append(i)

print(f'需要修正的行數: {len(rows_to_fix)}，從第{rows_to_fix[0] if rows_to_fix else "?"}行')

# 批次更新 G 欄為 20260625
if rows_to_fix:
    updates = []
    for row_num in rows_to_fix:
        updates.append({
            'range': f'G{row_num}',
            'values': [['20260625']]
        })
    # 每次最多 100 個
    for i in range(0, len(updates), 100):
        batch = updates[i:i+100]
        ws.batch_update(batch)
        time.sleep(2)
        print(f'已更新 {min(i+100, len(updates))}/{len(updates)} 行')

print('✅ 抓取時間修正完成！')
