with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    # ── 階段七：Google Trends 散戶情緒 ──────────────────────────\n    log.info("[7] 抓取 Google Trends 散戶情緒...")'

new = '    # ── 階段七：Google Trends 散戶情緒（僅 news 模式）────────────\n    if RUN_MODE == "inst":\n        log.info("RUN_MODE=inst，跳過 Google Trends")\n    else:\n        log.info("[7] 抓取 Google Trends 散戶情緒...")'

if old in content:
    content = content.replace(old, new)
    print("✅ 成功")
else:
    print("❌ 找不到")
    # 找實際內容
    for i, line in enumerate(content.split(chr(10))):
        if "階段七" in line:
            print(f"{i+1}: {line}")

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
