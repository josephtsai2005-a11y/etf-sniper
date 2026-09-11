"""驗證2026-09-11新增：「ETF清單半自動管理系統」（季度市場掃描 + 自動加入追蹤 + 績效標註）。

涵蓋：
1. fetcher.py::get_tracked_etf_list() — 分頁不存在/空白/找不到欄位/正常讀取/讀取例外時
   的各種回退情境，確認任何失敗都安全退回內建ETF_LIST，不會讓daily job抓不到任何ETF。
2. fetcher.py::fetch_all_etfs(etf_codes=...) — 確認可以接受動態代號清單，且不傳入時
   維持原本行為（沿用ETF_LIST）。
3. etf_registry.py::fetch_market_active_etf_list() — 用構造的假HTML（比照isin.twse.com.tw
   已知的「代號+全形空白+名稱」儲存格排版）驗證解析邏輯，不依賴真實TWSE連線（sandbox
   網路權限本來就連不上，此檔案開頭已有說明）。
4. etf_registry.py::compute_etf_performance() / annotate_performance() — 用假造的「4個
   時間點全市場快照」（2026-09-11上線後第二次修正，取代逐檔查歷史序列）驗證報酬率計算
   （含查無資料時留None不留0%）、非交易日自動往前回溯找快照、與四分位標籤邏輯。
5. etf_registry.py::run_quarterly_etf_scan() — 用記憶體內的假Spreadsheet/Worksheet物件
   驗證整個流程：第一次執行（分頁不存在）用ETF_LIST起始、新代號直接加入追蹤、既有代號
   消失時只標記不刪除、績效標註正確合併進最終要寫入的表格。
6. main.py — 原始碼結構檢查，確認RUN_MODE=etf_scan分支存在且提早return、以及daily抓取
   路徑已經改用get_tracked_etf_list()動態清單而不是寫死的ETF_LIST。
"""
import re
import sys
import types
import pandas as pd

sys.path.insert(0, "/home/claude/etf_opt")


# ============================================================
# 共用：記憶體內的假 gspread Spreadsheet / Worksheet
# ============================================================
class FakeWorksheetNotFound(Exception):
    pass


class FakeWorksheet:
    def __init__(self, title):
        self.title = title
        self._rows = []

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def clear(self):
        self._rows = []

    def append_row(self, row):
        self._rows.append(list(row))

    def append_rows(self, rows, value_input_option=None):
        for r in rows:
            self._rows.append(list(r))


class FakeSpreadsheet:
    def __init__(self, initial_sheets=None):
        self._sheets = {}
        for name, rows in (initial_sheets or {}).items():
            ws = FakeWorksheet(name)
            ws._rows = [list(r) for r in rows]
            self._sheets[name] = ws

    def worksheet(self, name):
        if name not in self._sheets:
            raise FakeWorksheetNotFound(f"worksheet {name} not found")
        return self._sheets[name]

    def worksheets(self):
        return list(self._sheets.values())

    def add_worksheet(self, title, rows=100, cols=10):
        ws = FakeWorksheet(title)
        self._sheets[title] = ws
        return ws


print("=== 測試1：get_tracked_etf_list() 各種回退情境 ===")
from fetcher import get_tracked_etf_list, ETF_LIST, fetch_all_etfs

# 1a. 分頁完全不存在 -> 回退ETF_LIST
ss_empty = FakeSpreadsheet()
result = get_tracked_etf_list(ss_empty, retries=0)
assert result == list(ETF_LIST), "分頁不存在時應該回退ETF_LIST"
print("✅ 分頁不存在 -> 回退ETF_LIST")

# 1b. 分頁存在但資料不足3列 -> 回退ETF_LIST
ss_thin = FakeSpreadsheet({"ETF清單管理": [["ETF清單管理 標題列"]]})
result = get_tracked_etf_list(ss_thin, retries=0)
assert result == list(ETF_LIST), "資料不足3列時應該回退ETF_LIST"
print("✅ 資料不足3列 -> 回退ETF_LIST")

# 1c. 分頁存在但沒有「ETF代碼」欄 -> 回退ETF_LIST
ss_no_col = FakeSpreadsheet({"ETF清單管理": [
    ["標題"], ["代碼", "名稱", "狀態"], ["00403A", "統一台灣", "追蹤中"],
]})
result = get_tracked_etf_list(ss_no_col, retries=0)
assert result == list(ETF_LIST), "找不到「ETF代碼」欄時應該回退ETF_LIST"
print("✅ 找不到「ETF代碼」欄 -> 回退ETF_LIST")

