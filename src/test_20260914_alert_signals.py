"""
test_20260914_alert_signals.py
測試 alert_signals.py：3種每日訊號提醒（聰明錢集中度提升／融資券異常變化／籌碼矛盾出現解除）

執行方式：python3 test_20260914_alert_signals.py
"""
import sys
sys.path.insert(0, "/home/claude/etf_opt")

import pandas as pd
import alert_signals


# ============================================================
# 共用：記憶體內的假 gspread Spreadsheet / Worksheet
# （跟 test_20260911_etf_quarterly_scan.py 同一套慣例）
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


print("=== 測試1：detect_concentration_up() ===")

diff_df_empty = pd.DataFrame()
assert alert_signals.detect_concentration_up(diff_df_empty).empty, "空DataFrame應回傳空"
print("✅ 空DataFrame -> 空結果")

diff_df_no_col = pd.DataFrame({"股票代號": ["2330"], "股票名稱": ["台積電"]})
assert alert_signals.detect_concentration_up(diff_df_no_col).empty, "沒有主要狀態欄應回傳空"
print("✅ 沒有「主要狀態」欄 -> 空結果")

diff_df = pd.DataFrame({
    "股票代號": ["2330", "2454", "2603", "1101", "2317"],
    "股票名稱": ["台積電", "聯發科", "長榮", "台泥", "鴻海"],
    "主要狀態": ["🆕 新增", "🔺 加碼", "🔻 減碼", "🗑️ 清倉", "🔀 混合"],
})
result = alert_signals.detect_concentration_up(diff_df)
assert set(result["股票代號"]) == {"2330", "2454"}, f"應只選出新增/加碼，實際：{result['股票代號'].tolist()}"
print("✅ 只篩選出「🆕 新增」「🔺 加碼」")

print("\n=== 測試2：detect_margin_abnormal() ===")

multi_df_empty = pd.DataFrame()
assert alert_signals.detect_margin_abnormal(multi_df_empty).empty, "空DataFrame應回傳空"
print("✅ 空DataFrame -> 空結果")

multi_df_no_col = pd.DataFrame({"股票代號": ["2330"]})
assert alert_signals.detect_margin_abnormal(multi_df_no_col).empty, "沒有融資訊號欄應回傳空"
print("✅ 沒有「融資訊號」欄 -> 空結果")

multi_df = pd.DataFrame({
    "股票代號": ["2330", "2454", "2603", "1101", "2317"],
    "股票名稱": ["台積電", "聯發科", "長榮", "台泥", "鴻海"],
    "融資訊號": [
        "🔺 融資大增（散戶槓桿追價中）",
        "🔻 融資大減（散戶停損/獲利了結中）",
        "融資小增",
        "融資小減",
        "融資持平",
    ],
})
result = alert_signals.detect_margin_abnormal(multi_df)
assert set(result["股票代號"]) == {"2330", "2454"}, f"應只選出大增/大減，實際：{result['股票代號'].tolist()}"
print("✅ 只篩選出「大增」「大減」，排除「小增」「小減」「持平」")

print("\n=== 測試3：detect_chip_conflict_transitions() ===")

multi_df_c = pd.DataFrame({
    "股票代號": ["2330", "2454", "2603", "1101"],
    "股票名稱": ["台積電", "聯發科", "長榮", "台泥"],
    "籌碼矛盾": ["⚠️ 疑似誘多出貨", "", "💡 疑似獲利了結換手", ""],
})

# 3a. 沒有歷史資料 -> 空結果（冷啟動）
assert alert_signals.detect_chip_conflict_transitions(multi_df_c, pd.DataFrame()).empty
print("✅ 沒有歷史資料（冷啟動）-> 空結果")

# 3b. 歷史資料只有「今天」自己（尚未累積到前一天）-> today_date_str排除後應為空
history_only_today = pd.DataFrame({
    "日期": ["20260914", "20260914"],
    "股票代號": ["2330", "2454"],
    "股票名稱": ["台積電", "聯發科"],
    "籌碼矛盾": ["", ""],
})
result = alert_signals.detect_chip_conflict_transitions(
    multi_df_c, history_only_today, today_date_str="20260914"
)
assert result.empty, "排除今天之後沒有更早的歷史資料，應回傳空"
print("✅ 歷史資料只有今天（today_date_str排除後）-> 空結果")

