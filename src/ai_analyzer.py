import os, json, logging, requests, pandas as pd
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"

def _append_truncation_warning(text: str, data: dict) -> str:
    """
    如果Claude API回應是因為撞到max_tokens上限被截斷（stop_reason == "max_tokens"），
    在文字結尾加上明顯警示，讓呼叫端/UI/Sheets存檔都能看到，不會讓使用者誤以為這是
    一份完整、AI自然結束的分析。

    2026-10-06新增：使用者反映一份籌碼分析報告在小節「3.」標題後面整段消失，但畫面
    照常顯示「分析完成」、照常存檔——查出來是call_claude_vision()的max_tokens設太低
    （1000），AI寫到一半被截斷，但回傳的文字本身看起來就是正常字串，程式完全無從
    分辨「AI本來就寫這麼短」跟「AI被攔腰截斷」，使用者也無從察覺。改成讀取API回應的
    stop_reason欄位（Anthropic官方文件：撞到max_tokens上限時固定回傳"max_tokens"），
    偵測到就附加警示，call_claude()跟call_claude_vision()共用這個helper，兩邊都有
    同樣的截斷風險（結構完全相同，差別只在有沒有帶圖片）。
    """
    if data.get("stop_reason") == "max_tokens":
        log.warning("Claude API 回應被 max_tokens 截斷，已於文字結尾附加警示")
        return text + "\n\n⚠️ **（以上內容因長度限制被截斷，可能沒有寫完，建議重新分析一次）**"
    return text


def call_claude(prompt, system="", max_tokens=2000, retries=2):
    """
    呼叫Claude API，含重試機制。
    2026-08-26曾發生RemoteDisconnected(連線被對方中斷)導致整份AI報告失敗、
    Sheets/Streamlit都完全沒有當天資料的事故——這是偶發性網路問題，不是邏輯錯誤，
    原本完全沒有重試，一次連線失敗就整份報告放棄，改成失敗後間隔等待再試，
    大幅降低單次網路不穩定就導致整份報告消失的機率。
    """
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

    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=120)
            data = resp.json()
            if resp.status_code != 200:
                log.error(f"Claude API 失敗 (status={resp.status_code}): {data}")
                # 額度不足(400)、認證錯誤等重試也沒用，直接放棄；其他狀態碼才重試
                if resp.status_code in (400, 401, 403):
                    return ""
                last_error = f"status={resp.status_code}"
                if attempt < retries:
                    import time as _time
                    wait = 5 * (attempt + 1)
                    log.warning(f"Claude API重試中（第{attempt+1}次，{wait}秒後）...")
                    _time.sleep(wait)
                    continue
                return ""
            return _append_truncation_warning(data["content"][0]["text"], data)
        except Exception as e:
            last_error = e
            if attempt < retries:
                import time as _time
                wait = 5 * (attempt + 1)
                log.warning(f"Claude API呼叫異常，{wait}秒後重試（第{attempt+1}次）: {e}")
                _time.sleep(wait)
                continue
            log.error(f"Claude API 呼叫異常（已重試{retries}次，放棄）: {e}")
            return ""
    return ""


