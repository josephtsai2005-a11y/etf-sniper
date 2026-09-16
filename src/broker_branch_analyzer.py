"""
broker_branch_analyzer.py
券商分點籌碼分析：使用者上傳券商分點APP截圖，AI判讀贏家/輸家分點動向，
輔助判斷「跟誰買、避開誰、什麼時候進場」。

背景（2026-09-16需求）：使用者想知道能不能做出「券商分點」資訊。研究後確認：
- TWSE官方查詢系統（bsr.twse.com.tw）有CAPTCHA擋自動化，且條款寫明「不得逕自散布
  或販售」，不適合做自動抓取。
- 第三方付費API（FinMind）雖然可以抓到結構化的券商分點進出資料，但相關資料集
  （TaiwanStockTradingDailyReport系列）需要「Sponsor」等級付費訂閱（查到的第三方
  資料約NT$999/月），且尚未確認能否涵蓋全市場或只有熱門股，屬於需要額外評估成本
  的方案，不在這次範圍。
- 使用者改用Gemini分析券商分點截圖得到的結果（判讀出「贏家分點」轉買賣訊號、
  「輸家囤貨」陷阱警示、切換天期看短線拐點等具體操作建議），證明「AI直接判讀
  截圖」這條路線本身就有實用價值，且Claude API原生支援圖片輸入，不需要額外資料源。

這不是自動化資料抓取，而是讓使用者自行用券商分點APP截圖後上傳，由Claude的圖片
理解能力直接判讀畫面內容。因為需要手動截圖，無法像既有的籌碼/融資券資料一樣自動
涵蓋所有追蹤股票——分析結果會存進Sheets留存歷史。

2026-09-16追加：使用者問「多方驗證名單裡的股票如果剛好有分點分析，能不能更完整地
利用這份資料」。決策原則：**不**把分點分析當成正式評分維度塞進AI報告核心選股公式
（`ai_analyzer.py::generate_investment_report()`那3-5檔的排名邏輯）——因為分點分析
是使用者手動、選擇性上傳的，涵蓋率天生不完整，當成正式評分維度會讓「有上傳」跟
「沒上傳」的股票被不公平地比較。改成當「補充註記」，跟`alert_signals.py`（每日
訊號提醒）完全一樣的模式：純資料比對、不額外呼叫AI、失敗不影響主要內容。
`get_latest_analysis_by_stock()`／`format_recent_analysis_for_report()`這兩個函式
就是給這個用途——同一份查詢結果，`app.py`的「多方驗證名單」頁面拿去做即時內嵌顯示，
`main.py`的AI報告流程拿去格式化成附加段落，兩處共用同一套邏輯，不用維護兩份。
"""
import io
import base64
import logging
import pandas as pd
from datetime import datetime, timedelta
import pytz
from retry_utils import retry_sheets_write

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_BROKER_ANALYSIS = "券商分點分析"
# Claude vision建議的最佳長邊像素，超過此值圖片會被API自動downscale、卻仍依原始
# 大小計算token/上傳時間，所以上傳前自己先縮圖，同時可以壓縮檔案大小加快上傳。
MAX_IMAGE_DIMENSION = 1568
# 2026-09-16追加：使用者實測後回報，判讀一檔股票常常需要同時提供「統計結果截圖」
# （分點買賣超表格）+「線形圖的券商分點進出圖」（走勢線圖）兩張不同呈現方式的畫面，
# 缺任何一張都不夠完整判讀。開放多張上傳，同時設一個上限避免有人無限上傳推高
# Claude API成本——4張已經足夠涵蓋「統計表格+線圖」再加上不同天期各一張的常見組合。
MAX_ANALYSIS_IMAGES = 4


