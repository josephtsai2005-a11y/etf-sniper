with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# inst 和 news 模式跳過階段一~三的寫入，直接讀 Sheets
old = '''    # ── 階段一：採集 34 檔 ETF ──────────────────────────────
    log.info("[1/3] 抓取 34 檔主動式 ETF 持股...")
    raw_df = fetch_all_etfs(TRADE_DATE)

    if raw_df.empty:
        msg = f"[{TRADE_DATE}] 無資料（可能非交易日）"
        log.warning(msg)
        send_line_notify(f"\\n⚠️ {msg}")
        sys.exit(0)'''

new = '''    # ── 階段一：採集 34 檔 ETF ──────────────────────────────
    log.info("[1/3] 抓取 34 檔主動式 ETF 持股...")

    if RUN_MODE in ("inst", "news"):
        # inst/news 模式：直接從 Sheets 讀取今日資料，不重新抓取
        log.info(f"RUN_MODE={RUN_MODE}，從 Sheets 讀取今日資料...")
        _client0 = get_client(CREDENTIALS_PATH)
        _ss0 = get_or_create_spreadsheet(_client0, SPREADSHEET_ID)
        raw_df = load_history_from_sheets(_ss0, days=1)
        raw_df = raw_df[raw_df["抓取時間"] == TRADE_DATE].copy() if not raw_df.empty else pd.DataFrame()
        if raw_df.empty:
            log.warning(f"Sheets 無 {TRADE_DATE} 資料，改為重新抓取")
            raw_df = fetch_all_etfs(TRADE_DATE)
    else:
        raw_df = fetch_all_etfs(TRADE_DATE)

    if raw_df.empty:
        msg = f"[{TRADE_DATE}] 無資料（可能非交易日）"
        log.warning(msg)
        send_line_notify(f"\\n⚠️ {msg}")
        sys.exit(0)'''

if old in content:
    content = content.replace(old, new)
    print('✅ 階段一修改成功')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
