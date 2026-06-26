with open('ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''def write_ai_report_to_sheets(ss, report, trade_date):
    import time
    SHEET = "每日AI總結"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET not in existing:
        ws = ss.add_worksheet(title=SHEET, rows=1000, cols=3)
        ws.append_row(["日期", "更新時間", "AI分析報告"])
    else:
        ws = ss.worksheet(SHEET)
    now = datetime.now(TW_TZ).strftime("%H:%M")
    time.sleep(3)
    ws.append_row([trade_date, now, report])
    log.info(f"AI 報告寫入完成 ({trade_date})")'''

new = '''def write_ai_report_to_sheets(ss, report, trade_date):
    import time
    SHEET = "每日AI總結"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET not in existing:
        ws = ss.add_worksheet(title=SHEET, rows=1000, cols=4)
        ws.append_row(["日期", "更新時間", "AI分析報告（上）", "AI分析報告（下）"])
    else:
        ws = ss.worksheet(SHEET)
    now = datetime.now(TW_TZ).strftime("%H:%M")
    time.sleep(3)
    # 拆成兩半避免 Sheets 單格字數限制（50000字）
    mid = len(report) // 2
    # 找最近的換行點
    split_pos = report.rfind("\\n\\n", 0, mid + 500)
    if split_pos == -1:
        split_pos = mid
    part1 = report[:split_pos]
    part2 = report[split_pos:]
    ws.append_row([trade_date, now, part1, part2])
    log.info(f"AI 報告寫入完成 ({trade_date})")'''

if old in content:
    content = content.replace(old, new)
    print('✅ 寫入函數更新成功')
else:
    print('❌ 找不到')

with open('ai_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
