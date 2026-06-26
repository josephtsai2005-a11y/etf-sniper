import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'
os.environ['ANTHROPIC_API_KEY'] = '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'

from sheets_writer import get_client, get_or_create_spreadsheet
client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])
ws = ss.worksheet('每日AI總結')
vals = ws.get_all_values()
if len(vals) >= 2:
    last = vals[-1]
    full = ''.join(last[2:])
    print(f'報告總長度: {len(full)} 字')
    print('--- 後半段 ---')
    print(full[-2000:])
