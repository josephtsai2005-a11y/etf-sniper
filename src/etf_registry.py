"""
etf_registry.py（2026-09-11新增）
季度ETF清單管理：掃描市場上現有的主動式ETF、把新的ETF自動納入追蹤名單、幫目前追蹤中
的ETF標註近期績效表現，讓使用者比較清楚該追蹤/操作哪幾檔ETF。

背景（使用者原始需求）：
「每一季掃描一遍市場上現有的ETF，將新的ETF納入我們的名單，並找出哪些ETF是表現好的，
在我們的ETF名單上備註。這樣可以讓我們比較瞭解可以追蹤哪幾隻ETF操作」

三個關鍵設計決策（皆已跟使用者確認）：
1. 新ETF「直接自動加入追蹤」，不設待審核暫存區。
2. 「表現好」用透明的多期報酬率四分位排名（近1月/近3月/今年以來），不做成混合規模(AUM)
   等因素的黑箱綜合分數——理由詳見annotate_performance()的docstring與下方「方法論」一節。
3. 由新增的Cloud Run Job（main.py的RUN_MODE=etf_scan）搭配Cloud Scheduler每季觸發一次，
   跟現有4個Job（daily/news/ai/inst）同一套架構。

## 方法論：為什麼用「透明報酬率排名」而不是「規模加權綜合分數」

WebSearch確認台灣市場對主動式ETF績效有豐富的公開討論，但這些討論本身就是兩個獨立角度，
不是市場上已經有公認的單一加權公式：
- 純報酬率排行榜（cmoney.tw、TVBS、money101.com.tw、槓桿學院、Yahoo奇摩股市等媒體/論壇
  都固定在做的「XX月報酬排行」），直接比報酬率，讀者一看就懂差異從哪裡來。
- 「規模魔咒」敘事（商周新財富備忘錄、鏡週刊等）：部分報導觀察到規模衝太快的主動式ETF，
  操盤彈性受限，報酬反而不如中小規模的同類ETF——這是一個「規模可能是報酬的負相關因素」
  的觀察，不是說「規模」本身該被當成正面加分項揉進一個分數。

如果把「規模」也塞進一個综合分數，會有兩個問題：(1) 這次沒有可靠、已在這個專案裡驗證過
的AUM/規模資料來源，硬湊等於用未經驗證的輸入去產生一個看起來精確的假分數；(2) 就算有
規模資料，「規模該加分還是扣分」本身在市場上都還有爭議（規模太小可能代表乏人問津/流動性
差，規模太大又可能有「規模魔咒」），不是單純「越大越好」，勉強決定一個方向去加權，
反而比不呈現規模資訊更容易誤導人。

沿用專案一貫原則「新技術指標先做顯示，不急著改評分公式」——這裡做法是只呈現交易所
每天都看得到、算法清楚的「報酬率」，讓使用者自己判斷，不是幫使用者做一個藏著主觀權重的
單一是非題。規模/AUM角度作為文件記錄下來的已知考量，留待之後如果找到可靠且驗證過的資料
來源，再考慮額外呈現（而不是混進同一個分數）。

⚠️ 重要限制：這個檔案裡fetch_market_active_etf_list()的TWSE網頁解析邏輯【尚未在正式環境
驗證過】。開發時的sandbox網路權限完全無法連線TWSE（WebFetch跟直接curl皆被擋下，確認是
沙盒本身的網路限制，不是程式邏輯問題），沒有辦法對照真實的HTML回應調整解析邏輯。部署到
正式環境（Cloud Run Job，網路權限與sandbox不同）後，第一次執行請務必檢查log：
- 預期至少能掃描到目前已知在追蹤的25檔（沿用fetcher.py::ETF_LIST）。
- 如果掃描到的數量遠低於25、或是0，代表這裡的表格解析邏輯需要依實際HTML結構調整
  （不會影響現有25檔ETF的每日抓取——那一段走的是fetcher.py::get_tracked_etf_list()的
  安全網退回機制，退回時繼續使用ETF_LIST，不受這裡影響）。

## 2026-09-11上線後修正2：績效計算改用「全市場單日快照」，不再逐檔查歷史序列

第一次正式上線後，compute_etf_performance()原本用price_fetcher.py::get_stock_price_
history()逐檔查詢STOCK_DAY（每檔ETF內部還要拆成13個月份的請求），25~33檔ETF疊加起來
單次執行會對TWSE發出上百次請求。實測（兩次正式Cloud Run執行 + 使用者在自家網路的本機
diagnose_rate_limit.py複測）都在恰好第6檔ETF（累計約85次請求左右）開始整批失敗，
HTTP狀態碼428、回應是TWSE自己的防爬蟲HTML頁面（不是JSON）。使用者從完全不同的網路
（住家/公司IP，不是Google Cloud）重跑同一套請求節奏，結果在幾乎一樣的位置一樣整批擋下，
這證明問題出在「短時間內對TWSE發出的請求『總量』」本身（TWSE的限制），跟是不是Cloud Run
的對外IP被針對無關——之前加的escalating cooldown/circuit breaker（見下方已移除的
PERFORMANCE_GIVE_UP_THRESHOLD相關邏輯）只能防止Job無限卡住，沒辦法真正解決「資料抓不
完整」的根本問題，即使冷卻累計超過10分鐘依然完全沒有恢復。

改用TWSE另一個既有端點`MI_INDEX`（price_fetcher.py::fetch_bulk_daily_quote()已經在用
同一個端點做「全市場當日收盤行情」，2026-09-01就寫好但一直沒有實測驗證過——這次意外地
用使用者本機的診斷腳本連帶驗證了這個端點格式是對的）：這個端點一次請求就回傳「當天全部
上市股票/ETF」的收盤價，不是「一檔股票一段期間」。近1月/近3月/今年以來報酬率其實只需要
4個時間點的收盤價（今天、約1個月前、約3個月前、今年年初），改成對這4個時間點各打1次
全市場快照（遇到假日/非交易日會自動往前一天找，最多回溯8天），不管追蹤幾檔ETF，
固定只需要4~最多約32次請求（4個時間點 × 最多8次回退嘗試），比原本165次少了一個數量級
以上，也不再需要cooldown/circuit breaker這些防禦性機制——請求量本身已經低到不會觸發
TWSE的限制。

代價：因為改成只看4個時間點的收盤價而非完整的每日序列，「近1月/近3月」從「精確的21/63個
交易日」變成「約30/90個『日曆天』回推、遇到非交易日往前找最近一個有資料的交易日」的近似
值，跟原本用交易日數回推比會有幾天的誤差（通常1-2個交易日內），但對「表現領先/中等/落後」
這種四分位分類來說，這個誤差不影響分類結果的判斷力，換取請求量少一個數量級是值得的取捨。
"""
import re
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup

