with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到問題區域
for i, line in enumerate(lines):
    if '階段四：每日差異比對' in line:
        start = i
        print(f'找到第 {i+1} 行')
        break

# 找到階段五
for i, line in enumerate(lines):
    if '階段五：新聞' in line:
        end = i
        print(f'階段五第 {i+1} 行')
        break

print(f'階段四範圍: {start+1} ~ {end}')

# 替換整個階段四
new_stage4 = '''    # ── 階段四：每日差異比對（僅 core 模式）───────────────────────
    if RUN_MODE != "core":
        log.info(f"RUN_MODE={RUN_MODE}，跳過差異比對")
    else:
        log.info("[4/4] 執行每日差異比對...")
        try:
            client2 = get_client(CREDENTIALS_PATH)
            ss2 = get_or_create_spreadsheet(client2, SPREADSHEET_ID)
            history_df = load_history_from_sheets(ss2, days=2)
            if history_df.empty:
                log.warning("歷史資料不足，跳過差異比對（需要兩天資料）")
            else:
                diff_detail = compute_daily_diff(raw_df, history_df, TRADE_DATE)
                if not diff_detail.empty:
                    if "收盤價" in smart_df.columns:
                        price_ref = smart_df[["股票代號","收盤價"]].drop_duplicates()
                        diff_detail = compute_fund_flow(diff_detail, price_ref)
                    stock_diff = aggregate_stock_diff(diff_detail)
                    _write_diff_to_sheets(ss2, stock_diff, diff_detail, TRADE_DATE)
                    log.info(f"差異比對完成：{len(stock_diff)} 檔有變動")
                else:
                    log.warning("差異比對無結果")
        except Exception as e:
            log.warning(f"差異比對失敗（不影響主流程）: {e}")

'''

lines = lines[:start] + [new_stage4] + lines[end:]

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('✅ 階段四修復完成')
