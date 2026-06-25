with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在聰明錢寫入完成後，加入盤後原始數據庫 append
old = '''        write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)
        log.info("Google Sheets 寫入完成！")
    except Exception as e:
        log.error(f"Sheets 寫入失敗: {e}")
        sys.exit(1)'''

new = '''        write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)
        log.info("Google Sheets 寫入完成！")

        # ── 追加盤後原始數據庫 ──
        try:
            ws_raw = ss.worksheet("盤後原始數據庫")
            all_vals = ws_raw.get_all_values()
            raw_cols = ["股票代號","股票名稱","ETF代碼","ETF名稱","持股數(張)","持股比例%","抓取時間"]
            avail = [c for c in raw_cols if c in raw_df.columns]
            if not all_vals or all_vals == [[]]:
                ws_raw.append_row(avail)
            today_dates = [r[avail.index("抓取時間")] if "抓取時間" in avail else "" for r in all_vals[1:]]
            if TRADE_DATE not in today_dates:
                import time
                time.sleep(3)
                rows = raw_df[avail].fillna("").values.tolist()
                ws_raw.append_rows(rows, value_input_option="USER_ENTERED")
                log.info(f"盤後原始數據庫追加完成：{len(rows)} 筆 ({TRADE_DATE})")
            else:
                log.info(f"盤後原始數據庫已有 {TRADE_DATE} 資料，跳過")
        except Exception as e:
            log.warning(f"盤後原始數據庫寫入失敗（不影響主流程）: {e}")
    except Exception as e:
        log.error(f"Sheets 寫入失敗: {e}")
        sys.exit(1)'''

if old in content:
    content = content.replace(old, new)
    print('✅ 盤後原始數據庫寫入已加入')
else:
    print('❌ 找不到目標區塊')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('儲存完成')
