import os, json, logging, requests, pandas as pd
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"

def call_claude(prompt, system="", max_tokens=2000):
    api_key = os.environ.get("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY).strip()
    if not api_key:
        log.warning("缺少 ANTHROPIC_API_KEY")
        return ""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=60)
        data = resp.json()
        if resp.status_code != 200:
            log.error(f"Claude API 失敗 (status={resp.status_code}): {data}")
            return ""
        return data["content"][0]["text"]
    except Exception as e:
        log.error(f"Claude API 呼叫異常: {e}")
        return ""

def collect_all_data(ss):
    data = {}
    sheets = {"聰明錢名單":20,"今日訊號":30,"持股異動明細":30,"三大法人":20,"多方驗證名單":20,"基本面資料":20,"題材趨勢":15,"新聞x籌碼交叉":15,"散戶情緒":10,"題材位置":15}
    for name, n in sheets.items():
        try:
            ws = ss.worksheet(name)
            vals = ws.get_all_values()
            if len(vals) >= 2:
                df = pd.DataFrame(vals[2:], columns=vals[1]) if len(vals) > 2 else pd.DataFrame()
                data[name] = df.head(n)
            else:
                data[name] = pd.DataFrame()
        except Exception as e:
            log.warning(f"讀取 {name} 失敗: {e}")
            data[name] = pd.DataFrame()
    return data

def format_data_for_ai(data, trade_date):
    sections = []
    def rows(df, cols, n=10):
        lines = []
        for _, r in df.head(n).iterrows():
            lines.append("  " + " | ".join(f"{c}:{r.get(c,'')}" for c in cols if c in r))
        return "\n".join(lines)

    df = data.get("聰明錢名單", pd.DataFrame())
    if not df.empty:
        sections.append("【聰明錢名單 Top10】\n" + rows(df, ["排名","股票代號","股票名稱","持有ETF數","訊號","收盤價","漲跌幅%"]))

    df = data.get("今日訊號", pd.DataFrame())
    if not df.empty:
        sections.append("【今日籌碼異動】\n" + rows(df, ["股票代號","股票名稱","主要狀態","加碼ETF數","新增ETF數"]))

    df = data.get("三大法人", pd.DataFrame())
    if not df.empty:
        sections.append("【三大法人】\n" + rows(df, ["股票代號","外資買賣超","投信買賣超","自營買賣超","三大合計","法人訊號"]))
    else:
        sections.append("【三大法人】\n  ⚠️ 資料未取得（可能尚未更新或抓取失敗）")

    df = data.get("多方驗證名單", pd.DataFrame())
    if not df.empty:
        sections.append("【多方驗證名單】\n" + rows(df, ["股票代號","股票名稱","持有ETF數","買超法人數","綜合評分","多方驗證"]))
    else:
        sections.append("【多方驗證名單】\n  ⚠️ 資料未取得")

    df = data.get("基本面資料", pd.DataFrame())
    if not df.empty:
        sections.append("【基本面資料】\n" + rows(df, ["股票代號","月營收(億)","年增率%","營收訊號","本益比","本益比訊號"]))
    else:
        sections.append("【基本面資料】\n  ⚠️ 資料未取得")

    df = data.get("題材趨勢", pd.DataFrame())
    if not df.empty:
        sections.append("【題材趨勢】\n" + rows(df, ["關鍵字","階段","今日篇數","趨勢"], 8))

    df = data.get("散戶情緒", pd.DataFrame())
    if not df.empty:
        sections.append("【散戶情緒反向指標】\n" + rows(df, ["主題","散戶關注度","進場訊號"], 5))

    return f"交易日：{trade_date}\n\n" + "\n\n".join(sections)


def generate_related_stocks(smart_df: pd.DataFrame, trend_df: pd.DataFrame) -> str:
    """獨立呼叫：產生產業輪動受惠股推薦"""
    if smart_df.empty:
        return ""

    # 準備強勢股資料
    top_stocks = []
    for _, row in smart_df.head(10).iterrows():
        top_stocks.append(f"- {row.get('股票代號','')} {row.get('股票名稱','')}（{row.get('持有ETF數','')}檔ETF持有，訊號：{row.get('訊號','')}）")
    stocks_str = "\n".join(top_stocks)

    # 準備題材資料
    themes = []
    if not trend_df.empty and "關鍵字" in trend_df.columns:
        themes = trend_df.head(5)["關鍵字"].tolist()
    themes_str = "、".join(themes) if themes else "AI伺服器、半導體、散熱"

    prompt = f"""今日台股ETF主動式基金重倉強勢股：
{stocks_str}

今日熱門題材：{themes_str}

請推薦10檔產業輪動受惠股（這些股票不在ETF持倉內，但可能因產業輪動受益）：

條件：
1. 優先選股價在500元以下的標的
2. 必須與上述強勢股的產業主題直接相關
3. 說明與主力題材的關聯性

請用以下格式回覆：
### 🔄 產業輪動受惠股（10檔）

| 排名 | 代號 | 名稱 | 關聯題材 | 股價區間 | 受益原因 |
|------|------|------|----------|----------|----------|
| 1 | XXXX | XXX | XXX | XXX元以下 | XXX |
...

注意：以上僅供參考，非買賣建議。"""

    return call_claude(prompt, max_tokens=1500)