# 1d. 正常讀取：只選「追蹤中」的代碼
ss_normal = FakeSpreadsheet({"ETF清單管理": [
    ["標題"],
    ["ETF代碼", "ETF名稱", "追蹤狀態"],
    ["00403A", "統一台灣", "追蹤中"],
    ["00981A", "主動統一台灣高息", "追蹤中"],
    ["00999Z", "已下市測試", "停用"],
]})
result = get_tracked_etf_list(ss_normal, retries=0)
assert result == ["00403A", "00981A"], f"應只回傳追蹤中的代碼，實際: {result}"
print("✅ 正常讀取只選「追蹤中」的代碼")

# 1e. 沒有「追蹤狀態」欄時，全部代碼都當作追蹤中
ss_no_status_col = FakeSpreadsheet({"ETF清單管理": [
    ["標題"], ["ETF代碼", "ETF名稱"], ["00403A", "統一台灣"], ["00981A", "主動統一"],
]})
result = get_tracked_etf_list(ss_no_status_col, retries=0)
assert result == ["00403A", "00981A"]
print("✅ 沒有「追蹤狀態」欄時，全部代碼視為追蹤中")

# 1f. worksheet()拋例外（模擬Sheets暫時連不上）-> 重試後回退ETF_LIST
class ExplodingSpreadsheet:
    def worksheet(self, name):
        raise RuntimeError("模擬連線失敗")

result = get_tracked_etf_list(ExplodingSpreadsheet(), retries=1)
assert result == list(ETF_LIST), "讀取例外時應該回退ETF_LIST"
print("✅ 讀取例外（模擬連線失敗）-> 回退ETF_LIST\n")

print("=== 測試2：fetch_all_etfs(etf_codes=...) 動態代號清單 ===")
import fetcher as fetcher_module

calls = []

def _fake_fetch_holdings(code, trade_date=None):
    calls.append(code)
    return pd.DataFrame([{"股票代號": "2330", "股票名稱": "台積電", "權重%": "10", "持股數": "1000",
                           "ETF代碼": code, "資料來源": "test", "抓取時間": trade_date}])

orig_fetch = fetcher_module.fetch_etfinfo_holdings
orig_sleep = fetcher_module.time.sleep
fetcher_module.fetch_etfinfo_holdings = _fake_fetch_holdings
fetcher_module.time.sleep = lambda *_a, **_k: None
try:
    df = fetch_all_etfs("20260911", etf_codes=["00403A", "00981A"])
    assert calls == ["00403A", "00981A"], f"應該只抓傳入的代號，實際呼叫: {calls}"
    assert len(df) == 2
    print("✅ 傳入etf_codes時只抓指定的清單")

    calls.clear()
    df2 = fetch_all_etfs("20260911")
    assert calls == list(ETF_LIST), "不傳etf_codes時應維持原本行為，沿用ETF_LIST"
    print("✅ 不傳etf_codes時維持原行為（沿用ETF_LIST），零回歸\n")
finally:
    fetcher_module.fetch_etfinfo_holdings = orig_fetch
    fetcher_module.time.sleep = orig_sleep


print("=== 測試3：fetch_market_active_etf_list() 解析假HTML（比照isin.twse.com.tw排版）===")
import etf_registry

FAKE_HTML = """
<html><body>
<table>
<tr><th>有價證券代號及名稱</th><th>國際代號</th></tr>
<tr><td>00403A　主動统一台灣高息动能</td><td>TW0000403A0</td></tr>
<tr><td>00981A　主動统一台灣高股息</td><td>TW0000981A0</td></tr>
<tr><td>00982D　主動统一台灣多元收益债券</td><td>TW0000982D0</td></tr>
<tr><td>2330　台積電</td><td>TW0002330009</td></tr>
<tr><td>0050　元大台灣50</td><td>TW0000050004</td></tr>
</table>
</body></html>
"""


class FakeResp:
    def __init__(self, text):
        self.text = text
        self.encoding = "utf-8"


def _fake_session_get(url, timeout=None):
    return FakeResp(FAKE_HTML)


