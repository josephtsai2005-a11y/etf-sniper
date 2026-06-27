import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

for name in ['題材趨勢', '題材位置', '新聞x籌碼交叉']:
    try:
        ws = ss.worksheet(name)
        vals = ws.get_all_values()
        print(f'{name}: {len(vals)} 行')
        if vals:
            print(f'  欄位: {vals[0]}')
            if len(vals) > 1:
                print(f'  第一筆: {vals[1][:5]}')
    except Exception as e:
        print(f'{name}: 錯誤 {e}')
    print()