def call_claude_vision(prompt, images, system="", max_tokens=1000, retries=2):
    """
    呼叫Claude API並附帶一張或多張圖片（例如券商分點截圖），供2026-09-16新增的
    broker_branch_analyzer.py使用。與call_claude()共用同一套重試/錯誤處理邏輯，
    差異只在content多帶image區塊——image區塊放在text前面是Anthropic官方建議的順序，
    實測對圖片判讀品質比較穩定。

    2026-09-16追加：原本只接受單一張圖片（image_b64, media_type兩個獨立參數），
    使用者實際使用時發現常常需要一次給「統計結果截圖」+「買賣超走勢線圖」兩張畫面
    才能完整判讀（純數字表格看不出動能是加速還是趨緩，要搭配線圖）。改成images參數
    接受(base64字串, media_type)的tuple list，多張圖片依序放在text前面，是同一種
    「圖片在前、問題在後」的建議順序，只是圖片數量從固定1張變成可以是多張。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY).strip()
    if not api_key:
        log.warning("缺少 ANTHROPIC_API_KEY")
        return ""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}}
        for image_b64, media_type in images
    ]
    content.append({"type": "text", "text": prompt})
    body = {"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
    if system:
        body["system"] = system

    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=120)
            data = resp.json()
            if resp.status_code != 200:
                log.error(f"Claude API(圖片) 失敗 (status={resp.status_code}): {data}")
                # 額度不足(400)、認證錯誤等重試也沒用，直接放棄；其他狀態碼才重試
                if resp.status_code in (400, 401, 403):
                    return ""
                last_error = f"status={resp.status_code}"
                if attempt < retries:
                    import time as _time
                    wait = 5 * (attempt + 1)
                    log.warning(f"Claude API(圖片)重試中（第{attempt+1}次，{wait}秒後）...")
                    _time.sleep(wait)
                    continue
                return ""
            return _append_truncation_warning(data["content"][0]["text"], data)
        except Exception as e:
            last_error = e
            if attempt < retries:
                import time as _time
                wait = 5 * (attempt + 1)
                log.warning(f"Claude API(圖片)呼叫異常，{wait}秒後重試（第{attempt+1}次）: {e}")
                _time.sleep(wait)
                continue
            log.error(f"Claude API(圖片) 呼叫異常（已重試{retries}次，放棄）: {e}")
            return ""
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


def build_affordable_picks_section(cross_df: pd.DataFrame, max_price: float = 1000.0, top_n: int = 8) -> str:
    """
    產生「1000元以下優選股清單」段落——純資料篩選，不呼叫AI，零額外成本
    來源：既有ETF持股（多方驗證名單），已經有完整ETF共識/法人/技術面驗證，
    只是重新用「股價上限」篩選+排序，讓資金有限的散戶也能參考

    跟 generate_related_stocks（產業輪動受惠股）的差異：
      - 這裡的股票「有」ETF實際持股驗證（比較可靠，但受限於現有追蹤ETF覆蓋範圍）
      - 產業輪動受惠股是AI推論的「延伸」名單，沒有ETF驗證（範圍更廣，但可靠度較低）
      - 兩者互補，各自標明資料來源與可靠度差異，避免使用者混淆
    """
    if cross_df is None or cross_df.empty or "收盤價" not in cross_df.columns:
        return ""

    df = cross_df.copy()
    df["收盤價"] = pd.to_numeric(df["收盤價"], errors="coerce")
    df["綜合評分"] = pd.to_numeric(df.get("綜合評分"), errors="coerce")

    affordable = df[(df["收盤價"] <= max_price) & (df["收盤價"] > 0)].copy()
    if affordable.empty:
        return f"### 💰 {max_price:.0f}元以下優選股清單（ETF實際持股驗證）\n\n（今日追蹤股票池中無{max_price:.0f}元以下標的）"

    affordable = affordable.sort_values("綜合評分", ascending=False).head(top_n)

    lines = [
        f"### 💰 {max_price:.0f}元以下優選股清單（ETF實際持股驗證，非AI推論）",
        "",
        "| 股票代號 | 股票名稱 | 收盤價 | 綜合評分 | 持有ETF數 | 法人訊號 | 技術面共振 | 融資訊號 |",
        "|---------|---------|--------|---------|----------|---------|-----------|---------|",
    ]
    for _, row in affordable.iterrows():
        lines.append(
            f"| {row.get('股票代號','')} | {row.get('股票名稱','')} | {row.get('收盤價','')} | "
            f"{row.get('綜合評分','')} | {row.get('持有ETF數','')} | {row.get('法人訊號','')} | "
            f"{row.get('技術面共振','')} | {row.get('融資訊號','') or '—'} |"
        )
    lines.append("")
    lines.append("💡 這份清單直接來自你現有追蹤的主動式ETF實際持股，經過完整ETF共識+法人+技術面驗證，"
                  "可靠度高於下方「產業輪動受惠股」（AI推論、無ETF驗證），但範圍受限於現有ETF覆蓋的股票池。")

    return "\n".join(lines)


def generate_related_stocks(smart_df: pd.DataFrame, trend_df: pd.DataFrame) -> str:
    """
    獨立呼叫：產生產業輪動受惠股推薦
    設計重點：AI只負責「找出哪些股票、為什麼相關」這種需要推理的部分；
    股價是客觀事實，不讓AI憑訓練記憶猜（AI訓練資料有時間差，猜的股價常常跟現在差很多，
    容易誤導使用者），改成AI生成完候選股票代號後，用price_fetcher即時查真實股價替換，
    不花額外AI成本（只是多幾次TWSE查詢）
    """
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
1. 優先選你認知中股價落在1000元以下區間的標的（目標是讓資金有限的散戶也能實際參與，避免全部推薦高價股；
   但這只是初步篩選方向，不需要在回覆裡標注確切股價，股價欄位會由系統另外即時查詢補上，不用你猜）
2. 必須與上述強勢股的產業主題直接相關
3. 說明與主力題材的關聯性

請用以下格式回覆，股價欄位留空或填「查詢中」即可，不要自己猜測數字：
### 🔄 產業輪動受惠股（10檔，1000元以下優先）

| 排名 | 代號 | 名稱 | 關聯題材 | 股價區間 | 受益原因 |
|------|------|------|----------|----------|----------|
| 1 | XXXX | XXX | XXX | 查詢中 | XXX |
...

注意：以上為AI依產業關聯推論，非ETF實際持股驗證過的標的，僅供參考，非買賣建議。"""

    raw_result = call_claude(prompt, max_tokens=1500)
    if not raw_result:
        return raw_result

    return _replace_prices_with_live_data(raw_result)


