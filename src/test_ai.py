import os, sys, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'
os.environ['ANTHROPIC_API_KEY'] = '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'

from sheets_writer import get_client, get_or_create_spreadsheet
from ai_analyzer import generate_investment_report, write_ai_report_to_sheets

client = get_client(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
ss = get_or_create_spreadsheet(client, os.environ['SPREADSHEET_ID'])

print('產生 AI 報告中...')
report = generate_investment_report(ss, '20260626')
print('=' * 50)
print(report)
print('=' * 50)

if report:
    write_ai_report_to_sheets(ss, report, '20260626')
    print('✅ 寫入完成')