def _prepare_image_for_claude(image_bytes: bytes) -> tuple:
    """
    壓縮/縮放使用者上傳的截圖，避免超過API限制或浪費token。
    回傳 (base64字串, media_type)
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > MAX_IMAGE_DIMENSION:
        scale = MAX_IMAGE_DIMENSION / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return b64, "image/jpeg"


def build_broker_branch_prompt(
    stock_code: str, stock_name: str, recent_history: list = None, num_images: int = 1
) -> str:
    """
    建立分析prompt，架構參考使用者實測過覺得有用的Gemini範例（贏家分點動向／
    避開陷阱訊號／天期比較／綜合判斷四段式），改寫成明確要求Claude只依畫面實際
    內容判讀、不可杜撰數字。

    2026-09-16追加num_images：使用者反映常常需要同時提供「統計結果截圖」（分點買賣
    超表格）+「線形圖的券商分點進出圖」（走勢線圖）才夠完整判讀——純數字表格看不出
    買賣超動能是加速還是趨緩，要搭配線圖；純線圖又看不出實際張數跟券商名稱。
    num_images>1時，開頭改成提醒Claude這是多張不同呈現方式的畫面，要互相對照、
    綜合判讀，不要只看其中一張就下結論，也不要預設假設每張圖分別是什麼類型
    （表格或線圖），依實際畫面內容判斷。

    2026-09-16修正：原本第3段是「天期切換建議」，假設使用者可以在App裡切換20日/
    60日/120日等不同回顧天期——但使用者實測後回報，他用的App「無法設定期間，只能
    給每日的分點進出圖片，但數字資訊是總結120日的結果」，也就是畫面上的囤貨/出貨/
    贏家/輸家分類，是App自己固定用某個回顧天期（例如120日）算出來的，使用者這邊
    沒有調整天期的選項，每天能拿到的只有「當天重新計算一次」的這張總結圖。原本的
    建議（切到20日觀察短線拐點）在這個App上根本做不到，是無效建議。

    改法：既然天期不能切換，唯一能看出「短線拐點」的方式，是靠使用者持續、每天
    上傳同一檔股票的截圖，累積出時間序列，讓AI比對「這幾天贏家分點是否已經從賣
    轉買」──這正好是save_broker_branch_analysis()/load_broker_branch_history()
    已經在做的事（每次上傳都存一筆帶日期的歷史紀錄）。這裡改成把同一檔股票最近
    幾次的分析結果一併放進prompt，讓Claude做跨天比較，取代原本做不到的「切換天期」
    建議。
    """
    stock_label = f"{stock_code} {stock_name}".strip() or "（使用者未提供股票代號/名稱）"

    if recent_history:
        history_lines = "\n".join(
            f"- {h.get('日期', '')}：{h.get('AI分析', '')}" for h in recent_history
        )
        history_block = (
            f"\n\n以下是「{stock_label}」最近幾次上傳的分析結果（由舊到新排列），"
            f"這些畫面跟這次同樣都是App固定回顧天期算出來的當日總結，可以拿來比對"
            f"跨天變化：\n{history_lines}\n"
        )
        trend_instruction = (
            "請特別比對上面歷史紀錄與這次畫面的差異，具體指出哪些分點的買賣方向出現"
            "轉變（尤其是原本賣超的贏家分點這幾次是否已經轉買、原本囤貨的輸家分點是否"
            "還在繼續買），這是判斷短線拐點最主要的依據。"
        )
    else:
        history_block = ""
        trend_instruction = (
            "這是這檔股票第一次上傳分析，還沒有歷史紀錄可以比對——之後如果持續（例如"
            "每天或每隔幾天）上傳同一檔股票的截圖，系統會自動累積歷史紀錄，之後的分析"
            "就能比對出「贏家分點買賣方向是否轉變」這類需要跨天比較才看得出來的短線"
            "拐點。這次先只根據單一畫面判讀，不臆測未來趨勢。"
        )

    if num_images > 1:
        image_intro = (
            f"你是台股籌碼分析專家。這裡提供了{num_images}張「{stock_label}」的券商分點"
            f"相關截圖（APP畫面，可能包含分點買賣超統計表格、也可能包含買賣超走勢線圖等"
            f"不同呈現方式，實際內容以畫面顯示為準）。請把這{num_images}張畫面當成同一次"
            f"判讀的完整資訊，彼此對照、互相補充——例如統計表格能看出實際券商名稱跟張數，"
            f"走勢線圖能看出買賣超動能是加速還是趨緩，兩者合起來看才完整，不要只看其中一張"
            f"就下結論，也不要假設每張圖分別是什麼類型，依實際畫面內容判斷。"
        )
    else:
        image_intro = (
            f"你是台股籌碼分析專家。這張圖是「{stock_label}」的券商分點進出統計截圖"
            f"（APP畫面，通常包含焦點券商、囤貨/出貨張數、贏家/輸家標記、買賣超排行等資訊）。"
        )

    return f"""{image_intro}