def _replace_prices_with_live_data(markdown_table: str) -> str:
    """
    把AI生成表格裡的股票代號抓出來，逐一用price_fetcher即時查真實股價，
    取代AI自己猜（或留空）的股價欄位，避免顯示過期/幻覺出來的錯誤數字
    """
    import re
    try:
        from price_fetcher import get_stock_price_single
    except Exception as e:
        log.warning(f"股價即時替換功能無法載入price_fetcher: {e}")
        return markdown_table

    lines = markdown_table.split("\n")
    new_lines = []
    for line in lines:
        # 比對表格資料列格式： | 排名 | 代號 | 名稱 | 關聯題材 | 股價區間 | 受益原因 |
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 7:
            new_lines.append(line)
            continue
        code_candidate = cells[2]
        if not re.fullmatch(r"\d{4,6}[A-Z]?", code_candidate):
            new_lines.append(line)  # 不是資料列（可能是標題列或分隔線），原樣保留
            continue

        try:
            live = get_stock_price_single(code_candidate)
        except Exception:
            live = None

        if live and live.get("收盤價"):
            close = live["收盤價"]
            change_pct = live.get("漲跌幅%", 0)
            cells[5] = f"{close}元（{change_pct:+.2f}%）"
        else:
            cells[5] = "查無即時股價"

        new_lines.append(" | ".join([""] + cells[1:-1] + [""]))

    result = "\n".join(new_lines)
    result += "\n\n💡 股價欄位為即時查詢的真實收盤價（非AI推測），但股票篩選本身仍是AI依產業關聯推論，非ETF實際持股驗證過的標的。"
    return result


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
    {{"影響清單": [{{"新聞摘要": "20字內", "影響股票": [{{"code": "代號", "reason": "30字內，需針對該股票具體說明受影響的角色"}}], "影響方向": "正面/負面/中性", "影響程度": "高/中/低"}}]}}

    規則：
    - 如果一則新聞同時影響多檔股票，每一檔股票的"reason"都要分別具體說明該股票在這個事件裡的角色
    （例如是供應商、客戶、同業競爭者，或產業鏈上下游），不要用同一句話套用在所有股票上
    - 影響股票只列清單內代號，最多15則，只回傳JSON。"""

    result = call_claude(prompt, max_tokens=3500)
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

def generate_market_sentiment(inst_df: pd.DataFrame, market_margin: dict,
                                benchmark_price_change: float = None,
                                us_market_text: str = "", trade_date: str = "") -> str:
    """
    產生「大盤法人氛圍」段落——跟generate_premarket_watch是互補的兩個層級：
      - generate_premarket_watch：個股層級，只看「籌碼矛盾」的少數標的
      - generate_market_sentiment：大盤層級，判斷整體法人是避險還是布局心態

    資料範圍誠實聲明：inst_df（三大法人加總）只涵蓋「本系統追蹤的股票池」（約66-70檔），
    不是TWSE全市場三大法人統計（該端點尚未經測試驗證，暫不使用，避免引入未驗證資料）；
    market_margin（融資融券）才是真正的全市場數據

    2026-09-03修正（配合AI job排程從23:00改到隔日05:00台股開盤前）：
    原本prompt裡的「今天整體三大法人」，是在trade_date當天晚上23:00生成報告時寫的，
    這時候「今天」剛好等於trade_date，講得通。改成隔日05:00生成後，讀報告的當下
    trade_date已經是「昨天」（台股今天的交易都還沒開始），繼續講「今天」會讓人搞不清楚
    是在講哪個交易日，所以明確改成「上一交易日（{trade_date}）」，並且說明這是作為
    「今天開盤」的參考，把「資料屬於哪一天」跟「這份判斷要給哪一天的交易使用」分開講清楚。
    """
    inst_summary_text = "（無追蹤股票池法人資料）"
    if inst_df is not None and not inst_df.empty and "三大合計" in inst_df.columns:
        total_col = pd.to_numeric(inst_df["三大合計"], errors="coerce")
        net_total = total_col.sum()
        buy_count = (total_col > 0).sum()
        sell_count = (total_col < 0).sum()
        inst_summary_text = (
            f"追蹤股票池（{len(inst_df)}檔）三大法人合計淨{'買超' if net_total >= 0 else '賣超'}"
            f"約{abs(net_total):,.0f}張；{buy_count}檔買超、{sell_count}檔賣超"
        )

    margin_text = "（無全市場融資融券資料）"
    if market_margin:
        m_chg = market_margin.get("融資增減")
        s_chg = market_margin.get("融券增減")
        if m_chg is not None:
            margin_text = f"全市場融資餘額今日{'增加' if m_chg >= 0 else '減少'}約{abs(m_chg):,.0f}張"
            if s_chg is not None:
                margin_text += f"，融券餘額{'增加' if s_chg >= 0 else '減少'}約{abs(s_chg):,.0f}張"

    benchmark_text = ""
    if benchmark_price_change is not None:
        benchmark_text = f"，大盤指標ETF(0050)上一交易日{'上漲' if benchmark_price_change >= 0 else '下跌'}{abs(benchmark_price_change):.2f}%"

    us_section = f"\n【美股隔夜收盤（已完整收盤確認，非盤中片段）】\n{us_market_text}" if us_market_text else ""

    trade_date_label = trade_date or "上一交易日"

    prompt = f"""你是台股總經分析師。這份報告固定在台股開盤前產生，請根據以下資料，判斷
「上一交易日（{trade_date_label}）三大法人整體是避險心態還是布局心態」，作為今天台股開盤的參考。

【追蹤股票池法人動向（{trade_date_label}）】
{inst_summary_text}

【全市場散戶槓桿（融資融券，{trade_date_label}）】
{margin_text}{benchmark_text}
{us_section}

請注意：
1. 法人資料僅涵蓋本系統追蹤的股票池（非TWSE全市場統計），請在分析中誠實反映這個範圍限制，
   不要把追蹤股票池的結論當成「全市場」的定論來講。
2. 上面的美股資料是已經完整收盤確認的隔夜數據（不是抓取當下的盤中片段），可以放心把它當成
   「已經發生的事實」來分析，不需要用「目前」「現在」這種暗示還在變動中的語氣描述。
3. 明確區分「{trade_date_label}的法人/籌碼資料」跟「今天即將開盤的台股交易」是兩個不同的
   交易日，不要用「今天」指稱{trade_date_label}的資料。

請用約100-150字，繁體中文，判斷法人上一交易日整體偏向：
1. 避險心態（法人賣超、融資減少、可能有國際情勢干擾）
2. 布局心態（法人買超或分歧但融資理性增加、屬正常換手）
3. 混合訊號（無法明確判斷，需觀察後續）

用「### 🧭 大盤法人氛圍」當標題，內容誠實、避免過度確定的語氣。"""

    result = call_claude(
        prompt,
        system="你是誠實的台股總經分析師，會清楚標註資料範圍限制與資料所屬交易日，不誇大追蹤股票池資料代表全市場結論。",
        max_tokens=500,
    )
    return result if result else ""


