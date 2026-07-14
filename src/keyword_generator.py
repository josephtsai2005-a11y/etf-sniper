"""
keyword_generator.py
AI自動生成個股題材關鍵字，取代 trend_analyzer.py 裡手動維護的 DEFAULT_MAP（僅18檔）

設計：
  - 每檔股票每月最多重新生成一次候選關鍵字
  - AI生成的關鍵字不會直接生效！會先進「待審核」狀態存進「AI關鍵字審核」分頁
  - 只有管理者在Streamlit「關鍵字審核」頁面核准後，才會真的被拿去比對新聞/Trends
  - 自動過濾常見籠統詞（財報、營收、展望...），減少需要人工審核的雜訊
  - 拒絕過的關鍵字會被記住，同一檔股票不會重複生成一樣的候選字來煩管理者
"""
import hashlib
import logging
import pandas as pd
from datetime import datetime
import pytz

from ai_analyzer import call_claude

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_KEYWORD_QUEUE = "AI關鍵字審核"
QUEUE_COLS = ["股票代號", "股票名稱", "關鍵字", "生成日期", "狀態"]
STATUS_PENDING = "待審核"
STATUS_APPROVED = "已核准"
STATUS_REJECTED = "已拒絕"

WEEKLY_BUCKETS = 5

STOPWORDS = {
    "財報", "營收", "獲利", "展望", "產業", "公司", "股票", "台股", "上市", "上櫃",
    "集團", "部門", "業績", "成長", "投資", "市場", "企業", "股價", "營運", "財務",
    "毛利", "毛利率", "EPS", "每股盈餘", "資本支出", "法說會", "股東會", "配息",
    "台灣", "亞洲", "全球", "國際", "科技", "電子", "製造", "供應鏈", "概念股",
}


def _weekday_bucket(code: str) -> int:
    """依股票代號算出固定分配到星期幾（0=週一...4=週五），同一檔股票每次算出來都一樣"""
    h = int(hashlib.md5(code.encode("utf-8")).hexdigest(), 16)
    return h % WEEKLY_BUCKETS


def _load_keyword_queue(ss) -> pd.DataFrame:
    """讀取關鍵字審核佇列，不存在則回傳空表（含正確欄位結構）"""
    try:
        ws = ss.worksheet(SHEET_KEYWORD_QUEUE)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame(columns=QUEUE_COLS)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in QUEUE_COLS:
            if c not in df.columns:
                df[c] = ""
        return df
    except Exception:
        return pd.DataFrame(columns=QUEUE_COLS)


def _write_keyword_queue(ss, df: pd.DataFrame):
    """整表覆寫回Sheets"""
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_KEYWORD_QUEUE not in existing:
        ws = ss.add_worksheet(title=SHEET_KEYWORD_QUEUE, rows=3000, cols=10)
    else:
        ws = ss.worksheet(SHEET_KEYWORD_QUEUE)
    ws.clear()
    ws.append_row(df.columns.tolist())
    if not df.empty:
        ws.append_rows(df.fillna("").values.tolist(), value_input_option="USER_ENTERED")


def get_approved_keyword_map(ss) -> dict:
    """
    取得目前所有「已核准」的關鍵字，組成 match_keywords_to_stocks 需要的格式
    這是實際會拿去跟新聞/Trends比對的關鍵字來源（未核准的候選字不會生效）
    回傳：{股票代號: [關鍵字, ...]}
    """
    df = _load_keyword_queue(ss)
    if df.empty:
        return {}
    approved = df[df["狀態"] == STATUS_APPROVED]
    if approved.empty:
        return {}
    result = {}
    for code, grp in approved.groupby("股票代號"):
        result[code] = grp["關鍵字"].tolist()
    return result


def get_pending_keywords(ss) -> pd.DataFrame:
    """取得所有「待審核」的關鍵字，供Streamlit審核頁面顯示"""
    df = _load_keyword_queue(ss)
    if df.empty:
        return df
    return df[df["狀態"] == STATUS_PENDING].reset_index(drop=True)


def apply_review_decisions(ss, decisions: dict):
    """
    套用管理者的審核決定
    decisions: {(股票代號, 關鍵字): "已核准" 或 "已拒絕"}
    """
    df = _load_keyword_queue(ss)
    if df.empty:
        return 0
    updated = 0
    for idx, row in df.iterrows():
        key = (row["股票代號"], row["關鍵字"])
        if key in decisions:
            df.at[idx, "狀態"] = decisions[key]
            updated += 1
    if updated > 0:
        _write_keyword_queue(ss, df)
    return updated


