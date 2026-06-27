import os, sys, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'
os.environ['ANTHROPIC_API_KEY'] = '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'
os.environ['SERPAPI_KEY'] = 'f3cac931b1aef6569aeb036181983d36c1f4207db625a404e6460ec6d108bdf5'
os.environ['RUN_MODE'] = 'news'

import main
main.main()