from fetcher import ETF_LIST
from retry_utils import retry_sheets_write

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})

# TWSE官方慣例：主動式ETF代號固定6碼，格式為「00」開頭+3碼數字+英文字母，第6碼代表類型
# （A=股票型主動式ETF，例如00403A；D=債券型主動式ETF，例如00982D）。
# 來源：https://www.twse.com.tw/zh/products/securities/etf/products/active-list.html
ACTIVE_ETF_CODE_PATTERN = re.compile(r"^00\d{3}[AD]$")

SHEET_REGISTRY = "ETF清單管理"

# _find_market_closes_near()往回找交易日快照時，最多回溯的天數（處理週末/連假這種
# 非交易日）。8天涵蓋得了一般連假（含國定假日調整放假），提成模組層級常數方便測試引用。
SNAPSHOT_MAX_LOOKBACK_DAYS = 8

REGISTRY_COLUMNS = [
    "ETF代碼", "ETF名稱", "追蹤狀態", "來源", "加入日期",
    "近1月報酬%", "近3月報酬%", "今年以來報酬%", "資料筆數", "備註", "最後掃描日期",
]


def fetch_market_active_etf_list(retries: int = 2) -> pd.DataFrame:
    """
    掃描TWSE公開的「上市有價證券代號及名稱」清單，抓出所有符合主動式ETF代號格式的標的。
    不是只認目前已追蹤的清單，這樣才能真正偵測到「新上市」的主動式ETF。

    來源：isin.twse.com.tw/isin/C_public.jsp?strMode=2（上市證券，strMode=2）。這個網址
    已知需要明確指定Big5編碼（resp.encoding = "big5"），requests常會自動偵測成錯誤編碼
    導致中文亂碼，沿用專案裡institutional_fetcher.py等模組已經踩過的同一個坑。

    回傳：DataFrame，欄位「ETF代碼」／「ETF名稱」。任何失敗（連線/解析錯誤/找不到表格）
    回傳空DataFrame——呼叫端run_quarterly_etf_scan()遇到空結果時會跳過「新增ETF」這一步，
    只針對既有追蹤清單做績效標註，不會因為這裡掃描失敗就誤判成「市場上已經沒有其他ETF」
    而錯誤地把既有追蹤清單清空或標記異常。

    2026-09-11第一次正式上線實測後修正：原本的版本裡，「table抓到了但0筆吻合ETF代號格式」
    這種情況會被當成例外，觸發重試——但這其實是邏輯/頁面結構判斷錯誤，不是網路瞬斷這種
    暫時性問題，對同一個URL、同一套解析邏輯再打一次完全不會有不同結果，只是白白讓container
    在512Mi記憶體限制下把整個大頁面（isin.twse.com.tw這份「全部上市證券」清單，用
    BeautifulSoup解析對記憶體負擔本來就不小）重複解析第二次，實測第一次上線時就是這樣
    被OOM（Out of memory）直接砍掉整個container，執行狀態顯示failed，log裡連
    「第2次失敗」都還沒印出來就被殺了。修法：(1) 改用lxml解析器（比html.parser省記憶體、
    速度也快，requirements.txt本來就有這個套件）；(2) 不再只認soup.find("table")抓到的
    第一個table——這個頁面很可能有多個table（版面配置用的table、跟真正證券清單table），
    改成掃描全部table、挑「解析出最多筆吻合ETF代號格式資料」的那一個，不用事先猜測是第
    幾個table；(3) 「table存在但0筆吻合」不再視為例外去重試，直接回傳空DataFrame，
    只有真正的連線/逾時/例外（requests丟出的Exception）才會觸發重試。
    """
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, timeout=30)
            resp.encoding = "big5"
            soup = BeautifulSoup(resp.text, "lxml")
            tables = soup.find_all("table")
            if not tables:
                raise ValueError("找不到任何table，TWSE頁面結構可能已變更")

            # 掃描全部table，挑吻合筆數最多的那一個當作真正的證券清單table——不用事先猜測
            # 是第幾個table，避免頁面版面配置（例如外層還有一層版面table）誤判成資料table。
            best_records = []
            for table in tables:
                records = []
                for tr in table.find_all("tr"):
                    tds = tr.find_all("td")
                    if not tds:
                        continue
                    first_cell = tds[0].get_text(strip=True)
                    # 儲存格內容格式例如「00981A　主動统一台灣高息动能」（代號+全形空白+
                    # 名稱），沿用TWSE這份清單一貫的排版慣例。
                    parts = first_cell.split("　")
                    if len(parts) < 2:
                        continue
                    code, name = parts[0].strip(), parts[1].strip()
                    if ACTIVE_ETF_CODE_PATTERN.match(code):
                        records.append({"ETF代碼": code, "ETF名稱": name})
                if len(records) > len(best_records):
                    best_records = records

            del soup, tables  # 這份頁面可能不小，解析完盡快釋放，降低記憶體峰值

            if not best_records:
                # 這不是連線問題——頁面抓得到、table也解析得出來，只是掃過全部table都沒有
                # 任何一筆吻合預期格式，代表頁面實際結構/排版跟這裡假設的不一樣，重試同一個
                # URL、同一套邏輯不會有不同結果，不觸發重試（避免像2026-09-11第一次上線那樣
                # 白白重複解析一次大頁面把記憶體榨乾）。
                log.warning("市場ETF清單掃描：頁面抓取與解析都成功，但掃過全部table後仍找不到"
                            "任何符合主動式ETF代號格式的項目——可能是頁面實際結構跟這裡假設的"
                            "不同，需要依實際HTML調整解析邏輯，不重試")
                return pd.DataFrame()

            df = pd.DataFrame(best_records).drop_duplicates(subset=["ETF代碼"]).reset_index(drop=True)
            log.info(f"市場主動式ETF掃描完成：偵測到 {len(df)} 檔")
            return df
        except Exception as e:
            last_error = e
            if attempt < retries:
                log.warning(f"市場ETF清單掃描第{attempt + 1}次失敗（連線/逾時等例外），重試中: {e}")
                time.sleep(3 * (attempt + 1))
                continue
            log.warning(f"市場主動式ETF掃描失敗（已重試{retries}次），本次跳過新增ETF步驟: {last_error}")
            return pd.DataFrame()
    return pd.DataFrame()