畫面上的囤貨/出貨/贏家/輸家分類，是這個App自己用固定回顧天期（例如過去120日）算出
來的，使用者這邊沒有調整天期的選項，請不要建議使用者「切換到20日/60日」之類的操作，
這個App做不到。

請仔細判讀畫面上實際顯示的券商名稱、買賣超張數、囤貨/出貨/贏家/輸家標記，
不要杜撰畫面上沒有的數字，並依據下面架構給出「可執行」的操作建議：

1.【贏家分點動向】列出畫面中屬於「贏家」（近期波段獲利最多）的分點，目前是買超還是
   賣超、累計張數大概多少；如果是賣超，提醒「這幾家若連續轉買超轉正，才是相對安全的
   跟隨買點」。

2.【避開的陷阱訊號】找出畫面中「囤貨但同時是輸家」的分點（越跌越買、可能已被套牢），
   提醒不要只看到買超就衝動跟進，需等到贏家分點也回歸買方。

3.【與近期比較，找短線拐點】{trend_instruction}

4.【綜合判斷】總結目前整體籌碼是「買方掌控」「賣方主導」還是「多空拉鋸」，並給出
   一句進場時機建議（例如：等待特定分點轉買、拉回測試某均線再分批、或目前訊號不足
   建議觀望）。

