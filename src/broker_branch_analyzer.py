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

2026-09-16再追加：使用者接著問，能不能讓AI透過分點走勢圖了解贏家券商的進出策略，
「預估」多方驗證名單裡股票的進出場時間。這裡刻意**不**做「AI預測進場時間」——
Claude讀的是一張截圖，看到的是視覺化的趨勢描述，不是結構化的數字時間序列，讓AI
從一張圖裡講出帶時間刻度的預測，容易讓使用者高估這個判讀的可靠度（違反專案一貫
「資料不足/推論薄弱要明講，不強行給結論」的誠實原則）。改成比照`main.py`裡
`generate_premarket_watch()`既有的「條件式檢查清單，非預測」設計哲學：
`build_entry_exit_checklist()`把這檔股票「多方驗證名單」裡本來就有、每天自動更新
的技術面欄位（KD訊號/MACD訊號/技術面共振/籌碼矛盾）整理成「目前哪些條件成立」的
清單，跟你上傳截圖判讀出的分點動向並列顯示——不合成新的AI推論，純粹是「把兩種
已經存在的資訊放在一起給你看」，時間點跟要不要進場，由使用者自己判斷。
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
# Claude API成本。
# 2026-09-23調高（4→8）：籌碼總覽整合進來後，一檔股票常見組合變成「分點統計+走勢圖
# +技術指標+籌碼總覽近5日/近5週」，使用者實測回報一檔股票常常要準備到6~8張截圖，
# 原本的4張已經不夠用。同時app.py改成「累積上傳清單」介面（可以分好幾次選圖加入
# 清單，湊齊再一次送出分析），所以「單次檔案選取視窗要選幾張」不再是使用者體感的
# 瓶頸，真正的成本考量只剩「單次AI呼叫要處理幾張圖」——8張仍遠低於Claude vision的
# API上限，token成本會隨張數增加，但只在使用者實際按下「AI分析」時才發生一次，不是
# 固定月費。
MAX_ANALYSIS_IMAGES = 8


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

    2026-09-16再追加：使用者傳來實際會用的4張截圖範例，確認典型組合是「1張統計
    表格＋3張走勢圖」——3張走勢圖其實是同一張K線圖＋分點進出長條圖，只是底下疊的
    技術指標面板不同（App一次只能顯示一種指標面板，分別截KD、MACD、成交量三種）。
    這種「同一張圖、不同指標面板」的組合，如果不特別說明，AI容易誤判成三張互不相干
    的獨立圖表分開講——這裡在多圖說明裡額外加一段，明講這種常見組合，並要求技術
    指標的判讀併入第1段「籌碼／分點動向」一起講（分點買賣超動向 × 技術指標是否同步），
    不要跟主要的贏家/輸家判讀切成兩件事。

    2026-09-16修正：原本第3段是「天期切換建議」，假設使用者可以在App裡切換20日/
    60日/120日等不同回顧天期——但使用者實測後回報，他用的App「無法設定期間，只能
    給每日的分點進出圖片，但數字資訊是總結120日的結果」，也就是畫面上的囤貨/出貨/
    贏家/輸家分類，是App自己固定用某個回顧天期（例如120日）算出來的結果，使用者這邊
    沒有調整天期的選項，每天能拿到的只有「當天重新計算一次」的這張總結圖。原本的
    建議（切到20日觀察短線拐點）在這個App上根本做不到，是無效建議。

    改法：既然天期不能切換，唯一能看出「短線拐點」的方式，是靠使用者持續、每天
    上傳同一檔股票的截圖，累積出時間序列，讓AI比對「這幾天贏家分點是否已經從賣
    轉買」──這正好是save_broker_branch_analysis()/load_broker_branch_history()
    已經在做的事（每次上傳都存一筆帶日期的歷史紀錄）。這裡改成把同一檔股票最近
    幾次的分析結果一併放進prompt，讓Claude做跨天比較，取代原本做不到的「切換天期」
    建議。

    2026-09-17再追加：使用者問「從圖片中可以了解他們進出的時間點是否和KD或MACD的
    交叉相符合，進一步抓到邏輯？」——這跟「這個分點背景是誰」不同，背景資訊畫面上
    看不到，但買賣超長條圖跟KD/MACD是畫在同一個時間軸上的，理論上確實可以對照。
    在第1段【贏家分點動向】追加一句，要求Claude额外描述買賣超相對技術指標交叉時間點
    是「領先／同步／落後」，但明確加上兩個誠實限制：(1) AI對齊兩個疊圖面板的精確
    日期能力有限，這只能是粗略的視覺印象，不是逐日精確比對；(2) 一張圖裡樣本數很少
    （可能就那幾波買賣超），不足以驗證成「這個分點一貫的操作邏輯」，prompt裡要求
    用「大致」「看起來」這類保留字眼，資訊不足時要直接說看不出來，不要勉強给結論——
    避免使用者把單張截圖的粗略印象，誤當成統計上驗證過的規則。

    2026-09-23追加（籌碼總覽整合）：使用者傳來券商App「籌碼總覽」頁面的截圖（近5日/
    近5週的外資/投信/自營/法人、融資/融券、大戶/散戶、主力、董監等欄位），問這類資料
    是否有助於判斷買賣時機、能否併入這個手動分析工具。決策（使用者選擇「併入現有券商
    分點工具，順便改名（推薦）」）：不另外做新頁面/新Sheets分頁，直接擴充這個既有的
    上傳流程跟這個函式的prompt，讓它能同時判讀三種畫面類型——分點統計/走勢、K線搭配
    KD/MACD/量的技術指標、籌碼總覽——AI依實際畫面內容判斷收到的是哪一種，不用使用者
    額外註明是哪一類截圖。

    籌碼總覽的欄位可信度不一，必須分開處理（誠實原則，不能把proprietary指標當成官方
    資料一樣自信地呈現）：外資/投信/自營/法人、融資/融券是官方公開資料，可以直接
    引用；大戶/散戶是官方集保週資料，可信但要註明是週頻率；主力是App自行估算的
    proprietary指標，必須明確標註可信度低於官方資料；董監是月更新、天生落後的背景
    參考，不是進出場觸發依據。這也代表原本假設「所有畫面都是App固定回顧天期算出的
    當日總結、不能切換天期」不再成立——籌碼總覽通常直接用近5日/近5週分開顯示，
    prompt裡把「不能切換天期」的說明改成只適用於分點類截圖。

    這個決策不影響SHEET_BROKER_ANALYSIS這張Sheets分頁的名稱（保留"券商分點分析"，
    避免既有歷史分析紀錄的資料遷移風險）——只有app.py的頁面顯示標籤改名。
    
    2026-09-24追加（依App官方說明校正判讀指引）：使用者傳來這個App自己的「籌碼總覽
    說明」畫面（開發商官方文件，不是使用者猜測），把原本判讀指引裡幾個用推測寫的
    細節，改成依官方定義：
    - 更新頻率：主力其實是「交易日18:00後更新」，跟外資/投信/自營/法人（16:50後）
      一樣是**每個交易日**更新，只是比法人晚，不是原本以為的低頻資料；真正屬於
      低頻的只有大戶/散戶（每週一前）跟董監（每月20號前）。主力真正該保留的地方
      是「計算方法不透明、無法驗證」，不是「資料落後」，這兩件事原本混在一起講，
      這次拆開。
    - 「動向」標籤（大買/小買/中立/小賣/大賣、大增/增/中立/減/大減）：官方定義是
      「依這檔股票自己的歷史統計數據加權算出門檻值，再拿當日數值比較後分類」，
      也就是不同股票的同一個標籤（例如都是「小買」）背後對應的絕對張數可能差很多，
      不能拿不同股票的標籤直接互相比較強弱，要搭配實際張數/比例一起看。
    - 新發現兩個原本沒注意到的資訊維度，這次補進判讀指引：「強度」區塊（把當日
      數值放進這檔股票近一年最小值~最大值的區間裡定位，愈靠極端愈少見）跟「排名」
      區塊（當期買賣超/增減金額在全上市櫃公司的名次，只公布前50名，排名愈前面代表
      愈是全市場數一數二的目標，比單看「買超」方向本身更有訊號強度）——這兩個是
      比原始張數更有解讀價值的資訊，如果畫面上有出現，這次明確要求AI要判讀進去。
    - 連續標籤官方只有兩種形態：「連增/連減」（同方向連續）跟「連增轉減/連減轉增」
      （方向剛轉變），原本的指引沒講清楚這個官方定義，這次補上，避免AI自己延伸出
      畫面沒寫的更精確天數。
    """
    stock_label = f"{stock_code} {stock_name}".strip() or "（使用者未提供股票代號/名稱）"

    if recent_history:
        history_lines = "\n".join(
            f"- {h.get('日期', '')}：{h.get('AI分析', '')}" for h in recent_history
        )
        history_block = (
            f"\n\n以下是「{stock_label}」最近幾次上傳的分析結果（由舊到新排列），"
            f"可以拿來比對跨天變化：\n{history_lines}\n"
        )
        trend_instruction = (
            "請特別比對上面歷史紀錄與這次畫面的差異，具體指出哪些分點/法人/大戶等"
            "籌碼方向出現轉變（尤其是原本賣超或減碼的一方這幾次是否已經轉為買超或"
            "增碼、原本買超或囤貨的一方是否還在繼續買），這是判斷短線拐點最主要的"
            "依據。"
        )
    else:
        history_block = ""
        trend_instruction = (
            "這是這檔股票第一次上傳分析，還沒有歷史紀錄可以比對——之後如果持續（例如"
            "每天或每隔幾天）上傳同一檔股票的截圖，系統會自動累積歷史紀錄，之後的分析"
            "就能比對出「贏家分點/法人/大戶等籌碼方向是否轉變」這類需要跨天比較才看"
            "得出來的短線拐點。這次先只根據單一畫面判讀，不臆測未來趨勢。"
        )

    if num_images > 1:
        image_intro = (
            f"你是台股籌碼分析專家。這裡提供了{num_images}張「{stock_label}」的籌碼"
            f"相關截圖，畫面類型可能包含：①券商分點買賣超統計表格或走勢線圖、②K線圖"
            f"搭配KD/MACD/成交量等技術指標面板、③籌碼總覽（外資/投信/自營/法人、"
            f"融資/融券、大戶/散戶、主力、董監等欄位的近5日/近5週彙總畫面）——實際"
            f"內容以畫面顯示為準，不要預設假設每張圖分別是哪一種類型。請把這"
            f"{num_images}張畫面當成同一次判讀的完整資訊，彼此對照、互相補充，不要"
            f"只看其中一張就下結論。\n"
            f"常見組合是「1張統計表格＋數張走勢圖」，走勢圖裡如果看到同一張K線圖搭配"
            f"分點進出長條圖、只是下方疊的技術指標面板不同（KD、MACD、成交量等分開各"
            f"一張），請把它們視為同一組資料的不同角度合併解讀，不要當成互不相干的三張"
            f"圖分開講——技術指標的判讀請併入下面第1段「籌碼／分點動向」一起講，例如"
            f"「贏家分點買超這幾天在放大，同時KD正從低檔翻揚／MACD柱狀由綠轉紅，動能"
            f"方向一致」這種交叉對照，而不是分開各自獨立寫一段。如果其中有籌碼總覽"
            f"畫面，請一併判讀外資/投信/自營/法人、融資/融券、大戶/散戶、主力、董監"
            f"等欄位（判讀方式見下方「籌碼總覽欄位判讀指引」）。"
        )
    else:
        image_intro = (
            f"你是台股籌碼分析專家。這張圖是「{stock_label}」的籌碼相關截圖，可能是"
            f"券商分點買賣超統計表格、K線搭配KD/MACD/成交量等技術指標，或籌碼總覽"
            f"（外資/投信/自營/法人、融資/融券、大戶/散戶、主力、董監等欄位的近5日/"
            f"近5週彙總畫面）——實際內容以畫面顯示為準，請先判斷這張圖屬於哪一種、"
            f"有哪些欄位，再依下面架構判讀。"
        )

    return f"""{image_intro}