def _fetch_all_market_closes(date_str: str, retries: int = 1) -> dict:
    """
    抓某一天「全市場」收盤價快照（TWSE MI_INDEX，1次請求涵蓋所有上市股票/ETF），
    回傳 {證券代號: 收盤價} 的dict。

    跟price_fetcher.py::fetch_bulk_daily_quote()是同樣的資料來源/端點，這裡另外寫一個
    輕量版本（只留代號+收盤價，不轉換其他欄位），刻意不直接呼叫fetch_bulk_daily_quote()——
    避免這個檔案對price_fetcher.py內部欄位格式（成交量/成交金額等這裡用不到的欄位）產生
    不必要的耦合，兩邊各自獨立維護自己實際用到的最小欄位子集。

    非交易日、查無資料、或連線例外，都回傳空dict（不拋例外）——呼叫端
    _find_market_closes_near()看到空dict就會自動往前一天找，不需要這裡區分「非交易日」
    跟「暫時性網路錯誤」這兩種情況。
    """
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = {"response": "json", "date": date_str, "type": "ALLBUT0999"}
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=20)
            data = resp.json()
            if data.get("stat") != "OK":
                return {}
            stock_table = None
            for t in data.get("tables", []):
                fields = t.get("fields", [])
                if "證券代號" in fields and "收盤價" in fields:
                    stock_table = t
                    break
            if stock_table is None:
                return {}
            fields = stock_table["fields"]
            code_idx = fields.index("證券代號")
            close_idx = fields.index("收盤價")
            closes = {}
            for row in stock_table.get("data", []):
                code = str(row[code_idx]).strip()
                raw_close = str(row[close_idx]).replace(",", "").strip()
                try:
                    closes[code] = float(raw_close)
                except ValueError:
                    continue
            return closes
        except Exception as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.debug(f"全市場收盤價快照抓取失敗 ({date_str}，已重試{retries}次): {e}")
            return {}
    return {}


