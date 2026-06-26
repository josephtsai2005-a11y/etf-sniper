with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修正：core只跑核心，inst跑法人基本面，news跑新聞
old = '''    # ── 只有 news 模式才跑以下 ──────────────────────────────────
    if RUN_MODE not in ("news", "all"):
        log.info(f"RUN_MODE={RUN_MODE}，跳過新聞/Trends 階段")
        log.info("===== 全部完成 =====")
        return
    # ── 階段五：新聞熱度收集與題材分析 ──────────────────────────'''

new = '''    # ── core 模式到此結束 ───────────────────────────────────────
    if RUN_MODE == "core":
        log.info("RUN_MODE=core，核心階段完成")
        log.info("===== 全部完成 =====")
        return

    # ── 階段五：新聞熱度收集與題材分析（news 模式）──────────────
    if RUN_MODE == "news":
        log.info("[5/5] 收集財經新聞 + 題材生命週期分析...")'''

if old in content:
    content = content.replace(old, new)
    print('✅ core 模式修正成功')
else:
    print('❌ 找不到目標')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