def generate_premarket_watch(cross_df: pd.DataFrame, us_market_text: str = "", trade_date: str = "") -> str:
    """
    產生「今日開盤前30分鐘觀察重點」段落
    設計原則（重要）：這不是預測，是給台股開盤時對照用的「條件式檢查清單」——
    內容格式必須是「如果...就要注意...」，不能用肯定語氣預告股價會怎麼走，
    避免給使用者錯誤的確定感。

    優先分析對象：「籌碼矛盾」欄位有標記的股票（融資與法人方向衝突，動態決定，
    不是固定挑幾檔），這些才是真正需要提早判讀「換手還是誘多」的標的；
    訊號單純一致的股票不需要額外解讀。

    2026-09-03修正（配合AI job排程從23:00改到隔日05:00台股開盤前）：
    原本這個段落叫「明日開盤前30分鐘觀察重點」、prompt裡寫「你沒有明天的即時資料，
    只有今晚收盤後的籌碼與美股資訊」——這是23:00當晚生成報告、隔天才會被打開來看的
    用詞，「明天」指的是報告生成後的下一個交易日。改成05:00台股開盤前生成後，
    使用者打開報告時，那個「明天」其實就是「今天」——用詞沒跟著改會讓人誤以為報告
    在講後天的事。同時，這個時間點美股已經確定收盤（不是23:00時只開盤1.5小時的
    片段資料），對「美股隔夜表現」這件事本身可以講得更肯定，但對台股接下來要怎麼走，
    仍然要維持條件式、不預測的原則不變。
    """
    if cross_df is None or cross_df.empty:
        return ""

    conflict_col = "籌碼矛盾" if "籌碼矛盾" in cross_df.columns else None
    conflicts = pd.DataFrame()
    if conflict_col:
        conflicts = cross_df[cross_df[conflict_col].astype(str).str.strip() != ""]

    conflict_text = "（上一交易日無明顯籌碼矛盾標的）"
    if not conflicts.empty:
        lines = []
        for _, row in conflicts.head(8).iterrows():
            code = row.get("股票代號", "")
            name = row.get("股票名稱", "")
            signal = row.get(conflict_col, "")
            margin_note = row.get("融資訊號", "")
            inst_signal = row.get("法人訊號", "")
            lines.append(f"- {code} {name}：{signal}（融資：{margin_note}／法人：{inst_signal}）")
        conflict_text = "\n".join(lines)

    us_section = f"\n\n【美股隔夜收盤（已完整收盤確認）】\n{us_market_text}" if us_market_text else "（無美股資料）"

    trade_date_label = trade_date or "上一交易日"

    prompt = f"""你是台股盤前分析師，這份報告在台股開盤前產生，要為今天開盤前30分鐘提供一份
「觀察檢查清單」，給使用者開盤時對照當下實際狀況判讀，**不是預測今天股價會怎麼走**。

嚴格規則：
- 全部用「如果...則要注意...」這種條件式語氣，絕不能用肯定句預告台股今天股價方向
- 你手上的是上一交易日（{trade_date_label}）收盤後的籌碼資料，以及已經完整收盤確認的
  美股隔夜表現——你沒有台股今天開盤後的即時資料，要誠實反映這個限制
- 美股隔夜表現是「已經發生、已收盤確認」的事實，可以直接肯定描述（不用「目前」「現在」
  這種暗示還在變動的語氣）；但美股走勢對台股今天開盤後的影響，仍然只能用條件式語氣推測
- 重點放在「籌碼矛盾」標的（融資與法人方向衝突的股票，資料屬於{trade_date_label}）——
  這些是真正需要開盤時多留意的，不是隨便挑幾檔知名股

上一交易日（{trade_date_label}）籌碼矛盾標的（融資 vs 法人方向衝突，需要今天開盤驗證是換手還是誘多/低接）：
{conflict_text}
{us_section}

請用以下格式產生內容（繁體中文）：

### 🔔 今日開盤前30分鐘觀察重點

**國際情勢／美股影響**：（1-2句，描述美股隔夜收盤的確定事實，再用條件式語氣說明對台股今天開盤情緒的可能影響）

**法人意圖推測**：（針對籌碼矛盾標的，各1句話推測法人可能在想什麼，例如「若開盤即賣壓湧現，可能代表法人趁散戶追高出貨」）

**散戶因應策略**：（2-3點具體可執行的觀察建議，例如「開盤30分鐘內留意成交量是否放大，若價漲量縮需提高警覺」）

**大盤情況提醒**：（1句，提醒需留意的大盤層級因素，如指數期貨走勢、匯率等，若無特別資料可從美股/籌碼矛盾程度推論一般性提醒）

全部約200-350字，語氣專業但誠實，避免過度確定的預測語言。"""

    result = call_claude(
        prompt,
        system="你是誠實嚴謹的台股盤前分析師，絕不用肯定語氣預測台股股價，只提供條件式觀察建議，"
               "但對已經收盤確認的美股隔夜事實可以肯定描述，並明確反映資料所屬交易日與報告產生時點的限制。",
        max_tokens=800,
    )
    return result if result else ""


def generate_investment_report(ss, trade_date, us_market_text="", cross_df: pd.DataFrame = None,
                                 market_margin: dict = None, benchmark_price_change: float = None,
                                 alert_text: str = "", major_company_text: str = "",
                                 product_maturity_text: str = ""):
    log.info("收集所有分頁資料...")
    data = collect_all_data(ss)
    data_text = format_data_for_ai(data, trade_date)
    us_section = f"\n\n【美股隔夜收盤（已完整收盤確認，非盤中片段）】\n{us_market_text}" if us_market_text else ""

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

報告產生時點（2026-09-03新增）：
- 這份報告固定在台股開盤前產生。文中所有ETF籌碼、三大法人、融資融券、基本面資料，
  都是「上一交易日」（報告標題的交易日）收盤後的資料；美股資料則是已經完整收盤確認的
  隔夜表現，不是盤中片段，可以放心當成已發生的事實來分析。
- 請用「上一交易日」或直接寫出交易日日期稱呼籌碼/法人/基本面資料，把「今天」保留給
  即將開盤、报告使用者接下來要操作的這個台股交易日，避免兩個不同交易日被混在一起講。