關於「天期」：如果畫面是券商分點的統計/走勢截圖，畫面上的囤貨/出貨/贏家/輸家分類
通常是App自己用固定回顧天期（例如過去120日）算出來的，使用者這邊沒有調整天期的
選項，請不要建議使用者「切換到20日/60日」之類的操作，這個App做不到。如果畫面是
籌碼總覽（近5日／近5週等區間並列顯示），則直接依畫面上已經分好的天期判讀短中期
趨勢是否一致即可，不受上述分點App限制影響。

【籌碼總覽欄位判讀指引】如果畫面包含籌碼總覽類型的欄位，依App官方定義的更新頻率/
計算方式分開處理，不要用同樣的確信度呈現：

- 資料更新時間（App官方定義）：外資/投信/自營/法人於交易日16:50後更新；主力於
  交易日18:00後更新（比法人晚，但同樣是每個交易日更新，不是低頻資料）；大戶/散戶
  於每週一前不定期更新（週頻率）；董監於每月20號前不定期更新（月頻率）。請依這個
  說明判斷資料新舊程度，不要自己臆測其他更新頻率。

- 外資/投信/自營/三大法人合計、融資/融券/券賣/借券：官方公開資料，可以直接引用
  判讀，可信度最高。

- 主力：這是App自行計算的「主力籌碼集中度」指標，不是官方三大法人資料，計算方法
  不透明、無法驗證——但更新頻率跟法人一樣是每個交易日（只是較晚，18:00後），不是
  低頻資料。請不要把它跟大戶/散戶/董監混為一談說成「資料落後」，正確的保留態度是
  「計算方法未公開、無法驗證，可信度低於官方法人資料，僅供參考」。

