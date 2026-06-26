import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'

from sheets_writer import get_client, get_or_create_spreadsheet

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

existing = [ws.title for ws in ss.worksheets()]

sheets_to_create = {
    '三大法人': ['排名','股票代號','外資買賣超','投信買賣超','自營買賣超','三大合計','買超法人數','法人訊號'],
    '多方驗證名單': ['排名','股票代號','股票名稱','持有ETF數','買超法人數','法人訊號','綜合評分','多方驗證','三大合計','收盤價','漲跌幅%'],
}

for name, headers in sheets_to_create.items():
    if name not in existing:
        ws = ss.add_worksheet(title=name, rows=1000, cols=20)
        ws.append_row([f'{name} - 每日 16:30 後更新'])
        ws.append_row(headers)
        print(f'✅ 建立分頁：{name}')
    else:
        print(f'已存在：{name}')
