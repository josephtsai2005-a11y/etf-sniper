with open('trend_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在檔案最後加入反向對應表
reverse_map = '''

# 反向對應表：關鍵字 → 相關股票代號列表
DEFAULT_MAP_REVERSE = {}
_DEFAULT_MAP = {
    "2330": ["台積電", "先進製程", "CoWoS", "NVIDIA", "GB200", "HBM"],
    "2454": ["聯發科", "AI伺服器", "NVIDIA", "GB200"],
    "2383": ["台光電", "CoWoS", "先進封裝"],
    "2308": ["台達電", "電源管理", "AI伺服器", "電動車"],
    "6223": ["旺矽", "CoWoS", "先進封裝", "矽光子"],
    "3037": ["欣興", "CoWoS", "PCB"],
    "2327": ["國巨", "被動元件", "電動車"],
    "2345": ["智邦", "網通", "400G", "AI伺服器"],
    "3017": ["奇鋐", "散熱", "AI伺服器", "液冷"],
    "6274": ["台燿", "散熱", "AI伺服器"],
    "2059": ["川湖", "鉸鏈", "筆電"],
    "2368": ["金像電", "MLCC", "被動元件"],
    "5274": ["信驊", "散熱", "AI伺服器"],
    "2360": ["致茂", "IC設計", "電源管理"],
    "3711": ["日月光", "封測", "先進封裝"],
    "4958": ["臻鼎", "PCB", "AI伺服器"],
    "6669": ["緯穎", "AI伺服器", "散熱"],
    "2344": ["華邦電", "HBM", "記憶體"],
    "8046": ["南電", "PCB", "先進封裝"],
    "6187": ["萬潤", "散熱", "液冷"],
}
for code, kws in _DEFAULT_MAP.items():
    for kw in kws:
        if kw not in DEFAULT_MAP_REVERSE:
            DEFAULT_MAP_REVERSE[kw] = []
        DEFAULT_MAP_REVERSE[kw].append(code)
'''

content = content + reverse_map
print('✅ DEFAULT_MAP_REVERSE 加入成功')

with open('trend_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
