with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '階段六.五：基本面資料' in line:
        print(f'找到第 {i+1} 行')
        insert = [
            '    # ── news 模式到此結束，inst 模式跑法人/基本面 ────────────\n',
            '    if RUN_MODE == \"news\":\n',
            '        log.info(\"RUN_MODE=news，新聞階段完成\")\n',
            '        log.info(\"===== 全部完成 =====\")\n',
            '        return\n',
            '\n',
        ]
        lines = lines[:i] + insert + lines[i:]
        print('✅ inst 判斷插入成功')
        break

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
