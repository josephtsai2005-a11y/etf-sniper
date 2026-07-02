with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在階段五開始前，inst 模式直接跳過
old = '    log.info("[5/5] 收集財經新聞 + 題材生命週期分析...")'
new = '''    # inst 模式跳過新聞，直接跑法人
    if RUN_MODE == "inst":
        log.info("RUN_MODE=inst，跳過新聞階段，直接跑法人")
    else:
        log.info("[5/5] 收集財經新聞 + 題材生命週期分析...")'''

if old in content:
    content = content.replace(old, new)
    print('✅ inst跳過新聞')
else:
    print('❌ 找不到')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