def analyze_news_impact(news_df, smart_df):
    """Claude 直接分析新聞對個股的影響（語意理解，不用關鍵字）"""
    if news_df.empty or smart_df.empty:
        return pd.DataFrame()

    titles = news_df["標題"].dropna().head(80).tolist()
    news_str = "\n".join([f"- {t}" for t in titles])

    stocks = smart_df[["股票代號","股票名稱"]].head(30).drop_duplicates()
    stock_str = "\n".join([f"{r['股票代號']} {r['股票名稱']}" for _, r in stocks.iterrows()])

    prompt = f"""你是台灣股市分析師。請分析以下新聞對台股個股的影響。

今日財經新聞標題：
{news_str}

ETF重倉股票清單：
{stock_str}

請分析每則重要新聞對上述股票的影響，只回傳 JSON，格式如下：
{{"影響清單": [{{"新聞摘要": "20字內", "影響股票": ["代號1"], "影響方向": "正面/負面/中性", "影響程度": "高/中/低", "原因": "30字內"}}]}}

規則：只列有明確影響的新聞，影響股票只列清單內代號，最多15則，只回傳JSON。"""

    result = call_claude(prompt, max_tokens=2000)
    if not result:
        return pd.DataFrame()

    try:
        result = result.strip().replace("`json","").replace("`","")
        data = json.loads(result)

        # 支援多種 JSON 格式
        impacts = (data.get("影響清單") or 
                   data.get("news_stock_impact") or 
                   data.get("impacts") or 
                   data.get("analysis") or [])

        rows = []
        for item in impacts:
            # 支援多種欄位名稱
            affected = (item.get("影響股票") or 
                       item.get("affected_stocks") or [])
            
            news_summary = (item.get("新聞摘要") or 
                           item.get("news","")[:30])
            direction = (item.get("影響方向") or 
                        item.get("impact_direction","中性"))
            degree = (item.get("影響程度") or 
                     item.get("impact_level","中"))
            reason = (item.get("原因") or 
                     item.get("reason",""))

            for stock in affected:
                # 支援字串或字典格式
                if isinstance(stock, dict):
                    code = str(stock.get("code",""))
                    stock_name = stock.get("name","")
                    reason2 = stock.get("reason", reason)
                else:
                    code = str(stock)
                    stock_name = ""
                    reason2 = reason

                if not stock_name:
                    name_match = smart_df[smart_df["股票代號"].astype(str)==code]["股票名稱"].values
                    stock_name = name_match[0] if len(name_match) > 0 else ""

                rows.append({
                    "股票代號": code,
                    "股票名稱": stock_name,
                    "新聞摘要": news_summary,
                    "影響方向": direction,
                    "影響程度": degree,
                    "原因": reason2,
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            order = {"高":0,"中":1,"低":2}
            df["_sort"] = df["影響程度"].map(order).fillna(3)
            df = df.sort_values(["影響方向","_sort"]).drop(columns=["_sort"])
        log.info(f"AI新聞影響分析完成：{len(df)} 筆")
        return df
    except Exception as e:
        log.warning(f"AI新聞影響解析失敗: {e}")
        import traceback
        log.debug(traceback.format_exc())
        return pd.DataFrame()

def generate_investment_report(ss, trade_date, us_market_text=""):
    log.info("收集所有分頁資料...")
    data = collect_all_data(ss)
    data_text = format_data_for_ai(data, trade_date)
    us_section = f"\n\n【美股市場參考（僅供參考）】\n{us_market_text}" if us_market_text else ""

    system_prompt = """你是一位擁有20年經驗的台灣股市專業基金經理人。

核心能力：
1. 以台灣本土籌碼為主要判斷依據（ETF持倉、三大法人、外資動向）
2. 美股和國際市場只是參考，不是決定因素
3. 深知台股有自己的邏輯：政策面、產業供應鏈、外資匯率、題材輪動
4. 能辨別哪些美股走勢真正影響台股，哪些只是雜訊

判斷原則：
- 台股籌碼 > 美股走勢
- 法人動向 > 散戶情緒  
- 基本面趨勢 > 短期價格波動
- 有時美股大漲，台股因外資匯出反而下跌
- 有時美股下跌，台股因內資撐盤反而抗跌

誠實原則（最重要）：
- 資料不足時，明確說明缺少哪個維度及對判斷的影響
- 訊號不明確時，誠實說明，不強行推薦
- 寧可說「資料不足，建議觀望」也不做無根據推薦
- 對每個推薦標的，標示哪些面向有資料支撐，哪些缺失

分析風格：繁體中文，專業但易懂，有數據支撐"""

    prompt = f"""請根據以下今日市場資料，在ETF已選出的股票中找出最有潛力的標的。

所有標的都來自主動式ETF持倉，已經過專業經理人篩選。
你的任務：在這些股票中進一步找出「今日最有潛力」的3-5檔。

潛力評分標準（權重由高到低）：
1. ETF籌碼集中度（幾檔持有？權重多高？今日加碼？）
2. 三大法人同向買超
3. 基本面支撐（月營收年增率、本益比）
4. 題材發酵程度（萌芽/成長期更好）
5. 散戶冷淡但法人積極＝最佳布局時機
6. 美股連動（需確認台股籌碼同步）

{data_text}{us_section}

## 📊 {trade_date} ETF狙擊系統每日報告

### 🎯 今日市場總結
（2-3句，以台股籌碼為核心）

### 🏆 今日最具潛力標的（Top 3-5）
每檔提供：
- 代號與名稱
- 各維度評分（ETF籌碼/法人/基本面/題材）
- 關鍵優勢
- 資料缺失說明（如有）
- 風險與觀察訊號

### 📊 籌碼面分析

### 🔥 題材面分析

### 🌏 美股影響評估

### ⚠️ 風險提示

### 💡 明日觀察清單（3-5點）

### 🔄 產業輪動受惠股（10檔）
基於今日ETF重倉股的產業主題，推薦10檔相關但股價較低的受惠股。
這些股票不在ETF持倉內，但可能因產業輪動受益。

針對每檔提供：
- 股票代號與名稱
- 與主力題材的關聯性（為什麼會受益）
- 股價區間參考（相對主力股更親民）
- 風險提示

注意：
- 優先選股價在 500 元以下的標的
- 必須與今日強勢題材直接相關
- 說明是供參考，非買賣建議
- 若無足夠依據，寧可少推薦

報告約 900-1200 字。若資料不足請明確說明，不要強行推薦。"""

    log.info("呼叫 Claude API 產生主報告...")
    main_report = call_claude(prompt, system=system_prompt, max_tokens=2000)

    # 獨立呼叫產生受惠股
    log.info("呼叫 Claude API 產生受惠股推薦...")
    smart_df = data.get("聰明錢名單", pd.DataFrame())
    trend_df = data.get("題材趨勢", pd.DataFrame())
    related = generate_related_stocks(smart_df, trend_df)

    return main_report + "\n\n" + related if related else main_report

def write_ai_report_to_sheets(ss, report, trade_date):
    import time
    SHEET = "每日AI總結"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET not in existing:
        ws = ss.add_worksheet(title=SHEET, rows=1000, cols=4)
        ws.append_row(["日期", "更新時間", "AI分析報告（上）", "AI分析報告（下）"])
    else:
        ws = ss.worksheet(SHEET)
    now = datetime.now(TW_TZ).strftime("%H:%M")
    time.sleep(3)
    # 拆成兩半避免 Sheets 單格字數限制（50000字）
    mid = len(report) // 2
    # 找最近的換行點
    split_pos = report.rfind("\n\n", 0, mid + 500)
    if split_pos == -1:
        split_pos = mid
    part1 = report[:split_pos]
    part2 = report[split_pos:]
    ws.append_row([trade_date, now, part1, part2])
    log.info(f"AI 報告寫入完成 ({trade_date})")

def generate_stock_keywords(smart_df, news_df):
    if smart_df.empty or news_df.empty:
        return {}
    stocks = smart_df[["股票代號","股票名稱"]].head(30).values.tolist()
    stock_str = "\n".join([f"{c} {n}" for c, n in stocks])
    titles = news_df["標題"].dropna().head(50).tolist()
    news_str = "\n".join(titles)
    prompt = f"""台灣股市ETF重倉股票：
{stock_str}

今日財經新聞標題：
{news_str}

只回傳 JSON，不要其他文字：
{{"股票代號": ["關鍵字1", "關鍵字2"]}}
每檔最多5個關鍵字，只列有明確相關性的股票。"""
    result = call_claude(prompt, max_tokens=1000)
    if not result:
        return {}
    try:
        return json.loads(result.strip().replace("```json","").replace("```",""))
    except Exception as e:
        log.warning(f"關鍵字解析失敗: {e}")
        return {}
