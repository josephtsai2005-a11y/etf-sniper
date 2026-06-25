with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 _write_trends_to_sheets 的每次寫入之間加更長 sleep
old = '''        if not df.empty:
            time.sleep(2)
            ws.append_row(df.columns.tolist())
            rows = df.fillna("").values.tolist()
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"{sheet_name} 寫入完成")
        time.sleep(5)'''

new = '''        if not df.empty:
            time.sleep(5)
            ws.append_row(df.columns.tolist())
            time.sleep(3)
            rows = df.fillna("").values.tolist()
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"{sheet_name} 寫入完成")
        time.sleep(10)'''

if old in content:
    content = content.replace(old, new)
    print("✅ Trends sleep 加長成功")
else:
    print("❌ 找不到目標")

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