def _load_relevant_news_titles(ss, stock_name: str, max_titles: int = 3) -> list:
    """
    從「新聞歷史庫」撈出標題裡有出現該股票名稱的近期新聞（用來當AI生成關鍵字的補充根據）
    冷門股即使只有1-2篇相關新聞，也比完全沒有根據好
    """
    try:
        ws = ss.worksheet("新聞歷史庫")
        vals = ws.get_all_values()
        if len(vals) < 2:
            return []
        df = pd.DataFrame(vals[1:], columns=vals[0])
        if "標題" not in df.columns:
            return []
        matched = df[df["標題"].str.contains(stock_name, na=False, regex=False)]
        return matched["標題"].tail(max_titles).tolist()
    except Exception:
        return []


def _generate_keywords_for_stock(code: str, name: str, existing_keywords: list,
                                   etf_names: list = None, news_titles: list = None) -> list:
    """
    呼叫Claude，針對單一股票生成產業/題材關鍵字候選（尚未核准，僅供審核）
    設計重點：不讓AI單憑訓練記憶憑空猜，而是餵入兩種「真實根據」讓AI延伸：
      1. 持有這檔股票的ETF名稱 —— 基金公司已經幫你做好主題分類，是最可靠的免費線索
      2. 該股近期相關新聞標題（若有）—— 即使只有1-2篇也比完全沒根據好
    生成後會自動過濾常見籠統詞（見 STOPWORDS），減少人工審核負擔
    """
    existing_text = "、".join(existing_keywords) if existing_keywords else "（無）"

    etf_context = ""
    if etf_names:
        etf_context = f"\n這檔股票目前被以下主題型ETF持有（ETF名稱本身通常反映其被歸類的產業/題材，可作為重要參考）：\n{' / '.join(etf_names)}\n"

    news_context = ""
    if news_titles:
        news_titles_text = "\n".join(f"- {t}" for t in news_titles)
        news_context = f"\n該股近期相關新聞標題（可從中判斷目前市場關注的具體題材角度）：\n{news_titles_text}\n"

    if not etf_context and not news_context:
        grounding_note = "（目前沒有額外的ETF持有或新聞根據，請基於你對此公司產業定位的了解謹慎生成，避免過度籠統或臆測）"
    else:
        grounding_note = "請優先根據上述ETF持有與新聞根據來生成關鍵字，不要脫離這些線索憑空發明題材。"

    stopwords_text = "、".join(sorted(STOPWORDS))

    prompt = f"""你是台股產業分析師。請針對下列個股，列出5-8個最能代表其「產業鏈定位」與「題材歸屬」的關鍵字，
這些關鍵字將用於比對新聞熱詞與Google Trends搜尋量，藉此判斷該股是否受惠於當前市場熱門題材。

股票代號：{code}
股票名稱：{name}
該股目前已有的關鍵字（避免完全重複，可以延伸出新角度，但不要跟這些完全一樣）：{existing_text}
{etf_context}{news_context}
{grounding_note}

嚴格禁止使用以下這類過於籠統、任何公司都適用、沒有鑑別度的詞（不要生成這些詞或其同義詞）：
{stopwords_text}

請只回傳關鍵字，用頓號「、」分隔，不要任何說明文字、不要編號、不要換行。
關鍵字應盡量具體（例如「CoWoS」「散熱模組」這種供應鏈定位），避免過於籠統的產業大分類（例如單純「電子業」）。
關鍵字範例格式（僅供參考格式，不要抄這個內容）：CoWoS、先進封裝、AI伺服器、散熱模組

現在請針對「{name}」給出關鍵字："""

    result = call_claude(prompt, system="你是專業的台股產業分析師，回答簡潔精準，只輸出關鍵字列表，不臆測沒有根據的題材，絕不使用籠統通用詞。", max_tokens=300)
    if not result:
        return []

    raw_kws = [kw.strip() for kw in result.replace("\n", "、").replace(",", "、").split("、")]
    raw_kws = [kw for kw in raw_kws if kw and len(kw) <= 10]
    raw_kws = [kw for kw in raw_kws if kw not in STOPWORDS]
    new_kws = [kw for kw in raw_kws if kw not in existing_keywords]
    return new_kws


