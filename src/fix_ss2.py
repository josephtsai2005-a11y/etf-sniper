with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '        else:\n            log.info(f"RUN_MODE={RUN_MODE}，跳過聰明錢/盤後寫入")'
new = '        else:\n            log.info(f"RUN_MODE={RUN_MODE}，跳過聰明錢/盤後寫入")\n        # inst/news 模式也需要 ss2\n        if RUN_MODE != "core":\n            import time as _t2; _t2.sleep(5)\n            client2 = get_client(CREDENTIALS_PATH)\n            ss2 = get_or_create_spreadsheet(client2, SPREADSHEET_ID)'

if old in content:
    content = content.replace(old, new)
    print('✅ ss2 修復成功')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
