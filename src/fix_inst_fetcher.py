with open('institutional_fetcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 fetch_batch_institutional 前加入新函數
new_func = '''
def fetch_all_institutional(trade_date: Optional[str] = None) -> pd.DataFrame:
    """一次抓全市場三大法人，再過濾目標股票（比逐一抓取快且穩定）"""
    if not trade_date:
        trade_date = get_trade_date()
    url = "https://www.twse.com.tw/fund/TWT38U"
    params = {"response": "json", "date": trade_date, "selectType": "ALL"}
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            log.warning(f"三大法人全市場無資料 ({trade_date})")
            return pd.DataFrame()
        rows = data.get("data", [])
        # 欄位重新命名（外資/投信/自營各有買進/賣出/買賣超）
        cols = ["序號","證券代號","證券名稱",
                "外資買進","外資賣出","外資買賣超",
                "投信買進","投信賣出","投信買賣超",
                "自營買進","自營賣出","自營買賣超"]
        df = pd.DataFrame(rows, columns=cols)
        # 清洗數字
        for col in ["外資買賣超","投信買賣超","自營買賣超"]:
            df[col] = df[col].astype(str).str.replace(",","").str.replace("+","")
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["三大合計"] = df["外資買賣超"] + df["投信買賣超"] + df["自營買賣超"]
        df["證券代號"] = df["證券代號"].astype(str).str.strip()
        df["抓取日期"] = trade_date
        log.info(f"三大法人全市場：{len(df)} 筆 ({trade_date})")
        return df
    except Exception as e:
        log.error(f"三大法人全市場失敗: {e}")
        return pd.DataFrame()

'''

# 插入在 fetch_batch_institutional 前
old = 'def fetch_batch_institutional('
content = content.replace(old, new_func + 'def fetch_batch_institutional(', 1)

# 修改 fetch_batch_institutional 改用新函數
old2 = '''    records = []
    total = len(stock_codes)
    for i, code in enumerate(stock_codes, 1):
        result = fetch_institutional_by_stock(str(code), trade_date)
        if result:
            records.append(result)
        if i % 10 == 0:
            log.info(f"  法人資料進度 {i}/{total}")
        time.sleep(delay)
    if not records:
        log.warning("批次法人資料：無結果")
        return pd.DataFrame()
    df = pd.DataFrame(records)
    log.info(f"批次法人資料完成：{len(df)}/{total} 筆")
    return df'''

new2 = '''    # 一次抓全市場再過濾
    all_df = fetch_all_institutional(trade_date)
    if all_df.empty:
        log.warning("批次法人資料：無結果")
        return pd.DataFrame()
    codes = [str(c).strip() for c in stock_codes]
    df = all_df[all_df["證券代號"].isin(codes)].copy()
    df = df.rename(columns={"證券代號":"股票代號"})
    log.info(f"批次法人資料完成：{len(df)}/{len(stock_codes)} 筆")
    return df'''

if old2 in content:
    content = content.replace(old2, new2)
    print('✅ fetch_batch_institutional 修改成功')
else:
    print('❌ 找不到目標')

with open('institutional_fetcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