# 3c. 正常情境：有前一天資料，比對出「出現」跟「解除」
history_df = pd.DataFrame({
    "日期": ["20260912", "20260912", "20260912", "20260913", "20260913", "20260913", "20260913"],
    "股票代號": ["2330", "2454", "2603", "2330", "2454", "2603", "1101"],
    "股票名稱": ["台積電", "聯發科", "長榮", "台積電", "聯發科", "長榮", "台泥"],
    "籌碼矛盾": ["", "", "", "", "💡 疑似法人低接", "💡 疑似獲利了結換手", "⚠️ 舊矛盾"],
})
# 20260913（前一天）: 2330無矛盾, 2454有矛盾, 2603有矛盾, 1101有矛盾
# 今天(multi_df_c): 2330出現矛盾(出現), 2454無矛盾(未變化,history沒有matching), 2603持續矛盾(不算變化), 1101沒在今天名單裡
result = alert_signals.detect_chip_conflict_transitions(
    multi_df_c, history_df, today_date_str="20260914"
)
codes_changed = dict(zip(result["股票代號"], result["變化"]))
assert codes_changed.get("2330") == "🆕 矛盾出現", f"2330應為矛盾出現，實際：{codes_changed}"
print(f"✅ 正確辨識出變化：{codes_changed}")

print("\n=== 測試4：append_chip_conflict_history() ===")

ss_fake = FakeSpreadsheet()
multi_df_hist = pd.DataFrame({
    "股票代號": ["2330", "2454"],
    "股票名稱": ["台積電", "聯發科"],
    "籌碼矛盾": ["⚠️ 疑似誘多出貨", ""],
    "融資訊號": ["🔺 融資大增（散戶槓桿追價中）", "融資持平"],
})

n1 = alert_signals.append_chip_conflict_history(ss_fake, multi_df_hist, "20260914")
assert n1 == 2, f"應新增2筆，實際：{n1}"
assert alert_signals.SHEET_CHIP_HISTORY in [w.title for w in ss_fake.worksheets()]
print(f"✅ 第一次寫入：新增 {n1} 筆，成功建立分頁「{alert_signals.SHEET_CHIP_HISTORY}」")

# 同一天重複寫入 -> 應該跳過（dedup by date）
n2 = alert_signals.append_chip_conflict_history(ss_fake, multi_df_hist, "20260914")
assert n2 == 0, f"同一天重複寫入應跳過，實際新增：{n2}"
print("✅ 同一天重複寫入 -> 正確跳過（dedup by date）")

# 缺少必要欄位 -> 應該直接回傳0，不寫入
multi_df_missing_col = pd.DataFrame({"股票代號": ["2330"], "股票名稱": ["台積電"]})
n3 = alert_signals.append_chip_conflict_history(ss_fake, multi_df_missing_col, "20260915")
assert n3 == 0, "缺少「籌碼矛盾」欄時應回傳0"
print("✅ 缺少必要欄位 -> 正確短路回傳0")

# 空DataFrame -> 應該直接回傳0
n4 = alert_signals.append_chip_conflict_history(ss_fake, pd.DataFrame(), "20260915")
assert n4 == 0, "空DataFrame應回傳0"
print("✅ 空DataFrame -> 正確短路回傳0")

print("\n=== 測試5：build_daily_alert_summary() 組合結果 ===")

summary = alert_signals.build_daily_alert_summary(multi_df, diff_df, pd.DataFrame(), today_date_str="20260914")
assert set(summary.keys()) == {"concentration_up", "margin_abnormal", "chip_conflict_change"}
assert isinstance(summary["concentration_up"], pd.DataFrame)
assert isinstance(summary["margin_abnormal"], pd.DataFrame)
assert isinstance(summary["chip_conflict_change"], pd.DataFrame)
print("✅ build_daily_alert_summary() 回傳正確的3個key，皆為DataFrame")

print("\n=== 測試6：format_alert_summary_for_ai() 文字格式化 ===")

# 6a. 全部都是空的 -> 應該回傳空字串
empty_summary = {
    "concentration_up": pd.DataFrame(),
    "margin_abnormal": pd.DataFrame(),
    "chip_conflict_change": pd.DataFrame(),
}
assert alert_signals.format_alert_summary_for_ai(empty_summary) == ""
print("✅ 三項訊號皆空 -> 回傳空字串")

# 6b. 有內容時應包含對應的標題與代號
full_summary = alert_signals.build_daily_alert_summary(multi_df, diff_df, pd.DataFrame(), today_date_str="20260914")
text = alert_signals.format_alert_summary_for_ai(full_summary)
assert "聰明錢集中度提升" in text
assert "融資券異常變化" in text
assert "2330" in text
print("✅ 有內容時正確產生包含標題與代號的文字摘要")
print("--- 摘要預覽 ---")
print(text)

print("\n🎉 全部測試通過！")
