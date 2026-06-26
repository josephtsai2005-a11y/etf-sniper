with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    # ── 階段四：每日差異比對 ────────────────────────────────────\n    log.info("[4/4] 執行每日差異比對...")'
new = '    # ── 階段四：每日差異比對（僅 core 模式）───────────────────────\n    log.info("[4/4] 執行每日差異比對...")\n    if RUN_MODE != "core":\n        log.info(f"RUN_MODE={RUN_MODE}，跳過差異比對")\n    else:'

if old in content:
    content = content.replace(old, new)
    # 縮排階段四的內容
    lines = content.split('\n')
    in_stage4 = False
    result = []
    for i, line in enumerate(lines):
        if '跳過差異比對' in line:
            in_stage4 = True
            result.append(line)
            continue
        if in_stage4 and line.startswith('    # ── 階段五'):
            in_stage4 = False
        if in_stage4 and line.strip():
            result.append('    ' + line)
        else:
            result.append(line)
    content = '\n'.join(result)
    print('✅ 階段四修改成功')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