- 大戶/散戶：官方集保結算所資料，可信，但是週更新頻率，判讀時請註明「這是週資料，
  非即時訊號」。

- 董監持股：月更新、天生落後，只能當背景參考，不是進出場時機的觸發依據，請明講
  這點，不要拿來當成「現在該進場/出場」的理由。

- 每個指標的「動向」標籤（大買/小買/中立/小賣/大賣，或大增/增/中立/減/大減）：
  這不是單純的正負值分類，是App依這檔股票自己的歷史統計數據加權算出一個門檻值，
  再拿當日數值跟門檻值比較後分類的——不同股票的同一個標籤（例如都是「小買」）
  背後對應的絕對張數可能差很多，請不要直接拿不同股票的「動向」標籤互相比較強弱，
  要搭配畫面上實際顯示的張數/比例數字一起判讀，標籤只代表「相對這檔股票自己過去
  常態而言算不算多」。

- 如果畫面有「強度」區塊（綠到紅的區間條，標示近一年最小值/最大值，三角形標示
  今天數值落在哪個位置）：這是把當日買賣超/增減張數放進這檔股票近一年的歷史分佈
  裡定位，愈靠近紅色端（近一年最大值）代表近一年少見的大幅買超/增碼，愈靠近綠色端
  代表少見的大幅賣超/減碼——這個「相對自己歷史的極端程度」比單看當日張數本身更有
  參考價值，如果畫面上有這個區塊，請一併判讀，並在分析裡指出今天是否落在近一年的
  極端區間。