誠實原則（最重要）：
- 資料不足時，明確說明缺少哪個維度及對判斷的影響
- 訊號不明確時，誠實說明，不強行推薦
- 寧可說「資料不足，建議觀望」也不做無根據推薦
- 對每個推薦標的，標示哪些面向有資料支撐，哪些缺失

分析風格：繁體中文，專業但易懂，有數據支撐"""

    prompt = f"""這份報告在台股開盤前產生。以下的ETF籌碼／三大法人／融資融券／基本面資料，
是上一交易日（{trade_date}）收盤後的資料；美股資料是剛結束、已完整收盤確認的隔夜表現。
請根據這些資料，在ETF已選出的股票中找出最有潛力的標的，作為今天台股開盤後的觀察依據。

所有標的都來自主動式ETF持倉，已經過專業經理人篩選。
你的任務：在這些股票中進一步找出「上一交易日表現最有潛力、值得今天開盤留意」的3-5檔。

潛力評分標準（權重由高到低）：
1. ETF籌碼集中度（幾檔持有？權重多高？上一交易日加碼？）
2. 三大法人同向買超
3. 基本面支撐（月營收年增率、本益比）
4. 題材發酵程度（萌芽/成長期更好）
5. 散戶冷淡但法人積極＝最佳布局時機
6. 美股連動（需確認台股籌碼同步）

{data_text}{us_section}

## 📊 {trade_date} ETF狙擊系統每日報告

### 🎯 上一交易日市場總結
（2-3句，以台股籌碼為核心，明確是在總結{trade_date}這個交易日）

### 🏆 上一交易日最具潛力標的（Top 3-5，今天開盤觀察用）
每檔提供：
- 代號與名稱
- 各維度評分（ETF籌碼/法人/基本面/題材）
- 關鍵優勢
- 資料缺失說明（如有）
- 風險與觀察訊號

### 📊 籌碼面分析

### 🔥 題材面分析

### 🌏 美股隔夜影響評估

### ⚠️ 風險提示

### 💡 今日開盤觀察清單（3-5點）