orig_get = etf_registry.SESSION.get
etf_registry.SESSION.get = _fake_session_get
try:
    market_df = etf_registry.fetch_market_active_etf_list(retries=0)
    assert not market_df.empty, "應該解析出結果"
    codes = sorted(market_df["ETF代碼"].tolist())
    assert codes == ["00403A", "00981A", "00982D"], f"應只保留符合主動式ETF代號格式的項目，實際: {codes}"
    assert "2330" not in codes and "0050" not in codes, "一般個股/被動ETF不應該被誤判為主動式ETF"
    name_map = dict(zip(market_df["ETF代碼"], market_df["ETF名稱"]))
    assert name_map["00403A"] == "主動统一台灣高息动能"
    print(f"✅ 正確從假HTML解析出 {len(market_df)} 檔主動式ETF，且排除一般個股/被動ETF\n")
finally:
    etf_registry.SESSION.get = orig_get

print("=== 測試3b：fetch_market_active_etf_list() 連線失敗時回傳空DataFrame（不拋例外）===")

def _fake_session_get_fail(url, timeout=None):
    raise RuntimeError("模擬連線失敗")

etf_registry.SESSION.get = _fake_session_get_fail
orig_sleep2 = etf_registry.time.sleep
etf_registry.time.sleep = lambda *_a, **_k: None
try:
    market_df_fail = etf_registry.fetch_market_active_etf_list(retries=1)
    assert market_df_fail.empty, "連線失敗時應回傳空DataFrame，不應該拋例外"
    print("✅ 連線失敗時安全回傳空DataFrame\n")
finally:
    etf_registry.SESSION.get = orig_get
    etf_registry.time.sleep = orig_sleep2


print("=== 測試3c：fetch_market_active_etf_list() 頁面解析成功但0筆吻合時，不觸發重試 ===")
# 2026-09-11第一次正式上線實測發現：這種情況原本會被當成例外去重試，對同一個URL/同一套
# 邏輯重複解析一次完全不會有不同結果，只是白白多耗一次記憶體——實測時就是在這個retry上
# 把512Mi記憶體榨乾，container被OOM砍掉，執行狀態顯示failed。修正後這裡驗證：0筆吻合時
# 只會呼叫SESSION.get()一次（不重試），直接回傳空DataFrame。
FAKE_HTML_NO_MATCH = """
<html><body>
<table>
<tr><th>有價證券代號及名稱</th></tr>
<tr><td>2330　台積電</td></tr>
<tr><td>0050　元大台灣50</td></tr>
</table>
</body></html>
"""
get_call_count = {"n": 0}


def _fake_session_get_no_match(url, timeout=None):
    get_call_count["n"] += 1
    return FakeResp(FAKE_HTML_NO_MATCH)


etf_registry.SESSION.get = _fake_session_get_no_match
try:
    result_no_match = etf_registry.fetch_market_active_etf_list(retries=2)
    assert result_no_match.empty, "0筆吻合時應該回傳空DataFrame"
    assert get_call_count["n"] == 1, \
        f"0筆吻合（頁面解析成功但沒有任何吻合項目）不應該觸發重試，實際呼叫了SESSION.get() {get_call_count['n']} 次"
    print(f"✅ 頁面解析成功但0筆吻合時，只呼叫一次SESSION.get()（不重試），避免重複解析大頁面耗盡記憶體\n")
finally:
    etf_registry.SESSION.get = orig_get


print("=== 測試3d：fetch_market_active_etf_list() 掃描全部table，挑吻合筆數最多的那個 ===")
FAKE_HTML_MULTI_TABLE = """
<html><body>
<table><tr><td>版面配置用的table，不是證券清單</td></tr></table>
<table>
<tr><th>有價證券代號及名稱</th></tr>
<tr><td>00403A　主動统一台灣高息动能</td></tr>
<tr><td>00981A　主動统一台灣高股息</td></tr>
</table>
</body></html>
"""


def _fake_session_get_multi(url, timeout=None):
    return FakeResp(FAKE_HTML_MULTI_TABLE)


etf_registry.SESSION.get = _fake_session_get_multi
try:
    result_multi = etf_registry.fetch_market_active_etf_list(retries=0)
    assert sorted(result_multi["ETF代碼"].tolist()) == ["00403A", "00981A"], \
        f"應該要掃過全部table，挑出真正的證券清單table，實際: {result_multi}"
    print(f"✅ 頁面有多個table時，正確挑出吻合筆數最多（真正的證券清單）的那一個\n")
finally:
    etf_registry.SESSION.get = orig_get