- 如果畫面有「排名」區塊（近五日走勢＋今天排名＋前一期排名，紅色數字＝買超/增
  排名、綠色數字＝賣超/減排名、黃色＝無進出）：這是這檔股票當期買賣超/增減金額在
  「全上市櫃公司」裡的名次（只公布前50名），排名數字愈小（例如第1~10名）代表這是
  當期全市場數一數二的買超/增碼目標，訊號強度遠高於只看「買超」這個方向本身；也請
  比較今天排名跟前一期排名的變化（排名明顯進步或惡化本身就值得留意）。畫面上沒有
  出現排名時，代表未進前50名，直接說明「未進榜（屬於一般水準的進出，不是市場級的
  極端訊號）」即可，不要杜撰一個名次。

- App已經算好的連續動向標籤（例如「連3買」「連2轉賣」）：官方定義只有兩種形態——
  「連增/連減」（同方向連續）跟「連增轉減/連減轉增」（方向剛轉變）——可以直接引用
  畫面上顯示的文字，但不可以杜撰畫面沒顯示的天數或標籤，也不要自己延伸成畫面沒講
  的更精確天數。

請仔細判讀畫面上實際顯示的數字與標記，不要杜撰畫面上沒有的資訊，並依據下面架構
給出「可執行」的操作建議：

