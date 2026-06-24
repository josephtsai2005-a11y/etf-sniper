f = open('app.py', encoding='utf-8')
c = f.read()
f.close()

# Fix load_sheet to handle sheets with title row
old = '        # 找欄位標題行（含「排名」或「股票代號」的那行）\n        header_idx = 0\n        for i, row in enumerate(all_values[:5]):\n            row_text = " ".join(str(c) for c in row)\n            if any(k in row_text for k in ["排名", "股票代號", "股票名稱", "代號"]):\n                header_idx = i\n                break'
new = '        # 找欄位標題行（含關鍵欄位名稱的那行）\n        header_idx = 0\n        for i, row in enumerate(all_values[:5]):\n            row_text = " ".join(str(c) for c in row)\n            if any(k in row_text for k in ["排名", "股票代號", "股票名稱", "代號", "主題", "關鍵字", "散戶關注度", "法人訊號"]):\n                header_idx = i\n                break'

if old in c:
    c = c.replace(old, new, 1)
    open('app.py', 'w', encoding='utf-8').write(c)
    print('fixed')
else:
    print('not found')
