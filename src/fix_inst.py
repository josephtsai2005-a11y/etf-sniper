f = open('institutional_fetcher.py', encoding='utf-8')
c = f.read()
f.close()

# 完全重寫 fetch_batch_institutional 改用全市場一次抓取
old = '''def fetch_batch_institutional(
    stock_codes: list,
    trade_date: Optional[str] = None,
    delay: float = 0.4,
) -> pd.DataFrame:
    \"\"\"
    批次抓取多檔股票三大法人資料
    \"\"\"
    if not trade_date:
        trade_date = get_trade_date()

    records = []
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

new = '''def fetch_batch_institutional(
    stock_codes: list,
    trade_date: Optional[str] = None,
    delay: float = 0.4,
) -> pd.DataFrame:
    \"\"\"
    一次抓取全市場三大法人資料，再篩選需要的股票
    \"\"\"
    if not trade_date:
        trade_date = get_trade_date()

    url = "https://www.twse.com.tw/fund/TWT38U"
    params = {"response": "json", "date": trade_date, "selectType": "ALL"}

    try:
        resp = SESSION.get(url, params=params, timeout=20)
        data = resp.json()

        if data.get("stat") != "OK" or not data.get("data"):
            log.warning(f"三大法人全市場無資料 ({trade_date})")
            return pd.DataFrame()

        fields = data.get("fields", [])
        rows   = data.get("data", [])
        df = pd.DataFrame(rows, columns=fields)

        # 找代號欄
        code_col = next((c for c in df.columns if "代號" in c or "代碼" in c), None)
        if not code_col:
            log.warning("找不到股票代號欄")
            return pd.DataFrame()

        # 清洗代號（去除空白和星號）
        df[code_col] = df[code_col].astype(str).str.strip().str.replace("*","").str.strip()

        # 清洗數字欄
        for col in df.columns:
            if col != code_col:
                df[col] = df[col].astype(str).str.replace(",","").str.replace("+","").str.strip()
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 篩選需要的股票
        codes_set = set(str(c).strip() for c in stock_codes)
        filtered = df[df[code_col].isin(codes_set)].copy()
        filtered = filtered.rename(columns={code_col: "股票代號"})

        # 找三大法人欄位
        foreign_col  = next((c for c in filtered.columns if "外資" in c and "買賣" in c), None)
        trust_col    = next((c for c in filtered.columns if "投信" in c and "買賣" in c), None)
        dealer_col   = next((c for c in filtered.columns if "自營" in c and "買賣" in c), None)
        total_col    = next((c for c in filtered.columns if "合計" in c), None)
        name_col     = next((c for c in filtered.columns if "名稱" in c), None)

        result = pd.DataFrame()
        result["股票代號"]   = filtered["股票代號"]
        result["股票名稱"]   = filtered[name_col].astype(str).str.strip() if name_col else ""
        result["外資買賣超"] = pd.to_numeric(filtered[foreign_col], errors="coerce").fillna(0) if foreign_col else 0
        result["投信買賣超"] = pd.to_numeric(filtered[trust_col],   errors="coerce").fillna(0) if trust_col   else 0
        result["自營買賣超"] = pd.to_numeric(filtered[dealer_col],  errors="coerce").fillna(0) if dealer_col  else 0
        result["三大合計"]   = pd.to_numeric(filtered[total_col],   errors="coerce").fillna(0) if total_col   else 0
        result["抓取日期"]   = trade_date

        log.info(f"三大法人全市場：總計 {len(df)} 筆，篩選出 {len(result)} 檔")
        return result.reset_index(drop=True)

    except Exception as e:
        log.error(f"三大法人全市場失敗: {e}")
        return pd.DataFrame()'''

if old in c:
    c = c.replace(old, new, 1)
    open('institutional_fetcher.py', 'w', encoding='utf-8').write(c)
    print('SUCCESS')
else:
    print('ERROR: not found')