def _find_market_closes_near(target_date: datetime, max_lookback_days: int = SNAPSHOT_MAX_LOOKBACK_DAYS):
    """
    從target_date開始，每次抓不到資料就往前推1天，最多回溯max_lookback_days天，
    直到抓到有資料的交易日快照為止——處理週末/國定連假這些非交易日（TWSE非交易日這個
    端點回傳的stat不會是"OK"，或是有OK但沒有個股明細表格）。

    回傳 (實際抓到資料的日期字串YYYYMMDD, {代號: 收盤價})；回溯到底仍找不到時回傳(None, {})。
    """
    cursor = target_date
    for _ in range(max_lookback_days):
        date_str = cursor.strftime("%Y%m%d")
        closes = _fetch_all_market_closes(date_str)
        if closes:
            return date_str, closes
        cursor -= timedelta(days=1)
    return None, {}


def compute_etf_performance(etf_codes: list) -> pd.DataFrame:
    """
    計算每檔ETF的近期報酬率，供annotate_performance()標註「表現好壞」用。

    2026-09-11上線後第二次修正：完全改寫，不再逐檔查詢歷史序列，改成只抓4個時間點
    （今天、約1個月前、約3個月前、今年年初）的「全市場單日收盤價快照」（TWSE MI_INDEX，
    見_fetch_all_market_closes()/_find_market_closes_near()）。不管追蹤幾檔ETF，固定
    只需要4個時間點 × 最多SNAPSHOT_MAX_LOOKBACK_DAYS次回退嘗試（處理假日）的請求量，
    從原本「逐檔查歷史序列」動輒上百次請求降到頂多幾十次，徹底避開TWSE對請求「總量」的
    限制（詳見本檔案開頭「2026-09-11上線後修正2」的完整說明，含使用者實測證據）。

    報酬率計算：(該ETF在「最新」快照的收盤價 / 該ETF在對應基準快照的收盤價 - 1) * 100
    - 近1月報酬%：基準快照＝約30天前（往前找最近一個有資料的交易日）
    - 近3月報酬%：基準快照＝約90天前
    - 今年以來報酬%（YTD）：基準快照＝今年1月1日（往前找的話會落到去年12月，所以這裡改成
      「往後」找最近一個有資料的交易日——用_find_market_closes_near時傳入的target_date
      設在1/1，該函式只會往前找，所以YTD的基準改用另一個機制，見下方實作）。

    任一時間點該ETF沒有收盤價（快照裡完全查不到這個代號，最常見是ETF今年才上市，早期快照
    時它還沒開始交易），或整個快照抓取失敗，對應欄位留None（不是0%）——0%代表「持平」是
    有意義的數字，None代表「不知道」，兩者不能混為一談，沿用專案一貫原則。

    回傳：DataFrame，欄位 ETF代碼／近1月報酬%／近3月報酬%／今年以來報酬%／資料筆數
    （資料筆數＝這4個時間點中，這檔ETF查得到收盤價的筆數，最大4，僅供參考用，不再是
    交易日數）。
    """
    today = datetime.now()

    # YTD基準：今年1月1日附近的交易日快照。1/1通常是元旦假期，往前找會跳到去年，
    # 這裡改成從1/1開始「往後」最多找SNAPSHOT_MAX_LOOKBACK_DAYS天（新年開紅盤通常
    # 1月初幾天內就會開始交易）。
    jan1 = datetime(today.year, 1, 1)
    ytd_date, ytd_closes = None, {}
    cursor = jan1
    for _ in range(SNAPSHOT_MAX_LOOKBACK_DAYS):
        date_str = cursor.strftime("%Y%m%d")
        closes = _fetch_all_market_closes(date_str)
        if closes:
            ytd_date, ytd_closes = date_str, closes
            break
        cursor += timedelta(days=1)

    latest_date, latest_closes = _find_market_closes_near(today)
    m1_date, m1_closes = _find_market_closes_near(today - timedelta(days=30))
    m3_date, m3_closes = _find_market_closes_near(today - timedelta(days=90))

    log.info(f"績效計算快照：最新={latest_date}({len(latest_closes)}檔) "
             f"1個月前={m1_date}({len(m1_closes)}檔) 3個月前={m3_date}({len(m3_closes)}檔) "
             f"年初={ytd_date}({len(ytd_closes)}檔)")

    def _ret(latest, base):
        if latest is None or base is None or base == 0:
            return None
        return round((latest / base - 1) * 100, 2)

    records = []
    for code in etf_codes:
        latest_close = latest_closes.get(code)
        r1m = _ret(latest_close, m1_closes.get(code))
        r3m = _ret(latest_close, m3_closes.get(code))
        ytd = _ret(latest_close, ytd_closes.get(code))
        data_points = sum(1 for c in (latest_close, m1_closes.get(code),
                                       m3_closes.get(code), ytd_closes.get(code)) if c is not None)
        records.append({
            "ETF代碼": code, "近1月報酬%": r1m, "近3月報酬%": r3m,
            "今年以來報酬%": ytd, "資料筆數": data_points,
        })

    return pd.DataFrame(records)


