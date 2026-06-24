f = open('app.py', encoding='utf-8')
c = f.read()
f.close()
old = '''        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🏦 三大法人",
        "📰 題材趨勢",
        "🔗 新聞×籌碼交叉",
        "📱 散戶情緒",
        "🎯 今日聰明錢名單",
        "📊 ETF 覆蓋分析",
        "📈 個股查詢",
        "🗂️ 原始持股庫",'''
new = '''        "🏆 多方驗證名單",
        "⚡ 今日訊號",
        "🎯 今日聰明錢名單",
        "🏦 三大法人",
        "📱 散戶情緒",
        "📰 題材趨勢",
        "🔗 新聞×籌碼交叉",
        "📊 ETF 覆蓋分析",
        "📈 個股查詢",
        "🗂️ 原始持股庫",'''
if old in c:
    c = c.replace(old, new, 1)
    open('app.py', 'w', encoding='utf-8').write(c)
    print('OK')
else:
    print('ERROR')