print("=== 測試4：compute_etf_performance() 用4個時間點全市場快照計算報酬率 ===")
# 2026-09-11上線後第二次修正：原本逐檔查歷史序列的做法（連續失敗冷卻/保險絲那一套）
# 已經整個被「4個時間點全市場快照」取代（見etf_registry.py開頭「上線後修正2」的完整
# 說明），這裡改成直接mock底層的_fetch_all_market_closes()，驗證新的計算/回溯邏輯。
from datetime import datetime as _dt, timedelta as _td

_today = _dt.now()
_today_str = _today.strftime("%Y%m%d")
_m1_str = (_today - _td(days=30)).strftime("%Y%m%d")
_m3_str = (_today - _td(days=90)).strftime("%Y%m%d")
_jan1_str = _dt(_today.year, 1, 1).strftime("%Y%m%d")

orig_fetch_closes = etf_registry._fetch_all_market_closes

FAKE_SNAPSHOTS = {
    _today_str: {"00403A": 110.0, "00981A": 50.0},
    _m1_str:    {"00403A": 100.0, "00981A": 55.0},
    _m3_str:    {"00403A": 90.0,  "00981A": 60.0},
    _jan1_str:  {"00403A": 80.0,  "00981A": 65.0},
}


def _fake_fetch_closes(date_str, retries=1):
    return dict(FAKE_SNAPSHOTS.get(date_str, {}))


etf_registry._fetch_all_market_closes = _fake_fetch_closes
try:
    perf_df = etf_registry.compute_etf_performance(["00403A", "00981A"])
    row_a = perf_df[perf_df["ETF代碼"] == "00403A"].iloc[0]
    assert row_a["近1月報酬%"] == round((110 / 100 - 1) * 100, 2)
    assert row_a["近3月報酬%"] == round((110 / 90 - 1) * 100, 2)
    assert row_a["今年以來報酬%"] == round((110 / 80 - 1) * 100, 2)
    assert row_a["資料筆數"] == 4
    row_b = perf_df[perf_df["ETF代碼"] == "00981A"].iloc[0]
    assert row_b["近1月報酬%"] < 0, "00981A收盤價一路下跌，近1月報酬應為負值"
    print(f"✅ 4個時間點快照正確算出報酬率：00403A 近1月{row_a['近1月報酬%']}% "
          f"近3月{row_a['近3月報酬%']}% YTD{row_a['今年以來報酬%']}%")
finally:
    etf_registry._fetch_all_market_closes = orig_fetch_closes


print("=== 測試4b：compute_etf_performance() 某時間點查無該代號（如新上市ETF）時留None ===")
FAKE_SNAPSHOTS_NEW = {
    _today_str: {"00777A": 20.0},
    _m1_str:    {"00777A": 18.0},
    _m3_str:    {"00403A": 90.0},   # 有快照資料，但查不到00777A這個代號（那時還沒上市）
    _jan1_str:  {"00403A": 80.0},
}
etf_registry._fetch_all_market_closes = lambda d, retries=1: dict(FAKE_SNAPSHOTS_NEW.get(d, {}))
try:
    perf_new = etf_registry.compute_etf_performance(["00777A"])
    row = perf_new.iloc[0]
    assert row["近1月報酬%"] is not None, "近1月的兩個快照都查得到，應該算得出報酬率"
    assert row["近3月報酬%"] is None and row["今年以來報酬%"] is None, \
        "3個月前/年初的快照查不到這個代號（新上市），應該留None不是硬湊數字"
    assert row["資料筆數"] == 2
    print("✅ 新上市ETF在較早時間點查無資料時，對應報酬率正確留None，資料筆數只計有資料的時間點")
finally:
    etf_registry._fetch_all_market_closes = orig_fetch_closes


print("=== 測試4c：_find_market_closes_near() 非交易日自動往前回溯找最近的交易日快照 ===")
attempted = []


def _fake_fetch_with_weekend_gap(date_str, retries=1):
    attempted.append(date_str)
    if date_str == "20260911":  # 只有9/11(五)有資料，9/12(六)/9/13(日)是非交易日查無資料
        return {"00403A": 100.0}
    return {}


etf_registry._fetch_all_market_closes = _fake_fetch_with_weekend_gap
try:
    found_date, closes = etf_registry._find_market_closes_near(_dt(2026, 9, 12))
    assert found_date == "20260911", f"應該往前回溯找到9/11的快照，實際: {found_date}"
    assert attempted == ["20260912", "20260911"], \
        f"應該先試目標日，沒資料才往前一天試，實際嘗試順序: {attempted}"
    print(f"✅ 正確往前回溯找到最近一個有資料的交易日快照：{found_date}（嘗試順序: {attempted}）")