報告約 900-1200 字。若資料不足請明確說明，不要強行推薦。"""

    log.info("呼叫 Claude API 產生主報告...")
    main_report = call_claude(prompt, system=system_prompt, max_tokens=4000)

    # 獨立呼叫產生受惠股
    log.info("呼叫 Claude API 產生受惠股推薦...")
    smart_df = data.get("聰明錢名單", pd.DataFrame())
    trend_df = data.get("題材趨勢", pd.DataFrame())
    related = generate_related_stocks(smart_df, trend_df)

    # 1000元以下優選股清單（純資料篩選，不呼叫AI，零額外成本）
    affordable_section = ""
    try:
        watch_df0 = cross_df if cross_df is not None and not cross_df.empty else data.get("多方驗證名單", pd.DataFrame())
        affordable_text = build_affordable_picks_section(watch_df0, max_price=1000.0, top_n=8)
        if affordable_text:
            affordable_section = "\n\n" + affordable_text
    except Exception as e:
        log.warning(f"1000元以下優選股清單生成失敗（不影響主報告）: {e}")

    # 今日開盤前30分鐘觀察重點（籌碼矛盾標的優先分析，條件式檢查清單，非預測）
    premarket_section = ""
    try:
        log.info("呼叫 Claude API 產生開盤前觀察重點...")
        watch_df = cross_df if cross_df is not None and not cross_df.empty else data.get("多方驗證名單", pd.DataFrame())
        premarket_text = generate_premarket_watch(watch_df, us_market_text, trade_date)
        if premarket_text:
            premarket_section = "\n\n" + premarket_text
    except Exception as e:
        log.warning(f"開盤前觀察重點生成失敗（不影響主報告）: {e}")

    # 大盤法人氛圍（大盤層級，跟上面的開盤前觀察重點是互補的兩個顆粒度）
    market_sentiment_section = ""
    try:
        log.info("呼叫 Claude API 產生大盤法人氛圍...")
        watch_df2 = cross_df if cross_df is not None and not cross_df.empty else data.get("多方驗證名單", pd.DataFrame())
        sentiment_text = generate_market_sentiment(
            watch_df2, market_margin or {}, benchmark_price_change, us_market_text, trade_date
        )
        if sentiment_text:
            market_sentiment_section = "\n\n" + sentiment_text
    except Exception as e:
        log.warning(f"大盤法人氛圍生成失敗（不影響主報告）: {e}")

    # 每日訊號提醒（聰明錢集中度提升／融資券異常變化／籌碼矛盾出現解除，純資料比對，不呼叫AI）
    alert_section = ""
    if alert_text:
        alert_section = (
            "\n\n### 🔔 訊號提醒（聰明錢集中度提升／融資券異常變化／籌碼矛盾出現解除）\n\n"
            + alert_text
        )

    # 國際大型公司財報/重大消息影響（2026-10-15新增，見main.py的analyze_major_company_impact()）
    major_company_section = ""
    if major_company_text:
        major_company_section = (
            "\n\n### 🏢 國際大型公司財報/重大消息影響\n\n"
            + major_company_text
        )

    # 2026-09-24移除：原本這裡會把你上傳過的「券商分點分析」附加在AI報告最後（見
    # 2026-09-16的決策），但這份資料是手動、選擇性截圖上傳的，沒有固定更新頻率——
    # 如果沒有每天/常常上傳，AI報告裡看到的永遠是同一批舊分析，時效性反而造成誤導
    # （使用者2026-09-24反映此問題）。改成完全移除這段附加，AI報告只保留全自動、
    # 每天都會更新的資料維度。你上傳過的分析仍然完整保留在「手動籌碼分析」頁面本身
    # 的歷史紀錄可以查閱，也仍會在「多方驗證名單」頁面即時顯示（那裡是查詢當下，不是
    # 隔夜快照，沒有時效性問題）——只有「AI報告」這個每天生成一次、容易被誤以為是當天
    # 新資料的地方不再顯示。main.py裡對應的broker_branch_text計算區塊也一併移除，
    # 避免白白多打一次Sheets查詢。

    final_report = main_report
    if affordable_section:
        final_report += affordable_section
    if alert_section:
        final_report += alert_section
    if related:
        final_report += "\n\n" + related
    if premarket_section:
        final_report += premarket_section
    product_maturity_section = ""
    if product_maturity_text:
        product_maturity_section = (
            "\n\n### 🏭 產品成熟度檢視\n\n"
            + product_maturity_text
        )

    if market_sentiment_section:
        final_report += market_sentiment_section
    if major_company_section:
        final_report += major_company_section
    if product_maturity_section:
        final_report += product_maturity_section

    return final_report

def analyze_product_maturity(news_df, cross_df, fundamental_df, extra_codes=None, ss=None):
    """
    2026-10-21新增：針對「題材相關產品是否已經成熟量產、有實際營收貢獻」的判斷。
    背景：題材面分析（topic_analyzer.py）只回答「有沒有被ETF布局」，沒有回答「這家公司
    在這個題材裡的生意，實際上做到什麼程度」——有些公司是傳產剛好符合題材、正在轉型但
    尚未有正式收入；有些公司已經有成熟產品、能量產、有長期客戶。

    範圍只鎖定當天候選名單（cross_df依綜合評分排序後取前8檔）∪ 目前持倉（extra_codes），
    不是整個ETF股票池，維持低成本。

    對每檔候選股，交叉比對兩個事實：
    ①基本面資料裡的「月營收年增率%」（公司整體營收趨勢，不分題材/本業）
    ②新聞裡有沒有同時命中「這檔股票的關鍵字」(STOCK_KEYWORD_MAP) + 「成熟/早期關鍵字」
      (MATURITY_KEYWORDS)
    把這些具體事實（不是憑空推論）餵給AI，請它綜合判斷「成熟有營收貢獻／早期布局尚未反映
    營收／資料不足無法判斷」，資料不夠就必須誠實標「資料不足」，不能用自己的背景知識硬掰
    （沿用專案一貫的誠實原則）。

    回傳：(maturity_df, summary_text)
    - maturity_df欄位：股票代號、股票名稱、月營收年增率%、分類、判斷依據摘要（供main.py
      寫入「產品成熟度追蹤」Sheet用）
    - summary_text：給主報告插入的一段摘要文字
    """
    if cross_df is None or cross_df.empty or "股票代號" not in cross_df.columns:
        return pd.DataFrame(), ""

    from news_fetcher import STOCK_KEYWORD_MAP, MATURITY_KEYWORDS

    # 2026-10-21新增：合併兩套關鍵字來源——①寫死的STOCK_KEYWORD_MAP（固定~20檔AI供應鏈股）
    # ②「關鍵字審核」頁面核准後存進「AI關鍵字審核」分頁的動態清單（keyword_generator.py）。
    # 兩者都可能有缺口：①只覆蓋固定名單，候選股換了別的產業就查無關鍵字；②要等AI按週分桶
    # 生成、且使用者實際核准過才會有資料，候選股剛好還沒輪到/還沒審核也會是空的。
    # 所以採「有就合併，缺一邊不影響另一邊」，盡量降低候選股完全查無關鍵字、被迫落到
    # 「資料不足」的情況（跟使用者討論後確認的方向）。
    combined_keyword_map = {}
    for code, kws in STOCK_KEYWORD_MAP.items():
        combined_keyword_map.setdefault(code, set()).update(kws)
    if ss is not None:
        try:
            from keyword_generator import get_approved_keyword_map
            approved_map = get_approved_keyword_map(ss)
            for code, kws in approved_map.items():
                combined_keyword_map.setdefault(code, set()).update(kws)
        except Exception as e:
            log.warning(f"產品成熟度分析：讀取「關鍵字審核」已核准清單失敗，僅用內建清單: {e}")
    combined_keyword_map = {code: list(kws) for code, kws in combined_keyword_map.items()}

    cross_df = cross_df.copy()
    cross_df["股票代號"] = cross_df["股票代號"].astype(str).str.strip()
    cross_df["綜合評分"] = pd.to_numeric(cross_df.get("綜合評分"), errors="coerce")
    top_candidates = cross_df.sort_values("綜合評分", ascending=False).head(8)
    candidate_codes = top_candidates["股票代號"].tolist()

    extra_codes = [str(c).strip() for c in (extra_codes or [])]
    all_codes = list(dict.fromkeys(candidate_codes + extra_codes))
    if not all_codes:
        return pd.DataFrame(), ""

    name_map = dict(zip(cross_df["股票代號"], cross_df.get("股票名稱", "")))

    yoy_map = {}
    if fundamental_df is not None and not fundamental_df.empty and "股票代號" in fundamental_df.columns:
        fdf = fundamental_df.copy()
        fdf["股票代號"] = fdf["股票代號"].astype(str).str.strip()
        for _, r in fdf.iterrows():
            yoy_map[r["股票代號"]] = r.get("年增率%", "")

    all_maturity_patterns = []
    for _tier, patterns in MATURITY_KEYWORDS.items():
        all_maturity_patterns.extend(patterns)

    news_hits = {}
    if news_df is not None and not news_df.empty and "標題" in news_df.columns:
        title_col = news_df["標題"].fillna("")
        summary_col = news_df["摘要"].fillna("") if "摘要" in news_df.columns else pd.Series("", index=news_df.index)
        full_text = title_col + " " + summary_col
        for code in all_codes:
            stock_patterns = combined_keyword_map.get(code, [])
            if not stock_patterns:
                continue
            mask_stock = full_text.apply(lambda t: any(p.lower() in t.lower() for p in stock_patterns))
            mask_maturity = full_text.apply(lambda t: any(p in t for p in all_maturity_patterns))
            matched = news_df[mask_stock & mask_maturity]
            if not matched.empty:
                news_hits[code] = matched["標題"].dropna().head(5).tolist()

    fact_blocks = []
    for code in all_codes:
        name = name_map.get(code, "")
        yoy = yoy_map.get(code, "")
        yoy_text = f"月營收年增率：{yoy}%" if yoy not in ("", None) else "月營收年增率：資料不足"
        hits = news_hits.get(code, [])
        if hits:
            news_text = "相關新聞（含成熟度關鍵字）：\n" + "\n".join(f"  - {h}" for h in hits)
        else:
            news_text = "相關新聞（含成熟度關鍵字）：查無相關新聞"
        fact_blocks.append(f"{code} {name}\n{yoy_text}\n{news_text}")

    facts_str = "\n\n".join(fact_blocks)

    prompt = f"""以下是{len(all_codes)}檔股票的客觀事實資料（月營收年增率、新聞裡是否命中