def annotate_performance(perf_df: pd.DataFrame, rank_period: str = "近3月報酬%") -> pd.DataFrame:
    """
    把compute_etf_performance()算出來的報酬率，轉換成人看得懂的「備註」標籤。

    採用「透明的多期報酬率四分位排名」，不做成混合各項因素（含規模/AUM等）加權算出來的
    單一黑箱分數。完整理由見本檔案開頭「方法論」一節，摘要三點：(1) 專案一貫原則是
    「新技術指標先做顯示，不急著改評分公式」；(2) 台灣市場對主動式ETF的公開討論本身就是
    報酬排行榜／規模魔咒觀察兩個獨立角度，不是已有公認的加權公式；(3) 這次沒有可靠、
    已驗證過的規模/AUM資料來源，硬湊分數等於用未驗證的輸入產生一個看似精確的假分數。

    rank_period: 用哪一期報酬率排名/分四分位，預設「近3月報酬%」——比近1月更能反映持續
    的操盤表現、不會被單一天的市場波動主導；比「今年以來」更即時、不會被年初以前很久的
    表現拖累近期判斷。

    2026-09-11上線後第二次修正：compute_etf_performance()改成「4個時間點快照」算法後，
    「資料筆數」的意義從「交易日數」變成「4個時間點中查得到收盤價的筆數」（最大4），
    不再適合用原本的min_data_points=40這種交易日數門檻判斷「資料是否足夠」——改成直接
    看rank_period那一期報酬率本身算不算得出來（notna），算不出來（通常是這檔ETF在
    對應基準時間點還沒上市/沒有收盤價）就是「資料尚不足」，語意上更直接、不用額外參數。

    分類邏輯：
    - rank_period對應的報酬率是None：「🆕 資料尚不足，暫無法比較」（新上市ETF常見情況）。
    - 樣本數（扣除資料不足者）< 4 檔時，四分位沒有統計意義，改用「正報酬=領先／負報酬=落後／
      恰好0=中等」這種簡單判斷。
    - 樣本數 >= 4 檔時，依rank_period數值排序分四等分：前25% 🟢表現領先／後25% 🔴表現落後／
      中間50% ⚡表現中等。

    回傳：perf_df加上「備註」欄位的複本，不修改傳入的原始DataFrame。
    """
    df = perf_df.copy()
    df["備註"] = "🆕 資料尚不足，暫無法比較"

    valid = df[df[rank_period].notna()].copy()

    if len(valid) >= 4:
        q1 = valid[rank_period].quantile(0.25)
        q3 = valid[rank_period].quantile(0.75)

        def _label(v):
            if v >= q3:
                return "🟢 表現領先"
            elif v <= q1:
                return "🔴 表現落後"
            return "⚡ 表現中等"

        df.loc[valid.index, "備註"] = valid[rank_period].apply(_label)
    elif len(valid) > 0:
        df.loc[valid.index, "備註"] = valid[rank_period].apply(
            lambda v: "🟢 表現領先" if v > 0 else ("🔴 表現落後" if v < 0 else "⚡ 表現中等")
        )

    return df