1.【籌碼／分點動向】依實際畫面內容判讀，只根據畫面實際出現的欄位講，沒出現的
   欄位不用強行講：
   - 如果有分點資料，列出畫面中屬於「贏家」（近期波段獲利最多）的分點，目前是
     買超還是賣超、累計張數大概多少；如果是賣超，提醒「這幾家若連續轉買超轉正，
     才是相對安全的跟隨買點」。
   - 如果有外資/投信/自營/三大法人合計、融資/融券資料，說明目前是買超還是賣超、
     近期方向是否一致。
   - 如果有大戶/散戶資料，說明大戶持股比例近期是否上升，並註明資料頻率。
   - 如果有「主力」欄位，先依上面判讀指引標註可信度，再說明目前方向。
   - 如果有董監持股資料，說明目前趨勢，並註明這是落後的背景參考。
   - 如果畫面有「強度」區間條或「排名」資訊，依上面判讀指引解讀，並整合進同一段
     方向判讀裡（例如「主力今天由中立轉小買，強度落在近一年較高的一端，排名進到
     第12名，屬於近期少見的積極表態」這種整合寫法，不要跟其他籌碼方向拆開單獨講）。
   - 如果畫面裡有K線圖搭配KD/MACD/成交量等技術指標，一併說明目前指標狀態（例如
     KD在低檔/高檔、MACD柱狀翻紅或翻綠、成交量是否放大），並指出上述籌碼/分點
     方向跟技術指標之間有沒有明顯同步（訊號一致更值得留意，訊號不一致則要明講
     「兩者方向不同步，證據還不夠齊全」，不要為了湊出結論硬講成一致）。如果畫面裡
     的分點買賣超長條圖，可以跟KD/MACD交叉的時間點對照，請額外用一句話描述這個
     分點的買賣超「相對技術指標交叉時間點」大致是領先（買賣超先出現、技術指標之後
     才翻轉）、同步（幾乎同時發生）、還是落後（技術指標先翻轉、買賣超才跟上）。
     這只是根據畫面上少數幾波買賣超形狀做的粗略視覺觀察，不是逐日精確比對，也不是
     驗證過的規則，請用「大致」「看起來」這類保留字眼描述，不要講得像已經證實的
     固定行為模式；如果畫面模糊、買賣超波動次數太少、或兩個面板時間軸對不齊，直接
     說「資訊不足，無法判斷領先/落後關係」，不要勉強給結論。

2.【避開的陷阱訊號】找出畫面中可能誤導的訊號，例如：分點「囤貨但同時是輸家」
   （越跌越買、可能已被套牢）；法人買賣方向彼此分歧（例如投信買超但外資賣超）；
   融資大幅增加但股價未同步上漲（可能是散戶追高、籌碼不穩）。提醒不要只看到單一
   買超訊號就衝動跟進，需等到多項訊號一致。

3.【與近期比較，找短線拐點】{trend_instruction}

4.【綜合判斷】總結目前整體籌碼是「買方掌控」「賣方主導」還是「多空拉鋸」，並給出
   一句進場時機建議（例如：等待特定分點轉買、拉回測試某均線再分批、或目前訊號不足
   建議觀望）。

用繁體中文回答，分點/數字盡量具體，但如果畫面模糊或資訊不足以判讀某一項，直接說明
「畫面資訊不足，無法判讀OOO」，不要編造。整體控制在600字以內，用上面1~4的標題分段。
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


