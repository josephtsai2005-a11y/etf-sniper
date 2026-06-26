with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    # ── 階段三：寫入 Google Sheets ──────────────────────────
    log.info("[3/3] 寫入 Google Sheets...")
    try:
        client = get_client(CREDENTIALS_PATH)
        ss = get_or_create_spreadsheet(client, SPREADSHEET_ID)
        write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)
        log.info("Google Sheets 寫入完成！")'''

new = '''    # ── 階段三：寫入 Google Sheets（僅 core 模式）────────────
    log.info("[3/3] 寫入 Google Sheets...")
    try:
        client = get_client(CREDENTIALS_PATH)
        ss = get_or_create_spreadsheet(client, SPREADSHEET_ID)
        if RUN_MODE == "core":
            write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)
            log.info("Google Sheets 寫入完成！")
        else:
            log.info(f"RUN_MODE={RUN_MODE}，跳過聰明錢/盤後寫入")'''

if old in content:
    content = content.replace(old, new)
    print('✅ 階段三修改成功')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