用繁體中文回答，分點/數字盡量具體，但如果畫面模糊或資訊不足以判讀某一項，直接說明
「畫面資訊不足，無法判讀OOO」，不要編造。整體控制在400字以內，用上面1~4的標題分段。
{history_block}"""


def analyze_broker_branch_screenshot(
    image_bytes_list, stock_code: str, stock_name: str, recent_history: list = None
) -> str:
    """
    上傳一張或多張截圖 -> 呼叫Claude vision -> 回傳分析文字（失敗回傳空字串）。

    2026-09-16追加多圖支援：image_bytes_list是bytes的list（原本是單一bytes）——
    使用者反映常常需要同時提供「統計結果截圖」+「線形圖的券商分點進出圖」兩張才夠
    完整判讀。為了呼叫端方便，也接受單一bytes（自動包成長度1的list），呼叫端不用
    自己判斷要包不包list。超過MAX_ANALYSIS_IMAGES張時只取前MAX_ANALYSIS_IMAGES張，
    避免無限上傳推高單次API成本（呼叫端app.py也會先擋一次、這裡是第二層防呆）。

    recent_history：同一檔股票過去的分析紀錄（由舊到新排列的dict list，通常是
    load_broker_branch_history()篩選出該股票後、取最近幾筆再反轉順序得到），用來讓
    Claude做跨天比較（見build_broker_branch_prompt()的說明）。留空表示第一次上傳。
    """
    from ai_analyzer import call_claude_vision

    if isinstance(image_bytes_list, (bytes, bytearray)):
        image_bytes_list = [image_bytes_list]
    image_bytes_list = list(image_bytes_list)[:MAX_ANALYSIS_IMAGES]
    if not image_bytes_list:
        return ""

    try:
        prepared_images = [_prepare_image_for_claude(b) for b in image_bytes_list]
    except Exception as e:
        log.error(f"券商分點截圖前處理失敗: {e}")
        return ""

    prompt = build_broker_branch_prompt(
        stock_code, stock_name, recent_history=recent_history, num_images=len(prepared_images)
    )
    return call_claude_vision(prompt, prepared_images, max_tokens=1000)


def save_broker_branch_analysis(ss, stock_code: str, stock_name: str, analysis_text: str, trade_date: str):
    """
    存進Sheets留存歷史（2列格式：header+data，跟「盤後原始數據庫」同慣例——不像
    「多方驗證名單」那樣需要額外一列title，因為這張表不是每日job自動寫入，是使用者
    手動上傳時才新增一列，不需要「今日更新時間」這種整表層級的標記）。
    之後若要串進每日AI報告或列出某股票的歷史分析紀錄，直接讀這張表即可。
    """
    if not analysis_text:
        return

    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_BROKER_ANALYSIS not in existing:
        ss.add_worksheet(title=SHEET_BROKER_ANALYSIS, rows=1000, cols=6)
        header = [["日期", "股票代號", "股票名稱", "AI分析", "上傳時間"]]

        def _init():
            ss.worksheet(SHEET_BROKER_ANALYSIS).append_rows(header, value_input_option="USER_ENTERED")

        retry_sheets_write(_init, retries=2, label="券商分點分析表頭初始化")

    ws = ss.worksheet(SHEET_BROKER_ANALYSIS)
    uploaded_at = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    row = [[trade_date, stock_code, stock_name, analysis_text, uploaded_at]]

    def _do_write():
        ws.append_rows(row, value_input_option="USER_ENTERED")

    retry_sheets_write(_do_write, retries=2, label="券商分點分析寫入")
    log.info(f"券商分點分析已存檔：{stock_code} {stock_name}")


def load_broker_branch_history(ss, stock_code: str = None) -> pd.DataFrame:
    """讀取歷史分析紀錄，可選擇篩選單一股票代號（最新在前）。找不到分頁（例如
    使用者從沒上傳過任何截圖）回傳空DataFrame，不視為錯誤。"""
    try:
        ws = ss.worksheet(SHEET_BROKER_ANALYSIS)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame()
        df = pd.DataFrame(vals[1:], columns=vals[0])
    except Exception as e:
        log.info(f"讀取券商分點分析歷史（尚無資料或分頁不存在）: {e}")
        return pd.DataFrame()

    if stock_code and "股票代號" in df.columns:
        df = df[df["股票代號"].astype(str) == str(stock_code)]

    return df.iloc[::-1].reset_index(drop=True)


def get_latest_analysis_by_stock(ss, stock_codes: list, days_lookback: int = 7) -> pd.DataFrame:
    """
    給定一批股票代號（例如當天「多方驗證名單」的全部代號），回傳這些股票裡「最近
    days_lookback天內有上傳過分點分析」的最新一筆紀錄，每檔股票最多一列。

    2026-09-16新增，供兩個地方共用：
    - app.py「多方驗證名單」頁面：即時內嵌顯示，跟頁面上既有的「🔔今日訊號提醒」
      區塊同一種「純資料交集比對」模式。
    - main.py的AI報告流程：格式化後（見format_recent_analysis_for_report()）當成
      附加段落接進報告，不影響報告核心選股評分邏輯。

    days_lookback預設7天（比照專案裡其他地方常見的「近7日」窗口慣例），避免顯示
    太久以前、可能已經過時的分點判讀；找不到分頁或股票代號清單為空都安全回傳空
    DataFrame，不拋例外。
    """
    if not stock_codes:
        return pd.DataFrame()

    all_hist = load_broker_branch_history(ss)  # 最新在前
    if all_hist.empty or "股票代號" not in all_hist.columns or "日期" not in all_hist.columns:
        return pd.DataFrame()

    codes_set = {str(c) for c in stock_codes if str(c).strip()}
    filtered = all_hist[all_hist["股票代號"].astype(str).isin(codes_set)].copy()
    if filtered.empty:
        return filtered

    cutoff = (datetime.now(TW_TZ) - timedelta(days=days_lookback)).strftime("%Y-%m-%d")
    filtered = filtered[filtered["日期"].astype(str) >= cutoff]
    if filtered.empty:
        return filtered

    # all_hist已經是最新在前，drop_duplicates(keep="first")等於「每檔股票只留最新一筆」
    filtered = filtered.drop_duplicates(subset=["股票代號"], keep="first").reset_index(drop=True)
    return filtered


def format_recent_analysis_for_report(recent_df: pd.DataFrame) -> str:
    """
    把get_latest_analysis_by_stock()的結果格式化成可以直接接進每日AI報告的文字段落。
    純文字組裝，不呼叫AI——這段文字是「附加參考」，不會被送進主報告的Claude prompt
    重新加權分析，使用者自己判斷要不要採信（見本檔案開頭2026-09-16追加的決策說明）。
    """
    if recent_df.empty:
        return ""
    blocks = []
    for _, r in recent_df.iterrows():
        code = r.get("股票代號", "")
        name = r.get("股票名稱", "")
        date = r.get("日期", "")
        text = r.get("AI分析", "")
        blocks.append(f"**{code} {name}**（{date}上傳）\n{text}")
    return "\n\n".join(blocks)