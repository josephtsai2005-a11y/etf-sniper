"""
backtest_tracker.py
回測績效追蹤：驗證「綜合評分/狙擊名單」與「法人訊號強度」的預測準確率

設計原則：
  - 不追蹤「固定一籃子股票」，而是把每一天每一檔股票的評分紀錄，
    都當成一筆獨立的「事件」：記錄當天分數 + 當天收盤價
  - 之後用「同一檔股票、N個交易日後的紀錄」回頭查詢未來股價，計算報酬率
  - 不需要額外抓歷史股價 API：直接沿用本系統每天已經記錄的收盤價資料
  - 因為每天上榜的股票組成本來就會變動，這是正常現象，不影響回測有效性
    （股票會消失通常代表當天不再被3+檔ETF持有，屬於資料涵蓋範圍的自然限制）
  - 除了固定天數的報酬率(T+N)，也記錄「T+20內出現過的最大報酬%」，
    避免漏掉「進場後盤整一段時間才噴出」的波段行情
  - 額外記錄「法人換手強度%」「買超轉換率%」，用來驗證法人交易量/一致性
    跟未來報酬是否真的正相關（三大合計張數本身不等於成交量或漲幅，
    需要用這兩個指標實際檢驗）
  - 同步記錄大盤基準（0050）收盤價，計算「相對大盤超額報酬%」——
    在大盤系統性上漲/下跌時，絕對報酬率會被大盤方向淹沒，
    超額報酬才能看出評分系統是否真的有選股能力（尤其驗證反彈期的相對強弱）
"""
import logging
import pandas as pd
from datetime import datetime
import pytz

from ai_analyzer import call_claude

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_BACKTEST = "回測記錄"
HORIZONS = [1, 3, 5, 10, 20]  # 追蹤 T+1/T+3/T+5/T+10/T+20 個「交易日」後的報酬率
MAX_WINDOW = 20  # 「區間內最大報酬%」的觀察窗口天數
BENCHMARK_COL = "大盤0050收盤價"

# ── AI分析報告的資料充足性門檻（避免對雜訊下結論）──────────────────
MIN_SAMPLES_PER_BUCKET = 100  # 每個評分區間至少要有這麼多筆樣本，統計上才有基本意義
MIN_TRADING_DAYS = 20         # 至少要走滿一次完整的T20觀察窗口，才代表有一批「最終結果」可用


def _load_backtest_sheet(ss) -> pd.DataFrame:
    """讀取回測記錄分頁，不存在則回傳空表（含正確欄位結構）"""
    base_cols = ["記錄日期", "股票代號", "股票名稱", "進場收盤價", "綜合評分", "法人訊號",
                 "持有ETF數", "成交量", "法人換手強度%", "買超轉換率%",
                 "KD訊號", "MACD訊號", "背離警示", "技術面共振", "ATR%", BENCHMARK_COL]
    return_cols = [f"T{n}報酬率%" for n in HORIZONS]
    excess_cols = [f"T{n}超額報酬%" for n in HORIZONS]
    extra_cols = [f"T{MAX_WINDOW}內最大報酬%", f"T{MAX_WINDOW}內最大報酬發生日"]
    all_cols = base_cols + return_cols + excess_cols + extra_cols

    try:
        ws = ss.worksheet(SHEET_BACKTEST)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame(columns=all_cols)
        df = pd.DataFrame(vals[1:], columns=vals[0])
        for c in all_cols:
            if c not in df.columns:
                df[c] = ""
        return df
    except Exception:
        return pd.DataFrame(columns=all_cols)


def _write_backtest_sheet(ss, df: pd.DataFrame):
    """整表覆寫回Sheets"""
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_BACKTEST not in existing:
        ws = ss.add_worksheet(title=SHEET_BACKTEST, rows=20000, cols=25)
    else:
        ws = ss.worksheet(SHEET_BACKTEST)
    ws.clear()
    ws.append_row(df.columns.tolist())
    if not df.empty:
        rows = df.fillna("").values.tolist()
        chunk = 5000
        for i in range(0, len(rows), chunk):
            ws.append_rows(rows[i:i + chunk], value_input_option="USER_ENTERED")