def _write_etf_registry_sheet(ss, registry_df: pd.DataFrame, scan_date: str):
    """
    把run_quarterly_etf_scan()整理好的結果寫入「ETF清單管理」分頁（含重試保護）。

    格式（第一列標題、第二列欄位名、第三列起資料）刻意跟main.py::_write_streak_sheet()
    一致，也是fetcher.py::get_tracked_etf_list()解析這張表時預期的格式——兩邊要維持一致，
    改動這裡的寫入格式時，get_tracked_etf_list()的讀取邏輯也要一併確認/更新。
    """
    existing_sheets = [w.title for w in ss.worksheets()]
    if SHEET_REGISTRY not in existing_sheets:
        ws = ss.add_worksheet(title=SHEET_REGISTRY, rows=200, cols=15)
    else:
        ws = ss.worksheet(SHEET_REGISTRY)

    def _do_write(ws=ws, registry_df=registry_df):
        ws.clear()
        ws.append_row([f"{SHEET_REGISTRY}　最後掃描：{scan_date}"])
        ws.append_row(registry_df.columns.tolist())
        ws.append_rows(registry_df.fillna("").values.tolist(), value_input_option="USER_ENTERED")

    retry_sheets_write(_do_write, retries=2, label=f"{SHEET_REGISTRY}寫入")


