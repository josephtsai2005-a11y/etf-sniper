with open('trend_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''def match_keywords_to_stocks(
    trend_df: pd.DataFrame,
    smart_df: pd.DataFrame,
    stock_keyword_map: Optional[Dict] = None
) -> pd.DataFrame:
    """
    將新聞熱詞對應到個股
    stock_keyword_map: {股票代號: [相關關鍵字列表]}
    """
    if trend_df.empty or smart_df.empty:
        return pd.DataFrame()
    # 預設個股關鍵字對應表
    DEFAULT_MAP = {
        "2330": ["台積電法說", "先進製程", "CoWoS", "NVIDIA", "GB200", "HBM"],
        "2454": ["AI伺服器", "NVIDIA", "GB200", "先進製程"],
        "2383": ["CoWoS", "先進封裝", "先進製程"],
        "2308": ["電源管理", "AI伺服器", "電動車"],
        "6223": ["CoWoS", "先進封裝", "矽光子"],
        "3037": ["CoWoS", "先進封裝", "PCB"],
        "2327": ["被動元件", "電動車", "AI伺服器"],
        "2345": ["網通", "400G", "AI伺服器"],
        "3017": ["散熱", "AI伺服器", "液冷"],
        "6274": ["散熱", "AI伺服器", "液冷"],
        "2059": ["鉸鏈", "筆電", "AI PC"],
        "2368": ["MLCC", "被動元件", "電動車"],
        "5274": ["散熱", "AI伺服器"],
        "2360": ["IC設計", "電源管理"],
        "3711": ["封測", "先進封裝", "CoWoS"],
    }
    kw_map = stock_keyword_map or DEFAULT_MAP
    # 爆發/成長中的關鍵字
    hot_keywords = set(
        trend_df[trend_df["階段"].isin(["🔥 爆發", "⚡ 成長"])]["關鍵字"].tolist()
    )'''

new = '''def match_keywords_to_stocks(
    trend_df: pd.DataFrame,
    smart_df: pd.DataFrame,
    stock_keyword_map: Optional[Dict] = None
) -> pd.DataFrame:
    """
    將新聞熱詞對應到個股
    1. 直接用股票名稱比對新聞關鍵字（自動）
    2. 補充 DEFAULT_MAP 的產業關鍵字（手動）
    """
    if trend_df.empty or smart_df.empty:
        return pd.DataFrame()
    # 預設產業關鍵字對應表（補充用）
    DEFAULT_MAP = {
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
    kw_map = stock_keyword_map or DEFAULT_MAP
    # 所有關鍵字（不限階段）
    all_keywords = set(trend_df["關鍵字"].tolist())
    hot_keywords = set(
        trend_df[trend_df["階段"].isin(["🔥 爆發", "⚡ 成長", "🌱 萌芽"])]["關鍵字"].tolist()
    )'''

if old in content:
    content = content.replace(old, new)
    print('✅ 函數開頭修改成功')
else:
    print('❌ 找不到，嘗試部分匹配...')
    if 'DEFAULT_MAP' in content:
        print('DEFAULT_MAP 存在')

with open('trend_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