def record_daily_snapshot(ss, smart_df: pd.DataFrame, trade_date: str, benchmark_price: float = None):
    """
    每日記錄快照：把今天有評分/收盤價的股票各存一筆獨立紀錄
    建議在 inst 模式（16:45）、cross_df（多方驗證名單）已經算好各項法人指標之後呼叫
    benchmark_price: 當天大盤基準（0050）收盤價，由main.py抓取後傳入
                     （若為None，超額報酬欄位會留空，之後也無法回填）
    """
    if smart_df.empty or "收盤價" not in smart_df.columns:
        log.warning("回測記錄：資料缺少收盤價欄位，跳過本次記錄")
        return

    df = _load_backtest_sheet(ss)

    if not df.empty and "記錄日期" in df.columns:
        if trade_date in df["記錄日期"].unique().tolist():
            log.info(f"回測記錄：{trade_date} 已記錄過，跳過重複寫入")
            return

    valid = smart_df[smart_df["收盤價"].notna()].copy()
    new_rows = []
    for _, row in valid.iterrows():
        new_rows.append({
            "記錄日期": trade_date,
            "股票代號": str(row.get("股票代號", "")),
            "股票名稱": row.get("股票名稱", ""),
            "進場收盤價": row.get("收盤價", ""),
            "綜合評分": row.get("綜合評分", row.get("sniper_score", "")),
            "法人訊號": row.get("訊號", row.get("法人訊號", "")),
            "持有ETF數": row.get("持有ETF數", ""),
            "成交量": row.get("成交量", ""),
            "法人換手強度%": row.get("法人換手強度%", ""),
            "買超轉換率%": row.get("買超轉換率%", ""),
            "KD訊號": row.get("KD訊號", ""),
            "MACD訊號": row.get("MACD訊號", ""),
            "背離警示": row.get("背離警示", ""),
            "技術面共振": row.get("技術面共振", ""),
            "ATR%": row.get("ATR%", ""),
            BENCHMARK_COL: benchmark_price if benchmark_price else "",
            **{f"T{n}報酬率%": "" for n in HORIZONS},
            **{f"T{n}超額報酬%": "" for n in HORIZONS},
            f"T{MAX_WINDOW}內最大報酬%": "",
            f"T{MAX_WINDOW}內最大報酬發生日": "",
        })

    if not new_rows:
        log.info("回測記錄：本日無有效資料可記錄")
        return

    combined = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True) if not df.empty else pd.DataFrame(new_rows)
    _write_backtest_sheet(ss, combined)
    log.info(f"回測記錄：{trade_date} 新增 {len(new_rows)} 筆快照" + (f"（大盤0050={benchmark_price}）" if benchmark_price else "（未取得大盤基準價）"))