def build_entry_exit_checklist(stock_row: dict) -> dict:
    """
    2026-09-16新增：進出場條件checklist——純資料比對，不呼叫AI。

    依「多方驗證名單」裡這檔股票每天自動更新的技術面欄位（KD訊號/MACD訊號/
    技術面共振/籌碼矛盾），整理成「目前哪些條件成立」的清單，跟你上傳截圖判讀出的
    分點動向並列顯示。這是條件checklist，不是預測：只呈現「現在條件夠不夠」，
    不猜測會在哪一天發生轉折，時間點跟要不要進場由使用者自己判斷（見本檔案開頭
    2026-09-16再追加的決策說明——為什麼不做「AI預測進場時間」）。

    MACD/KD的多空判斷標準跟price_fetcher.py::compute_technical_indicators()算
    「技術面共振」燈號時用的是同一套MACD_BULL_SET/KD_BULL_SET等常數，不自己另外
    發明一套標準。

    stock_row：「多方驗證名單」裡這檔股票那一列資料（dict或pandas Series皆可，
    用.get()讀取，缺欄位不會crash，只會標成「資料不足」）。

    回傳：{"items": [{"label", "status"（met/unmet/unknown）, "detail"}, ...],
           "met_count": int, "total_count": int}
    total_count只計「有明確資料可判讀」的項目數（不含unknown），met_count是其中
    成立的項目數，例如"2/3"代表3項有資料可判讀的條件裡有2項目前成立。
    """
    from price_fetcher import MACD_BULL_SET, MACD_BEAR_SET, KD_BULL_SET, KD_BEAR_SET

    def _get(key):
        try:
            val = stock_row.get(key, "")
        except AttributeError:
            val = stock_row[key] if key in stock_row else ""
        return str(val).strip() if val is not None else ""

    items = []

    kd = _get("KD訊號")
    if kd in KD_BULL_SET:
        items.append({"label": "KD指標", "status": "met", "detail": f"{kd}（偏多）"})
    elif kd in KD_BEAR_SET:
        items.append({"label": "KD指標", "status": "unmet", "detail": f"{kd}（偏空）"})
    else:
        items.append({"label": "KD指標", "status": "unknown", "detail": kd or "資料不足"})

    macd = _get("MACD訊號")
    if macd in MACD_BULL_SET:
        items.append({"label": "MACD指標", "status": "met", "detail": f"{macd}（偏多）"})
    elif macd in MACD_BEAR_SET:
        items.append({"label": "MACD指標", "status": "unmet", "detail": f"{macd}（偏空）"})
    else:
        items.append({"label": "MACD指標", "status": "unknown", "detail": macd or "資料不足"})

    resonance = _get("技術面共振")
    if resonance in ("🟢🟢 多頭共振", "🟢 偏多"):
        items.append({"label": "技術面共振", "status": "met", "detail": resonance})
    elif resonance in ("🔴 偏空", "🔴🔴 空頭共振"):
        items.append({"label": "技術面共振", "status": "unmet", "detail": resonance})
    else:
        items.append({"label": "技術面共振", "status": "unknown", "detail": resonance or "資料不足"})

    # 籌碼矛盾：margin_fetcher.py::compute_chip_conflict()只有三種可能——
    # 空字串（無矛盾，中性）、"💡"開頭（散戶減碼/停損但法人在買，這套系統一貫認為
    # 是有利訊號，見compute_chip_conflict()docstring）、"⚠️"開頭（散戶追價但法人在賣，
    # 不利訊號）。用字串前綴判斷，不猜測空字串以外的其他文字格式。
    conflict = _get("籌碼矛盾")
    if conflict.startswith("💡"):
        items.append({"label": "籌碼矛盾狀態", "status": "met", "detail": conflict})
    elif conflict.startswith("⚠️"):
        items.append({"label": "籌碼矛盾狀態", "status": "unmet", "detail": conflict})
    elif conflict:
        items.append({"label": "籌碼矛盾狀態", "status": "unknown", "detail": conflict})
    else:
        items.append({"label": "籌碼矛盾狀態", "status": "unknown", "detail": "無矛盾（中性）"})

    known_items = [i for i in items if i["status"] != "unknown"]
    met_count = sum(1 for i in known_items if i["status"] == "met")
    total_count = len(known_items)

    return {"items": items, "met_count": met_count, "total_count": total_count}