finally:
    etf_registry._fetch_all_market_closes = orig_fetch_closes


print("=== 測試4d：_find_market_closes_near() 回溯超過上限仍找不到資料時回傳(None, {}) ===")
etf_registry._fetch_all_market_closes = lambda d, retries=1: {}
try:
    found_date2, closes2 = etf_registry._find_market_closes_near(_dt(2026, 9, 12), max_lookback_days=3)
    assert found_date2 is None and closes2 == {}, "回溯超過上限仍找不到資料時應該回傳(None, {})"
    print("✅ 回溯超過上限仍找不到資料時，正確回傳(None, {})而不是無限回溯\n")
finally:
    etf_registry._fetch_all_market_closes = orig_fetch_closes


print("=== 測試5：annotate_performance() 四分位標籤邏輯 ===")
perf_sample = pd.DataFrame([
    {"ETF代碼": "A", "近3月報酬%": 20.0, "資料筆數": 60},
    {"ETF代碼": "B", "近3月報酬%": 15.0, "資料筆數": 60},
    {"ETF代碼": "C", "近3月報酬%": 5.0, "資料筆數": 60},
    {"ETF代碼": "D", "近3月報酬%": -10.0, "資料筆數": 60},
    {"ETF代碼": "E", "近3月報酬%": -20.0, "資料筆數": 60},
    {"ETF代碼": "F", "近3月報酬%": None, "資料筆數": 5},  # 資料不足
])
annotated = etf_registry.annotate_performance(perf_sample, rank_period="近3月報酬%")
notes = dict(zip(annotated["ETF代碼"], annotated["備註"]))
assert notes["F"] == "🆕 資料尚不足，暫無法比較"
assert notes["A"] == "🟢 表現領先", f"報酬率最高的應該是表現領先，實際: {notes['A']}"
assert notes["E"] == "🔴 表現落後", f"報酬率最低的應該是表現落後，實際: {notes['E']}"
assert notes["C"] == "⚡ 表現中等"
print(f"✅ 四分位標籤邏輯正確：{notes}\n")

print("=== 測試5b：annotate_performance() 樣本數<4檔時退回簡單正負判斷 ===")
perf_small = pd.DataFrame([
    {"ETF代碼": "A", "近3月報酬%": 5.0, "資料筆數": 60},
    {"ETF代碼": "B", "近3月報酬%": -5.0, "資料筆數": 60},
])
annotated_small = etf_registry.annotate_performance(perf_small)
notes_small = dict(zip(annotated_small["ETF代碼"], annotated_small["備註"]))
assert notes_small["A"] == "🟢 表現領先" and notes_small["B"] == "🔴 表現落後"
print(f"✅ 樣本數過少時退回簡單正負報酬判斷：{notes_small}\n")


print("=== 測試6：run_quarterly_etf_scan() 端對端流程（假Spreadsheet）===")
etf_registry.fetch_market_active_etf_list = lambda retries=2: pd.DataFrame([
    {"ETF代碼": "00403A", "ETF名稱": "統一台灣"},
    {"ETF代碼": "00981A", "ETF名稱": "主動統一台灣高息"},
    {"ETF代碼": "00777A", "ETF名稱": "全新主動式ETF"},  # 這檔是「新發現」的
    # 注意：00982D 沒有出現在這次掃描結果 -> 應該被標記提醒，但不能被移除
])
etf_registry.compute_etf_performance = lambda codes: pd.DataFrame([
    {"ETF代碼": c, "近1月報酬%": 1.0, "近3月報酬%": 3.0, "今年以來報酬%": 8.0, "資料筆數": 80}
    for c in codes
])
# annotate_performance 保留真實邏輯，不mock

ss_scan = FakeSpreadsheet({
    "ETF清單管理": [
        ["ETF清單管理　最後掃描：20260601"],
        ["ETF代碼", "ETF名稱", "追蹤狀態", "來源", "加入日期"],
        ["00403A", "統一台灣", "追蹤中", "內建清單", "20260601"],
        ["00981A", "主動統一台灣高息", "追蹤中", "內建清單", "20260601"],
        ["00982D", "主動統一多元收益債券", "追蹤中", "內建清單", "20260601"],
    ]
})

result_df = etf_registry.run_quarterly_etf_scan(ss_scan)