def backfill_returns(ss):
    """
    回填報酬率：掃描所有還沒填報酬率的舊紀錄，用「同股票、N個交易日後」的紀錄回填
    同時計算「T+20內最大報酬%」與「相對大盤超額報酬%」
    建議每天執行一次（inst模式尾聲），會自動處理所有累積未完成的回填
    """
    df = _load_backtest_sheet(ss)
    if df.empty:
        return

    df["進場收盤價"] = pd.to_numeric(df["進場收盤價"], errors="coerce")
    df[BENCHMARK_COL] = pd.to_numeric(df[BENCHMARK_COL], errors="coerce")

    trading_days = sorted(df["記錄日期"].unique().tolist())
    day_index = {d: i for i, d in enumerate(trading_days)}

    price_lookup = {}       # (股票代號, 記錄日期) -> 進場收盤價
    benchmark_lookup = {}   # 記錄日期 -> 大盤0050收盤價（同一天所有列共用同一個值，取第一筆非空）
    for _, row in df.iterrows():
        price_lookup[(row["股票代號"], row["記錄日期"])] = row["進場收盤價"]
        if row["記錄日期"] not in benchmark_lookup and pd.notna(row[BENCHMARK_COL]):
            benchmark_lookup[row["記錄日期"]] = row[BENCHMARK_COL]

    updated_count = 0
    excess_updated_count = 0
    max_updated_count = 0

    for idx, row in df.iterrows():
        code = row["股票代號"]
        rec_date = row["記錄日期"]
        entry_price = row["進場收盤價"]
        if pd.isna(entry_price) or rec_date not in day_index:
            continue

        rec_idx = day_index[rec_date]
        entry_benchmark = benchmark_lookup.get(rec_date)

        # ── 固定天數 T+N 報酬率 + 相對大盤超額報酬% ──────────────
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            excess_col = f"T{n}超額報酬%"
            already_has_return = row.get(col, "") not in ["", None] and not pd.isna(row.get(col, ""))

            target_idx = rec_idx + n
            if target_idx >= len(trading_days):
                continue

            target_date = trading_days[target_idx]

            if not already_has_return:
                found_price = None
                for lookahead in range(0, 4):
                    probe_idx = target_idx + lookahead
                    if probe_idx >= len(trading_days):
                        break
                    probe_date = trading_days[probe_idx]
                    if (code, probe_date) in price_lookup:
                        p = price_lookup[(code, probe_date)]
                        if pd.notna(p):
                            found_price = p
                            break

                if found_price is not None and entry_price:
                    ret_pct = round((found_price - entry_price) / entry_price * 100, 2)
                    df.at[idx, col] = ret_pct
                    updated_count += 1

            # 超額報酬：即使個股報酬率已經算過，只要超額報酬還沒算，且大盤基準資料齊全就補算
            already_has_excess = row.get(excess_col, "") not in ["", None] and not pd.isna(row.get(excess_col, ""))
            if not already_has_excess and entry_benchmark:
                target_benchmark = benchmark_lookup.get(target_date)
                current_ret_val = df.at[idx, col] if col in df.columns else None
                if target_benchmark and pd.notna(current_ret_val) and current_ret_val != "":
                    benchmark_ret_pct = (target_benchmark - entry_benchmark) / entry_benchmark * 100
                    excess = round(float(current_ret_val) - benchmark_ret_pct, 2)
                    df.at[idx, excess_col] = excess
                    excess_updated_count += 1

        # ── T+20內最大報酬% （掃描整個區間找最高點，不是只看第20天）──
        max_col = f"T{MAX_WINDOW}內最大報酬%"
        date_col = f"T{MAX_WINDOW}內最大報酬發生日"
        already_has_max = row.get(max_col, "") not in ["", None] and not pd.isna(row.get(max_col, ""))
        window_end_idx = rec_idx + MAX_WINDOW

        if not already_has_max and entry_price:
            best_ret = None
            best_date = None
            scan_end = min(window_end_idx, len(trading_days) - 1)
            for probe_idx in range(rec_idx + 1, scan_end + 1):
                probe_date = trading_days[probe_idx]
                if (code, probe_date) in price_lookup:
                    p = price_lookup[(code, probe_date)]
                    if pd.notna(p):
                        ret = (p - entry_price) / entry_price * 100
                        if best_ret is None or ret > best_ret:
                            best_ret = ret
                            best_date = probe_date

            if best_ret is not None:
                df.at[idx, max_col] = round(best_ret, 2)
                df.at[idx, date_col] = best_date
                max_updated_count += 1

    if updated_count > 0 or max_updated_count > 0 or excess_updated_count > 0:
        _write_backtest_sheet(ss, df)
        log.info(f"回測回填完成：T+N報酬率 {updated_count} 筆，超額報酬 {excess_updated_count} 筆，"
                  f"T{MAX_WINDOW}內最大報酬 {max_updated_count} 筆")
    else:
        log.info("回測回填：本次無新資料可回填")


