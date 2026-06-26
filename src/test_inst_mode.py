import os, sys
sys.path.insert(0, '.')
os.environ['SPREADSHEET_ID'] = '1yQW-F-kXvVeVYyfSo_tgPYEbLI5dmCCX79KhzgEo92s'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'C:\Users\bubu_\Desktop\Hunt ETF AI\etf_sniper\secrets\gcp-sa.json'
os.environ['SERPAPI_KEY'] = 'f3cac931b1aef6569aeb036181983d36c1f4207db625a404e6460ec6d108bdf5'
os.environ['RUN_MODE'] = 'inst'

import main
main.main()
