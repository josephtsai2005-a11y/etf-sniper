with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 TRADE_DATE 定義後加入 RUN_MODE
old = 'TRADE_DATE = os.environ.get("TRADE_DATE", _today_str)'
new = '''TRADE_DATE = os.environ.get("TRADE_DATE", _today_str)
RUN_MODE = os.environ.get("RUN_MODE", "core")  # core | inst | news'''

content = content.replace(old, new)

# 在 main() 裡階段五之前加判斷
old2 = '    # ── 階段五：新聞熱度收集與題材分析 ──────────────────────────'
new2 = '''    # ── 只有 news 模式才跑以下 ──────────────────────────────────
    if RUN_MODE not in ("news", "all"):
        log.info(f"RUN_MODE={RUN_MODE}，跳過新聞/Trends 階段")
        log.info("===== 全部完成 =====")
        return

    # ── 階段五：新聞熱度收集與題材分析 ──────────────────────────'''

content = content.replace(old2, new2)

# 在階段六.五之前加判斷（inst模式）
old3 = '    # ── 階段六.五：基本面資料（必須在法人之前！）──────────────────'
new3 = '''    # ── 只有 inst 或 all 模式才跑法人/基本面 ────────────────────
    if RUN_MODE == "news":
        log.info("RUN_MODE=news，跳過法人/基本面階段")
        log.info("===== 全部完成 =====")
        return

    # ── 階段六.五：基本面資料（必須在法人之前！）──────────────────'''

content = content.replace(old3, new3)

print('✅ RUN_MODE 拆分完成')
with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