codes_after = set(result_df["ETF代碼"])
assert "00777A" in codes_after, "市場掃描發現的新代號應該直接加入追蹤"
new_row = result_df[result_df["ETF代碼"] == "00777A"].iloc[0]
assert new_row["來源"] == "季度掃描新增" and new_row["追蹤狀態"] == "追蹤中"
print("✅ 新發現的ETF直接加入追蹤（來源標記「季度掃描新增」）")

missing_row = result_df[result_df["ETF代碼"] == "00982D"].iloc[0]
assert missing_row["追蹤狀態"] == "追蹤中", "掃描不到的既有ETF不應該被自動移除追蹤"
assert "請人工確認" in missing_row["備註"], "掃描不到的既有ETF應該在備註標記提醒"
print("✅ 既有ETF本次掃描不到時，不自動移除，只標記提醒人工確認")

kept_row = result_df[result_df["ETF代碼"] == "00403A"].iloc[0]
assert kept_row["近3月報酬%"] == 3.0, "追蹤中的ETF應該有計算出來的績效數字"
assert kept_row["備註"] != "", "追蹤中且有績效資料的ETF備註不應為空（應有績效標籤或至少不是空字串異常）"
print(f"✅ 既有追蹤ETF正確合併績效標註：00403A 備註 = 「{kept_row['備註']}」")

# 確認實際寫入了假Sheets（第三列起應該有資料，且欄位跟REGISTRY_COLUMNS一致）
written_ws = ss_scan.worksheet("ETF清單管理")
written_vals = written_ws.get_all_values()
assert len(written_vals) >= 3, "應該有寫入資料列"
assert written_vals[1] == etf_registry.REGISTRY_COLUMNS, "寫入的欄位順序應該跟REGISTRY_COLUMNS一致"
print(f"✅ 已正確寫入「ETF清單管理」分頁，共 {len(written_vals) - 2} 筆資料\n")


print("=== 測試6b：run_quarterly_etf_scan() 第一次執行（分頁不存在）用ETF_LIST起始 ===")
etf_registry.fetch_market_active_etf_list = lambda retries=2: pd.DataFrame()  # 模擬掃描失敗
ss_fresh = FakeSpreadsheet()  # 完全空的，沒有任何分頁
result_fresh = etf_registry.run_quarterly_etf_scan(ss_fresh)
assert set(result_fresh["ETF代碼"]) == set(ETF_LIST), "第一次執行應該用內建ETF_LIST當起始追蹤清單"
assert (result_fresh["來源"] == "內建清單").all()
print(f"✅ 第一次執行（分頁不存在）正確用內建ETF_LIST（{len(ETF_LIST)}檔）起始，且掃描失敗不影響既有清單\n")


print("=== 測試7：main.py 結構檢查 — RUN_MODE=etf_scan分支 + 動態ETF清單抓取 ===")
main_src = open("/home/claude/etf_opt/main.py", encoding="utf-8").read()

assert 'RUN_MODE == "etf_scan"' in main_src, "main.py應該要有RUN_MODE=etf_scan的判斷分支"
etf_scan_block_match = re.search(
    r'if RUN_MODE == "etf_scan":(.*?)\n    # ── 階段一', main_src, re.S
)
assert etf_scan_block_match, "找不到RUN_MODE=etf_scan完整區塊（應該在階段一之前提早return）"
etf_scan_block = etf_scan_block_match.group(1)
assert "run_quarterly_etf_scan" in etf_scan_block, "etf_scan分支應該呼叫run_quarterly_etf_scan()"
assert "return" in etf_scan_block, "etf_scan分支應該提早return，不繼續往下跑抓持股流程"
print("✅ main.py有獨立的RUN_MODE=etf_scan分支，呼叫run_quarterly_etf_scan()後提早return")

assert "get_tracked_etf_list" in main_src, "main.py應該要呼叫get_tracked_etf_list()動態決定清單"
assert "fetch_all_etfs(TRADE_DATE, etf_codes=tracked_etf_codes)" in main_src, \
    "daily抓取流程應該把動態清單傳給fetch_all_etfs()，而不是繼續只抓寫死的ETF_LIST"
assert "_client0" not in main_src and "_ss0" not in main_src, \
    "舊的_client0/_ss0變數應該已經被統一改成_list_client/_list_ss"
print("✅ daily抓取流程已改用get_tracked_etf_list()動態清單，並正確傳入fetch_all_etfs()\n")

print("全部測試通過 🎉")