「量產/出貨/認證通過」等成熟度關鍵字），請針對每一檔，根據**提供的事實**（不是你自己的
背景知識），判斷這家公司跟題材相關的產品/業務，目前是哪個階段：

{facts_str}

分類只能選以下三種之一：
- 「成熟有營收貢獻」：有新聞提到量產/出貨/認證通過等確認性字眼，或月營收年增率明顯為正
- 「早期布局尚未反映營收」：只有評估/試產/布局等早期字眼，或月營收年增率平淡/負成長
- 「資料不足無法判斷」：沒有相關新聞、也沒有月營收資料時，必須誠實選這個，不能憑空推測

請用JSON格式回傳一個陣列，每個元素是：
{{"股票代號": "...", "分類": "...", "判斷依據摘要": "...(50字內，具體指出根據哪則新聞或
哪個數字)"}}

只回傳JSON陣列，不要其他文字。"""

    result = call_claude(
        prompt,
        system="你是誠實嚴謹的產業分析師，只根據提供的事實資料判斷，資料不足就明講，"
               "絕不用自己的背景知識去猜測沒有提供的事實，也不對沒有被問到的股票多做發揮。",
        max_tokens=2000,
    )
    if not result:
        return pd.DataFrame(), ""

    try:
        result = result.strip().replace("```json", "").replace("```", "")
        data = json.loads(result)
        rows = []
        for item in data:
            code = str(item.get("股票代號", "")).strip()
            rows.append({
                "股票代號": code,
                "股票名稱": name_map.get(code, ""),
                "月營收年增率%": yoy_map.get(code, ""),
                "分類": item.get("分類", ""),
                "判斷依據摘要": item.get("判斷依據摘要", ""),
            })
        maturity_df = pd.DataFrame(rows)
        if maturity_df.empty:
            return pd.DataFrame(), ""

        mature = maturity_df[maturity_df["分類"] == "成熟有營收貢獻"]
        early = maturity_df[maturity_df["分類"] == "早期布局尚未反映營收"]
        lines = []
        for _, r in mature.iterrows():
            lines.append(f"🟢 {r['股票代號']} {r['股票名稱']}：成熟有營收貢獻——{r['判斷依據摘要']}")
        for _, r in early.iterrows():
            lines.append(f"🟡 {r['股票代號']} {r['股票名稱']}：早期布局尚未反映營收——{r['判斷依據摘要']}")
        summary_text = "\n".join(lines) if lines else "候選名單中目前沒有足夠證據判斷產品成熟度，建議持續觀察。"

        return maturity_df, summary_text
    except Exception as e:
        log.warning(f"產品成熟度分析JSON解析失敗: {e}")
        return pd.DataFrame(), ""



def analyze_major_company_impact(news_df, smart_df):
    """
    2026-10-15新增：針對「國際大型公司財報/重大消息」情境的聚焦版新聞影響分析。
    跟analyze_news_impact()的差異：
    ①只篩MAJOR_COMPANY_KEYWORDS命中的新聞（半導體/AI運算、消費電子/雲端平台、
      電動車/車用這幾個產業指標性公司的財報/法說/展望/評等調整），不是不分類
      取前80則，寧可筆數少也不要雜訊。
    ②同一次AI呼叫除了結構化的「新聞→受影響股票」清單之外，也直接產生一段narrative
      摘要，給AI報告新增的「國際大型公司財報/重大消息影響」段落直接使用。
    ③如果這次新聞裡沒有符合資格的大型公司消息，摘要會誠實寫「隔夜無重大公司財報/
      消息」，不會為了有內容硬湊。

    回傳：(impact_df, summary_text)
      impact_df：結構類似analyze_news_impact()的輸出，寫入「新聞×籌碼交叉」頁面用。
      summary_text：給AI報告段落直接使用的narrative文字。
    """
    if news_df.empty or smart_df.empty:
        return pd.DataFrame(), ""

    from news_fetcher import MAJOR_COMPANY_KEYWORDS
    all_patterns = []
    for _industry, companies in MAJOR_COMPANY_KEYWORDS.items():
        for _company, patterns in companies.items():
            all_patterns.extend(patterns)

    title_col = news_df["標題"].fillna("")
    summary_col = news_df.get("摘要", pd.Series("", index=news_df.index)).fillna("")
    full_text = title_col + " " + summary_col
    mask = full_text.apply(lambda t: any(p.lower() in t.lower() for p in all_patterns))
    matched_df = news_df[mask]

    if matched_df.empty:
        return pd.DataFrame(), "隔夜無重大公司財報/消息，相關供應鏈持股維持原趨勢觀察。"

    titles = matched_df["標題"].dropna().head(30).tolist()
    news_str = "\n".join([f"- {t}" for t in titles])

    stocks = smart_df[["股票代號","股票名稱"]].head(30).drop_duplicates()
    stock_str = "\n".join([f"{r['股票代號']} {r['股票名稱']}" for _, r in stocks.iterrows()])

    prompt = f"""你是台灣股市分析師，專門分析國際大型公司（半導體/AI運算、消費電子/雲端平台、
電動車/車用這幾個產業的指標性公司，例如NVIDIA、AMD、台積電ADR、美光、博通、高通、ASML、
Apple、Microsoft、Tesla等）的財報/法說/重大消息，對台股供應鏈個股的影響。

以下新聞是已經篩選過、確定提到這些大型公司的新聞標題：
{news_str}

ETF重倉股票清單（只在這份清單裡找受影響股票）：
{stock_str}

請完成兩件事，只回傳JSON，格式如下：
{{
  "摘要": "150字內，繁體中文，給隔日開盤操盤參考用的narrative摘要，說明這次主要是
          哪家大型公司的什麼消息、大致方向是正面還是負面。如果新聞內容其實都是瑣碎、
          非重大的消息（沒有真正的財報/法說/展望/評等調整），就誠實寫『隔夜無重大
          公司財報/消息，相關供應鏈持股維持原趨勢觀察』，不要牽強附會。",
  "影響清單": [
    {{"新聞摘要": "20字內", "影響股票": [{{"code": "代號", "reason": "30字內，需具體
      說明該股票是這家大型公司的供應商/客戶/同業競爭者的哪一種角色"}}],
      "影響方向": "正面/負面/中性", "影響程度": "高/中/低"}}
  ]
}}

規則：
- 只有真正重大的消息（財報、法說會重點、展望調整、評等調升/調降）才列入「影響清單」，
  單純的股價漲跌新聞不算
- 影響股票只列清單內代號，最多10則
- 只回傳JSON"""

    result = call_claude(prompt, max_tokens=2500)
    if not result:
        return pd.DataFrame(), ""

    try:
        result = result.strip().replace("```json", "").replace("```", "")
        data = json.loads(result)
        summary_text = data.get("摘要", "")
        impacts = data.get("影響清單", [])

        rows = []
        for item in impacts:
            affected = item.get("影響股票", [])
            news_summary = item.get("新聞摘要", "")
            direction = item.get("影響方向", "中性")
            degree = item.get("影響程度", "中")

            for stock in affected:
                if isinstance(stock, dict):
                    code = str(stock.get("code", ""))
                    reason = stock.get("reason", "")
                else:
                    code = str(stock)
                    reason = ""

                name_match = smart_df[smart_df["股票代號"].astype(str) == code]["股票名稱"].values
                stock_name = name_match[0] if len(name_match) > 0 else ""

                rows.append({
                    "新聞摘要": news_summary,
                    "股票代號": code,
                    "股票名稱": stock_name,
                    "原因": reason,
                    "影響方向": direction,
                    "影響程度": degree,
                })

        impact_df = pd.DataFrame(rows)
        return impact_df, summary_text
    except Exception as e:
        log.warning(f"大型公司財報影響分析JSON解析失敗: {e}")
        return pd.DataFrame(), ""

def write_ai_report_to_sheets(ss, report, trade_date, retries=2):
    """
    寫入AI報告到Sheets，含重試機制。
    2026-08-26事故：Claude API呼叫全數成功、報告內容都生成好了，
    但寫入這一步遇到網路瞬斷（RemoteDisconnected），整份報告因此遺失，
    Sheets跟Streamlit都完全看不到當天報告——原本這裡完全沒有重試，
    一次連線失敗就前功盡棄，改成失敗後等待重試，避免「生成成功但寫入失敗」的狀況。
    """
    import time
    import gspread

    SHEET = "每日AI總結"

    def _do_write():
        existing = [ws.title for ws in ss.worksheets()]
        if SHEET not in existing:
            ws = ss.add_worksheet(title=SHEET, rows=1000, cols=4)
            ws.append_row(["日期", "更新時間", "AI分析報告（上）", "AI分析報告（下）"])
        else:
            ws = ss.worksheet(SHEET)

        # 強制確保表頭正確，避免舊分頁殘留過期表頭導致欄位對不上
        header = ["日期", "更新時間", "AI分析報告（上）", "AI分析報告（下）"]
        current_header = ws.row_values(1)
        if current_header != header:
            ws.update('A1:D1', [header])
            log.info(f"表頭已修正：{current_header} → {header}")

        now = datetime.now(TW_TZ).strftime("%H:%M")
        # 拆成兩半避免 Sheets 單格字數限制（50000字）
        mid = len(report) // 2
        split_pos = report.rfind("\n\n", 0, mid + 500)
        if split_pos == -1:
            split_pos = mid
        part1 = report[:split_pos]
        part2 = report[split_pos:]
        ws.append_row([trade_date, now, part1, part2])

    last_error = None
    for attempt in range(retries + 1):
        try:
            time.sleep(3)
            _do_write()
            log.info(f"AI 報告寫入完成 ({trade_date})")
            return True
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait = 10 * (attempt + 1)
                log.warning(f"AI報告寫入失敗，{wait}秒後重試（第{attempt+1}次）: {e}")
                time.sleep(wait)
                continue
            log.error(f"AI報告寫入失敗（已重試{retries}次，放棄，報告內容遺失）: {e}")
            return False
    return False

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