def run_quarterly_etf_scan(ss, retries: int = 2) -> pd.DataFrame:
    """
    季度ETF清單管理主流程，供main.py的RUN_MODE=etf_scan呼叫（新增的Cloud Run Job，
    由Cloud Scheduler每季觸發一次）。

    步驟：
    1. 讀取現有的「ETF清單管理」分頁。第一次執行、分頁還不存在時，用fetcher.py內建的
       ETF_LIST當作起始追蹤清單（來源標記「內建清單」）——這25檔本來就是專案已經在
       追蹤的，不需要靠這次掃描才「發現」。
    2. 呼叫fetch_market_active_etf_list()掃描整個市場現有的主動式ETF；掃描失敗（回傳空）
       時記錄警告、跳過「新增ETF」這一步，避免因為「這次連不上TWSE」被誤判成
       「市場上真的沒有其他ETF」。
    3. 市場掃描結果裡，代號不在目前追蹤清單的，直接加入追蹤（使用者已明確選擇「直接自動
       加入追蹤」，不做待審核暫存），標記來源「季度掃描新增」、加入日期為本次掃描日期。
    4. 目前「追蹤中」的ETF，如果這次市場掃描完全沒掃到，不會自動移除/停用追蹤——只在
       「備註」欄位加註提醒，交由人工確認是否已下市/代號變更。
       ⚠️ 這是這次設計上的預設值（保守、不自動刪除），還沒有和使用者明確確認過這個
       子決策本身，只確認過「新ETF直接自動加入」，「舊ETF消失了怎麼辦」尚待使用者回覆。
    5. 對所有「追蹤中」的ETF計算近期績效（compute_etf_performance）並標註
       （annotate_performance）。
    6. 整份結果寫入「ETF清單管理」分頁（_write_etf_registry_sheet）。

    回傳整理好的registry DataFrame（方便main.py記錄摘要log，或測試直接檢查回傳值，
    不用另外重讀Sheets）。
    """
    scan_date = datetime.now().strftime("%Y%m%d")
    log.info(f"===== 季度ETF清單掃描開始 ({scan_date}) =====")

    # 步驟1：讀取現有清單，第一次執行時用ETF_LIST當起始清單
    existing_df = pd.DataFrame()
    try:
        ws = ss.worksheet(SHEET_REGISTRY)
        all_vals = ws.get_all_values()
        if len(all_vals) >= 3:
            existing_df = pd.DataFrame(all_vals[2:], columns=all_vals[1])
    except Exception:
        pass

    if existing_df.empty or "ETF代碼" not in existing_df.columns:
        log.info(f"「{SHEET_REGISTRY}」分頁不存在或無資料，使用內建ETF_LIST（{len(ETF_LIST)}檔）當作起始追蹤清單")
        existing_df = pd.DataFrame([
            {"ETF代碼": code, "ETF名稱": "", "追蹤狀態": "追蹤中", "來源": "內建清單", "加入日期": scan_date}
            for code in ETF_LIST
        ])

    for col in ["ETF名稱", "追蹤狀態", "來源", "加入日期"]:
        if col not in existing_df.columns:
            existing_df[col] = ""
    existing_df["追蹤狀態"] = existing_df["追蹤狀態"].replace("", "追蹤中")
    existing_df["ETF代碼"] = existing_df["ETF代碼"].astype(str).str.strip()

    # 只保留身分/追蹤欄位，績效相關欄位每次都重新計算，避免merge時新舊欄位同名衝突
    identity_cols = ["ETF代碼", "ETF名稱", "追蹤狀態", "來源", "加入日期"]
    existing_df = existing_df[[c for c in identity_cols if c in existing_df.columns]]

    existing_codes = set(existing_df["ETF代碼"])

    # 步驟2：掃描市場現況
    market_df = fetch_market_active_etf_list()

    # 步驟3：新代號直接加入追蹤
    new_rows = []
    if not market_df.empty:
        for _, row in market_df.iterrows():
            code = str(row["ETF代碼"]).strip()
            if code and code not in existing_codes:
                new_rows.append({
                    "ETF代碼": code, "ETF名稱": row.get("ETF名稱", ""),
                    "追蹤狀態": "追蹤中", "來源": "季度掃描新增", "加入日期": scan_date,
                })
        if new_rows:
            log.info(f"季度掃描發現 {len(new_rows)} 檔新的主動式ETF，直接加入追蹤："
                      f"{[r['ETF代碼'] for r in new_rows]}")
        else:
            log.info("季度掃描：沒有發現尚未追蹤的新主動式ETF")
    else:
        log.warning("市場ETF掃描失敗或無資料，本次跳過「新增ETF」步驟，僅更新既有追蹤清單的績效標註")

    registry_df = pd.concat([existing_df, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else existing_df.copy()

    # 步驟4：追蹤中但這次掃描沒掃到的，標記提醒（不自動移除，見函式docstring的⚠️說明）
    registry_df["備註"] = ""
    market_codes = set(market_df["ETF代碼"].astype(str).str.strip()) if not market_df.empty else set()
    if market_codes:
        tracked_mask = registry_df["追蹤狀態"] == "追蹤中"
        missing_mask = tracked_mask & (~registry_df["ETF代碼"].isin(market_codes))
        registry_df.loc[missing_mask, "備註"] = "⚠️ 本次市場掃描未偵測到，請人工確認是否已下市/代號變更"

    # 步驟5：績效計算 + 標註
    # 2026-09-11上線後第二次修正：compute_etf_performance()改成「4個時間點快照」算法
    # （見本檔案開頭「上線後修正2」），不再需要months_back這種依月份動態調整回溯範圍的
    # 參數——不管追蹤幾檔ETF、現在是幾月，請求量都固定是4個時間點左右，不用再為了省
    # 請求量而動態調整回溯月數。
    tracked_codes = registry_df.loc[registry_df["追蹤狀態"] == "追蹤中", "ETF代碼"].tolist()
    if tracked_codes:
        perf_df = compute_etf_performance(tracked_codes)
        perf_df = annotate_performance(perf_df)

        registry_df = registry_df.merge(perf_df, on="ETF代碼", how="left", suffixes=("", "_perf"))
        if "備註_perf" in registry_df.columns:
            def _combine_notes(row):
                parts = [str(n) for n in [row.get("備註", ""), row.get("備註_perf", "")] if n]
                return "；".join(parts)
            registry_df["備註"] = registry_df.apply(_combine_notes, axis=1)
            registry_df = registry_df.drop(columns=["備註_perf"])

    registry_df["最後掃描日期"] = scan_date

    for c in REGISTRY_COLUMNS:
        if c not in registry_df.columns:
            registry_df[c] = ""
    registry_df = registry_df[REGISTRY_COLUMNS]

    _write_etf_registry_sheet(ss, registry_df, scan_date)
    log.info(f"===== 季度ETF清單掃描完成：共追蹤 {len(tracked_codes)} 檔 =====")
    return registry_df


if __name__ == "__main__":
    import sys
    print("這個模組設計上由main.py（RUN_MODE=etf_scan）呼叫run_quarterly_etf_scan(ss)，"
          "需要真實的gspread Spreadsheet物件，不支援直接命令列執行完整流程。")
    print("若只想測試市場掃描本身（不需要Sheets），可執行：")
    print("  python -c \"from etf_registry import fetch_market_active_etf_list; "
          "print(fetch_market_active_etf_list())\"")
    sys.exit(0)