def get_or_generate_keyword_map(ss, stock_list: pd.DataFrame, max_new_calls: int = 50) -> dict:
    """
    主入口：
      1. 依週間分桶邏輯，為「今天輪到」且「這個月還沒生成過候選字」的股票呼叫AI生成候選關鍵字
      2. 候選字寫入「AI關鍵字審核」分頁，狀態為「待審核」（不會馬上生效）
      3. 回傳目前所有「已核准」的關鍵字map，供 match_keywords_to_stocks 使用

    stock_list: 需包含「股票代號」「股票名稱」欄位的DataFrame（例如聰明錢名單），
                若有「持有ETF清單」欄位會一併用來當AI生成的根據
    max_new_calls: 單次執行的安全上限（正常情況下週間分桶就會把數量壓得很低，這只是防呆上限）
    回傳：{股票代號: [已核准關鍵字, ...]}（未核准的候選字不會出現在這裡）
    """
    now = datetime.now(TW_TZ)
    this_month = now.strftime("%Y-%m")
    today_str = now.strftime("%Y-%m-%d")
    today_weekday = now.weekday()

    queue_df = _load_keyword_queue(ss)

    generated_this_month_codes = set()
    rejected_kws_by_code = {}
    if not queue_df.empty:
        queue_df["_month"] = queue_df["生成日期"].astype(str).str[:7]
        generated_this_month_codes = set(
            queue_df[queue_df["_month"] == this_month]["股票代號"].tolist()
        )
        rejected = queue_df[queue_df["狀態"] == STATUS_REJECTED]
        for code, grp in rejected.groupby("股票代號"):
            rejected_kws_by_code[code] = set(grp["關鍵字"].tolist())

    codes_to_check = stock_list["股票代號"].astype(str).unique().tolist() if "股票代號" in stock_list.columns else []
    names_by_code = {}
    etf_names_by_code = {}
    if "股票代號" in stock_list.columns and "股票名稱" in stock_list.columns:
        for _, r in stock_list.iterrows():
            code_key = str(r["股票代號"])
            names_by_code[code_key] = str(r["股票名稱"])
            if "持有ETF清單" in stock_list.columns:
                etf_raw = r.get("持有ETF清單", "")
                if etf_raw and str(etf_raw) != "nan":
                    etf_names_by_code[code_key] = [e.strip() for e in str(etf_raw).split(",") if e.strip()][:5]

    calls_made = 0
    new_queue_rows = []

    for code in codes_to_check:
        name = names_by_code.get(code, "")
        if not name:
            continue

        if code in generated_this_month_codes:
            continue

        is_todays_turn = _weekday_bucket(code) == today_weekday
        if not is_todays_turn or calls_made >= max_new_calls:
            continue

        etf_names = etf_names_by_code.get(code, [])
        news_titles = _load_relevant_news_titles(ss, name)
        already_rejected = rejected_kws_by_code.get(code, set())

        existing_all = set()
        if not queue_df.empty:
            existing_all = set(queue_df[queue_df["股票代號"] == code]["關鍵字"].tolist())

        new_kws = _generate_keywords_for_stock(code, name, list(existing_all), etf_names, news_titles)
        calls_made += 1

        new_kws = [kw for kw in new_kws if kw not in already_rejected]

        for kw in new_kws:
            new_queue_rows.append({
                "股票代號": code,
                "股票名稱": name,
                "關鍵字": kw,
                "生成日期": today_str,
                "狀態": STATUS_PENDING,
            })

        if new_kws:
            log.info(f"AI關鍵字候選：{code} {name} 新增 {len(new_kws)} 個待審核關鍵字"
                      f"（ETF根據{len(etf_names)}檔、新聞根據{len(news_titles)}篇）")
        else:
            log.info(f"AI關鍵字候選：{code} {name} 本次無新增（可能全部被停用詞/重複過濾掉）")

    if new_queue_rows:
        base_df = queue_df.drop(columns=["_month"], errors="ignore") if not queue_df.empty else pd.DataFrame(columns=QUEUE_COLS)
        combined = pd.concat([base_df, pd.DataFrame(new_queue_rows)], ignore_index=True) if not base_df.empty else pd.DataFrame(new_queue_rows)
        _write_keyword_queue(ss, combined)
        log.info(f"AI關鍵字審核佇列更新：新增 {len(new_queue_rows)} 筆待審核，本次呼叫AI {calls_made} 次")

    return get_approved_keyword_map(ss)