def get_etf_trend_group_summary(ss, lookback_days: int = 10, level_filter: str = None) -> pd.DataFrame:
    """
    依「ETF持有數的變化趨勢」分組（不是只看當下水位），解決一個重要盲點：
    「持有ETF數低」可能是①正在被市場慢慢發現、往上爬的早期階段，
    也可能是②原本很多ETF持有、後來慢慢被減碼／清倉，正在往下掉的衰退階段——
    這兩種是完全相反的情境，只看「當下有幾檔」看不出來，必須看「趨勢方向」才能分辨

    做法：往回查同一檔股票 lookback_days 個交易日前的「持有ETF數」，跟現在比較：
      - 上升趨勢：現在比過去多（正在被更多ETF發現/加碼）
      - 下降趨勢：現在比過去少（正在被ETF減碼/清倉）
      - 持平：差異在1檔以內

    level_filter: 可選，只看特定水位分組（例如只看"≤3檔"的股票，比較同樣是≤3檔，
                  上升趨勢跟下降趨勢的未來報酬有沒有差異——這是驗證「早期機會 vs 正在流失」的關鍵比較）
                  可選值："≤3檔"、"4-8檔"、"≥9檔"、None（不篩選水位，全部一起看趨勢）
    """
    df = _load_backtest_sheet(ss)
    if df.empty:
        return pd.DataFrame()

    df["持有ETF數"] = pd.to_numeric(df["持有ETF數"], errors="coerce")

    trading_days = sorted(df["記錄日期"].dropna().unique().tolist())
    day_index = {d: i for i, d in enumerate(trading_days)}

    etf_lookup = {}
    for _, r in df.iterrows():
        if pd.notna(r["持有ETF數"]):
            etf_lookup[(r["股票代號"], r["記錄日期"])] = r["持有ETF數"]

    def _level_group(n):
        if pd.isna(n):
            return None
        if n <= 3:
            return "≤3檔"
        elif n <= 8:
            return "4-8檔"
        else:
            return "≥9檔"

    trends = []
    for idx, row in df.iterrows():
        code = row["股票代號"]
        rec_date = row["記錄日期"]
        current_val = row["持有ETF數"]

        if pd.isna(current_val) or rec_date not in day_index:
            trends.append(None)
            continue

        rec_idx = day_index[rec_date]
        past_idx = rec_idx - lookback_days
        if past_idx < 0:
            trends.append(None)  # 資料還沒累積到足夠天數往回比較
            continue

        # 找最近的過去交易日資料（該股當天不一定有紀錄，往前後3天找最近的）
        past_val = None
        for offset in range(0, 4):
            probe_idx = past_idx - offset
            if probe_idx < 0:
                break
            probe_date = trading_days[probe_idx]
            if (code, probe_date) in etf_lookup:
                past_val = etf_lookup[(code, probe_date)]
                break

        if past_val is None:
            trends.append(None)
            continue

        delta = current_val - past_val
        if delta >= 1:
            trends.append("📈 上升趨勢")
        elif delta <= -1:
            trends.append("📉 下降趨勢")
        else:
            trends.append("➡️ 持平")

    df["ETF趨勢"] = trends
    df["ETF水位分組"] = df["持有ETF數"].apply(_level_group)

    if level_filter:
        df = df[df["ETF水位分組"] == level_filter]

    records = []
    for trend_label in ["📈 上升趨勢", "➡️ 持平", "📉 下降趨勢"]:
        sub = df[df["ETF趨勢"] == trend_label]
        if len(sub) < 5:
            continue
        row = {"ETF趨勢": trend_label, "樣本數": len(sub)}
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            vals = pd.to_numeric(sub[col], errors="coerce").dropna()
            if len(vals) > 0:
                row[f"T{n}平均報酬%"] = round(vals.mean(), 2)
                row[f"T{n}勝率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
            else:
                row[f"T{n}平均報酬%"] = None
                row[f"T{n}勝率%"] = None
        records.append(row)

    return pd.DataFrame(records)


def get_etf_holding_group_summary(ss, min_score: float = None) -> pd.DataFrame:
    """
    依「持有ETF數」分成三組，統計各組未來報酬率——驗證「共識形成中 vs 共識已飽和」的假設：
      - ≤3檔：可能還沒被多數基金經理人認可，若之後陸續被更多ETF加碼，可能是早期機會
      - 4-8檔：共識正在形成中
      - ≥9檔：高度共識，但也可能股價已經被推升、反映了大部分利多，剩餘空間較小

    min_score: 若指定，只統計「綜合評分>=min_score」的樣本（例如只看7分以上的股票，
               排除掉低分股的干擾，更精確回答「同樣是高分股，ETF持有數不同，未來報酬有沒有差異」）
    """
    df = _load_backtest_sheet(ss)
    if df.empty:
        return pd.DataFrame()

    df["持有ETF數"] = pd.to_numeric(df["持有ETF數"], errors="coerce")
    df["綜合評分"] = pd.to_numeric(df["綜合評分"], errors="coerce")

    if min_score is not None:
        df = df[df["綜合評分"] >= min_score]
        if df.empty:
            return pd.DataFrame()

    def etf_group(n):
        if pd.isna(n):
            return None
        if n <= 3:
            return "≤3檔（早期未獲共識）"
        elif n <= 8:
            return "4-8檔（共識形成中）"
        else:
            return "≥9檔（高度共識）"

    df["ETF共識分組"] = df["持有ETF數"].apply(etf_group)

    group_order = ["≤3檔（早期未獲共識）", "4-8檔（共識形成中）", "≥9檔（高度共識）"]
    records = []
    for grp in group_order:
        sub = df[df["ETF共識分組"] == grp]
        if len(sub) < 5:
            continue
        row = {"ETF共識分組": grp, "樣本數": len(sub)}
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            vals = pd.to_numeric(sub[col], errors="coerce").dropna()
            if len(vals) > 0:
                row[f"T{n}平均報酬%"] = round(vals.mean(), 2)
                row[f"T{n}勝率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
            else:
                row[f"T{n}平均報酬%"] = None
                row[f"T{n}勝率%"] = None

        max_col = f"T{MAX_WINDOW}內最大報酬%"
        max_vals = pd.to_numeric(sub[max_col], errors="coerce").dropna()
        if len(max_vals) > 0:
            row[f"T{MAX_WINDOW}內平均最大報酬%"] = round(max_vals.mean(), 2)
        else:
            row[f"T{MAX_WINDOW}內平均最大報酬%"] = None

        records.append(row)

    return pd.DataFrame(records)


def get_technical_signal_summary(ss, signal_col: str = "技術面共振") -> pd.DataFrame:
    """
    依技術面訊號分組統計未來報酬——用來驗證KD/MACD/技術面共振這些「提早偵測」訊號是否真的有效
    signal_col: 要分析哪個技術欄位，可選 "技術面共振"、"KD訊號"、"MACD訊號"
    """
    df = _load_backtest_sheet(ss)
    if df.empty or signal_col not in df.columns:
        return pd.DataFrame()

    records = []
    for signal in df[signal_col].dropna().unique().tolist():
        signal = str(signal).strip()
        if not signal:
            continue
        sub = df[df[signal_col] == signal]
        if len(sub) < 5:
            continue
        row = {signal_col: signal, "樣本數": len(sub)}
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            vals = pd.to_numeric(sub[col], errors="coerce").dropna()
            if len(vals) > 0:
                row[f"T{n}平均報酬%"] = round(vals.mean(), 2)
                row[f"T{n}勝率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
            else:
                row[f"T{n}平均報酬%"] = None
                row[f"T{n}勝率%"] = None
        records.append(row)

    result = pd.DataFrame(records)
    if not result.empty and "T5平均報酬%" in result.columns:
        result = result.sort_values("T5平均報酬%", ascending=False).reset_index(drop=True)
    return result


def score_bucket(s):
    """評分區間分類（模組層級函式，供 get_backtest_summary 與 Streamlit 頁面明細鑽取共用）"""
    if pd.isna(s):
        return "無評分"
    if s >= 8:
        return "8分以上"
    elif s >= 6:
        return "6-8分"
    elif s >= 4:
        return "4-6分"
    else:
        return "4分以下"


def get_backtest_summary(ss) -> pd.DataFrame:
    """依「綜合評分區間」分組，統計各期間平均報酬率、勝率、超額報酬、以及T20內最大報酬%"""
    df = _load_backtest_sheet(ss)
    if df.empty:
        return pd.DataFrame()

    df["綜合評分"] = pd.to_numeric(df["綜合評分"], errors="coerce")
    df["評分區間"] = df["綜合評分"].apply(score_bucket)

    records = []
    for bucket in ["8分以上", "6-8分", "4-6分", "4分以下"]:
        sub = df[df["評分區間"] == bucket]
        if sub.empty:
            continue
        row = {"評分區間": bucket, "樣本數": len(sub)}
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            excess_col = f"T{n}超額報酬%"
            vals = pd.to_numeric(sub[col], errors="coerce").dropna()
            excess_vals = pd.to_numeric(sub[excess_col], errors="coerce").dropna()
            if len(vals) > 0:
                row[f"T{n}平均報酬%"] = round(vals.mean(), 2)
                row[f"T{n}勝率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
            else:
                row[f"T{n}平均報酬%"] = None
                row[f"T{n}勝率%"] = None
            if len(excess_vals) > 0:
                row[f"T{n}超額報酬%"] = round(excess_vals.mean(), 2)
                row[f"T{n}跑贏大盤率%"] = round((excess_vals > 0).sum() / len(excess_vals) * 100, 1)
            else:
                row[f"T{n}超額報酬%"] = None
                row[f"T{n}跑贏大盤率%"] = None

        max_col = f"T{MAX_WINDOW}內最大報酬%"
        max_vals = pd.to_numeric(sub[max_col], errors="coerce").dropna()
        if len(max_vals) > 0:
            row[f"T{MAX_WINDOW}內平均最大報酬%"] = round(max_vals.mean(), 2)
            row[f"出現50%+機會比例%"] = round((max_vals >= 50).sum() / len(max_vals) * 100, 1)
        else:
            row[f"T{MAX_WINDOW}內平均最大報酬%"] = None
            row[f"出現50%+機會比例%"] = None

        records.append(row)

    return pd.DataFrame(records)


def get_signal_summary(ss) -> pd.DataFrame:
    """依「法人訊號」分組統計績效（例如三大齊買 vs 外資主導 vs 雙向買超哪種未來報酬最好）"""
    df = _load_backtest_sheet(ss)
    if df.empty or "法人訊號" not in df.columns:
        return pd.DataFrame()

    records = []
    for signal in df["法人訊號"].dropna().unique().tolist():
        if not signal:
            continue
        sub = df[df["法人訊號"] == signal]
        if len(sub) < 5:
            continue
        row = {"法人訊號": signal, "樣本數": len(sub)}
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            vals = pd.to_numeric(sub[col], errors="coerce").dropna()
            if len(vals) > 0:
                row[f"T{n}平均報酬%"] = round(vals.mean(), 2)
                row[f"T{n}勝率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
            else:
                row[f"T{n}平均報酬%"] = None
                row[f"T{n}勝率%"] = None
        records.append(row)

    result = pd.DataFrame(records)
    if not result.empty and "T5平均報酬%" in result.columns:
        result = result.sort_values("T5平均報酬%", ascending=False).reset_index(drop=True)
    return result


def get_institutional_intensity_summary(ss) -> dict:
    """
    驗證「法人交易量/一致性」是否真的跟未來報酬正相關（回應：三大合計張數本身不等於成交量或漲幅）
    分別依「法人換手強度%」（法人交易量佔當日總成交量比例）與
    「買超轉換率%」（淨買超佔法人總交易量比例，越高代表方向越一致）分組
    回傳 {"換手強度": df, "買超轉換率": df}
    """
    df = _load_backtest_sheet(ss)
    if df.empty:
        return {}

    results = {}

    for metric_col, label, buckets in [
        ("法人換手強度%", "換手強度", [(0, 10, "10%以下"), (10, 30, "10-30%"), (30, 60, "30-60%"), (60, 999, "60%以上")]),
        ("買超轉換率%", "買超轉換率", [(0, 30, "0-30%(分歧)"), (30, 60, "30-60%"), (60, 85, "60-85%"), (85, 999, "85%以上(高度一致)")]),
    ]:
        if metric_col not in df.columns:
            continue
        df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce")

        records = []
        for lo, hi, name in buckets:
            sub = df[(df[metric_col] >= lo) & (df[metric_col] < hi)]
            if len(sub) < 5:
                continue
            row = {label + "區間": name, "樣本數": len(sub)}
            for n in [5, 10, 20]:
                col = f"T{n}報酬率%"
                vals = pd.to_numeric(sub[col], errors="coerce").dropna()
                if len(vals) > 0:
                    row[f"T{n}平均報酬%"] = round(vals.mean(), 2)
                    row[f"T{n}勝率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
                else:
                    row[f"T{n}平均報酬%"] = None
                    row[f"T{n}勝率%"] = None
            records.append(row)

        if records:
            results[label] = pd.DataFrame(records)

    return results


def get_relative_strength_by_period(ss, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    驗證「反彈強度與評分關聯」專用：指定一段期間（例如大盤回檔/反彈區間），
    依評分區間統計「相對大盤超額報酬%」，用來檢驗評分高的股票在這段期間
    是否真的比大盤抗跌／反彈更強

    start_date/end_date: "YYYY-MM-DD" 格式（對應「記錄日期」），皆為None則使用全部資料
    """
    df = _load_backtest_sheet(ss)
    if df.empty:
        return pd.DataFrame()

    if start_date:
        df = df[df["記錄日期"] >= start_date]
    if end_date:
        df = df[df["記錄日期"] <= end_date]

    if df.empty:
        return pd.DataFrame()

    df["綜合評分"] = pd.to_numeric(df["綜合評分"], errors="coerce")
    df["評分區間"] = df["綜合評分"].apply(score_bucket)

    records = []
    for bucket in ["8分以上", "6-8分", "4-6分", "4分以下"]:
        sub = df[df["評分區間"] == bucket]
        if sub.empty:
            continue
        row = {"評分區間": bucket, "樣本數": len(sub)}
        for n in HORIZONS:
            excess_col = f"T{n}超額報酬%"
            vals = pd.to_numeric(sub[excess_col], errors="coerce").dropna()
            if len(vals) > 0:
                row[f"T{n}超額報酬%"] = round(vals.mean(), 2)
                row[f"T{n}跑贏大盤率%"] = round((vals > 0).sum() / len(vals) * 100, 1)
            else:
                row[f"T{n}超額報酬%"] = None
                row[f"T{n}跑贏大盤率%"] = None
        records.append(row)

    return pd.DataFrame(records)


def check_data_sufficiency(ss) -> dict:
    """
    檢查回測資料是否已經累積到足以進行AI分析的門檻
    設計原則：寧可保守不分析，也不要對雜訊下結論——樣本不足時，
    任何「看起來合理」的AI敘事都可能只是在幫巧合編故事（敘事謬誤）

    回傳：
        {
            "sufficient": bool,           # 是否達標，可以進行AI分析
            "total_records": int,         # 累積總快照筆數
            "trading_days": int,          # 累積交易日數
            "bucket_counts": dict,        # 各評分區間目前樣本數
            "reasons": list[str],         # 尚未達標的具體原因（sufficient=True時為空list）
        }
    """
    df = _load_backtest_sheet(ss)
    result = {
        "sufficient": False,
        "total_records": 0,
        "trading_days": 0,
        "bucket_counts": {},
        "reasons": [],
    }
    if df.empty:
        result["reasons"].append("尚無任何回測記錄")
        return result

    result["total_records"] = len(df)
    trading_days = df["記錄日期"].nunique()
    result["trading_days"] = trading_days

    df["綜合評分"] = pd.to_numeric(df["綜合評分"], errors="coerce")
    df["評分區間"] = df["綜合評分"].apply(score_bucket)
    bucket_counts = df["評分區間"].value_counts().to_dict()
    result["bucket_counts"] = {b: int(bucket_counts.get(b, 0)) for b in ["8分以上", "6-8分", "4-6分", "4分以下"]}

    if trading_days < MIN_TRADING_DAYS:
        result["reasons"].append(
            f"交易日數不足：目前累積 {trading_days} 個交易日，需要至少 {MIN_TRADING_DAYS} 天，"
            f"才會有第一批完整的T20（20交易日後）最終結果"
        )

    insufficient_buckets = [
        b for b in ["8分以上", "6-8分", "4-6分", "4分以下"]
        if result["bucket_counts"].get(b, 0) < MIN_SAMPLES_PER_BUCKET
    ]
    if insufficient_buckets:
        detail = "、".join(f"{b}（{result['bucket_counts'].get(b, 0)}筆）" for b in insufficient_buckets)
        result["reasons"].append(
            f"以下評分區間樣本數尚未達到 {MIN_SAMPLES_PER_BUCKET} 筆的統計門檻：{detail}"
        )

    result["sufficient"] = len(result["reasons"]) == 0
    return result


def generate_backtest_ai_report(ss) -> str:
    """
    產生回測績效的AI分析報告，採資深分析師跟主管報告的6段式架構：
      1. 結論先行  2. 資料充足性聲明  3. 分項發現(附樣本數)
      4. 異常與矛盾點  5. 建議行動  6. 已知限制

    只有 check_data_sufficiency() 判定資料充足時才會真正呼叫AI，
    未達標時直接回傳說明文字，不浪費API成本、也不會對雜訊下結論。
    建議執行頻率：週報/月報，不建議每天執行
    （回測結論不會因為多一天資料就有意義的改變，天天跑只是徒增噪音跟成本）
    """
    sufficiency = check_data_sufficiency(ss)

    if not sufficiency["sufficient"]:
        reasons_text = "\n".join(f"- {r}" for r in sufficiency["reasons"])
        bucket_text = "\n".join(f"  - {b}：{c} 筆" for b, c in sufficiency["bucket_counts"].items())
        return f"""## ⚠️ 資料量尚不足以進行AI分析

**目前狀態**：累積 {sufficiency['total_records']} 筆快照、{sufficiency['trading_days']} 個交易日

**各評分區間樣本數**：
{bucket_text}

**尚未達標的原因**：
{reasons_text}

**為什麼現在不分析**：在樣本不足、市場狀態涵蓋不全的情況下，任何統計結果都可能只是短期雜訊。
AI在這種情況下容易產出「聽起來合理但缺乏統計意義」的敘事（敘事謬誤），
反而會讓人誤以為系統已被驗證有效。建議繼續累積資料，待達標後再進行分析。"""

    score_summary = get_backtest_summary(ss)
    signal_summary = get_signal_summary(ss)
    intensity_results = get_institutional_intensity_summary(ss)
    relative_summary = get_relative_strength_by_period(ss)

    def _df_to_text(df, title):
        if df is None or df.empty:
            return f"【{title}】\n（無資料）\n"
        return f"【{title}】\n{df.to_string(index=False)}\n"

    data_blocks = [
        _df_to_text(score_summary, "綜合評分區間 vs 未來報酬率/勝率/波段最大機會"),
        _df_to_text(signal_summary, "法人訊號類型 vs 未來報酬率/勝率"),
    ]
    if intensity_results.get("換手強度") is not None:
        data_blocks.append(_df_to_text(intensity_results["換手強度"], "法人換手強度% vs 未來報酬率"))
    if intensity_results.get("買超轉換率") is not None:
        data_blocks.append(_df_to_text(intensity_results["買超轉換率"], "買超轉換率% vs 未來報酬率"))
    data_blocks.append(_df_to_text(relative_summary, "相對大盤(0050)超額報酬% —— 排除大盤系統性漲跌後的真實選股能力"))

    data_text = "\n".join(data_blocks)

    prompt = f"""你是一位資深量化分析師，現在要針對一套自建的台股ETF籌碼評分系統的回測結果，
向主管做一份誠實、嚴謹的績效驗證報告。這套系統用「多檔主動式ETF同時持有同一標的」加上
三大法人買賣超、基本面成長等因子，產出0-11分的「綜合評分」，理論上分數越高代表未來報酬應該越好。

以下是目前累積的回測統計資料（每組都已標示樣本數）：

{data_text}

累積總樣本數：{sufficiency['total_records']} 筆快照，涵蓋 {sufficiency['trading_days']} 個交易日。

請用以下架構撰寫報告（繁體中文，Markdown格式，適合直接呈現給主管看）：

## 結論先行
用1-2句話講清楚：這套評分系統目前是否展現出統計上有意義的選股能力，還是證據仍不足以下定論。
不要誇大，如果證據薄弱就明講證據薄弱。

## 資料充足性聲明
誠實說明目前的樣本數、涵蓋的市場狀態（例如是否只測到單一方向的行情、有沒有經歷完整漲跌循環）、
時間跨度是否足夠，坦白目前分析結果的可信度邊界。

## 分項發現
針對上面每一組資料，各用1-2句話講重點發現，且必須引用具體數字和樣本數，不能只講「看起來不錯」這種空話。

## 異常與矛盾點
主動指出資料中任何違反直覺、或跟「評分應該正相關未來報酬」的假設矛盾的地方
（例如某個高分組表現反而比低分組差），並嘗試給出可能解釋，但同時要明確標註
「這可能只是樣本不足的雜訊，需要更多資料才能確認」，不要迴避或選擇性忽略不利的結果。

## 建議行動
給出具體、可執行的下一步建議（例如繼續觀察、調整評分權重的方向、需要補充哪類資料等）。

## 已知限制
列出這份回測方法論上的已知限制（例如存活偏差——股票掉出榜單就看不到後續表現、
樣本可能集中在特定市場狀態、多重比較問題等），不要等被問才講。

語氣要專業、誠實、避免過度推銷結論，這是要對真實決策負責的分析，不是行銷文案。"""

    result = call_claude(
        prompt,
        system="你是嚴謹的量化分析師，重視統計證據強度，絕不誇大薄弱證據的結論，會主動揭露方法論限制。",
        max_tokens=2500,
    )

    if not result:
        return "⚠️ AI分析報告產生失敗（API呼叫無回應），請稍後再試。"

    return result