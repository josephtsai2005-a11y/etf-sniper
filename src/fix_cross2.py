with open('trend_analyzer.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找函數開始和結束位置
start = None
end = None
for i, line in enumerate(lines):
    if 'def match_keywords_to_stocks' in line:
        start = i
    if start and i > start and 'hot_keywords = set(' in line:
        end = i + 3  # 包含接下來3行
        break

print(f'替換範圍: {start+1} ~ {end+1}')

new_block = [
    'def match_keywords_to_stocks(\n',
    '    trend_df: pd.DataFrame,\n',
    '    smart_df: pd.DataFrame,\n',
    '    stock_keyword_map: Optional[Dict] = None\n',
    ') -> pd.DataFrame:\n',
    '    """\n',
    '    將新聞熱詞對應到個股\n',
    '    1. 直接用股票名稱比對新聞關鍵字（自動）\n',
    '    2. 補充 DEFAULT_MAP 的產業關鍵字（手動）\n',
    '    """\n',
    '    if trend_df.empty or smart_df.empty:\n',
    '        return pd.DataFrame()\n',
    '    DEFAULT_MAP = {\n',
    '        "2330": ["台積電", "先進製程", "CoWoS", "NVIDIA", "GB200", "HBM"],\n',
    '        "2454": ["聯發科", "AI伺服器", "NVIDIA", "GB200"],\n',
    '        "2383": ["台光電", "CoWoS", "先進封裝"],\n',
    '        "2308": ["台達電", "電源管理", "AI伺服器", "電動車"],\n',
    '        "6223": ["旺矽", "CoWoS", "先進封裝", "矽光子"],\n',
    '        "3037": ["欣興", "CoWoS", "PCB"],\n',
    '        "2327": ["國巨", "被動元件", "電動車"],\n',
    '        "2345": ["智邦", "網通", "400G", "AI伺服器"],\n',
    '        "3017": ["奇鋐", "散熱", "AI伺服器", "液冷"],\n',
    '        "6274": ["台燿", "散熱", "AI伺服器"],\n',
    '        "2059": ["川湖", "鉸鏈", "筆電"],\n',
    '        "2368": ["金像電", "MLCC", "被動元件"],\n',
    '        "5274": ["信驊", "散熱", "AI伺服器"],\n',
    '        "2360": ["致茂", "IC設計", "電源管理"],\n',
    '        "3711": ["日月光", "封測", "先進封裝"],\n',
    '        "4958": ["臻鼎", "PCB", "AI伺服器"],\n',
    '        "6669": ["緯穎", "AI伺服器", "散熱"],\n',
    '        "2344": ["華邦電", "HBM", "記憶體"],\n',
    '        "8046": ["南電", "PCB", "先進封裝"],\n',
    '        "6187": ["萬潤", "散熱", "液冷"],\n',
    '    }\n',
    '    kw_map = stock_keyword_map or DEFAULT_MAP\n',
    '    # 所有關鍵字（包含萌芽階段）\n',
    '    hot_keywords = set(\n',
    '        trend_df[trend_df["階段"].isin(["🔥 爆發", "⚡ 成長", "🌱 萌芽"])]["關鍵字"].tolist()\n',
    '    )\n',
    '    # 同時加入：用股票名稱直接比對關鍵字\n',
    '    all_kw = set(trend_df["關鍵字"].tolist())\n',
]

lines = lines[:start] + new_block + lines[end:]

with open('trend_analyzer.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print(f'✅ 替換完成，共 {len(new_block)} 行')
