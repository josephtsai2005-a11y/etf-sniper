with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到目標行
for i, line in enumerate(lines):
    if '只有 news 模式才跑以下' in line:
        print(f'找到第 {i+1} 行: {line.rstrip()}')
        # 替換這行和下面3行
        lines[i]   = '    # ── core 模式到此結束 ───────────────────────────────────────\n'
        lines[i+1] = '    if RUN_MODE == \"core\":\n'
        lines[i+2] = '        log.info(\"RUN_MODE=core，核心階段完成\")\n'
        lines[i+3] = '        log.info(\"===== 全部完成 =====\")\n'
        lines[i+4] = '        return\n'
        print('✅ 替換成功')
        break

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
