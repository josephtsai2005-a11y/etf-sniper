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
"""
import logging
import pandas as pd
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SHEET_BACKTEST = "回測記錄"
HORIZONS = [1, 3, 5, 10, 20]  # 追蹤 T+1/T+3/T+5/T+10/T+20 個「交易日」後的報酬率
MAX_WINDOW = 20  # 「區間內最大報酬%」的觀察窗口天數


def _load_backtest_sheet(ss) -> pd.DataFrame:
    """讀取回測記錄分頁，不存在則回傳空表（含正確欄位結構）"""
    base_cols = ["記錄日期", "股票代號", "股票名稱", "進場收盤價", "綜合評分", "法人訊號",
                 "持有ETF數", "成交量", "法人換手強度%", "買超轉換率%"]
    return_cols = [f"T{n}報酬率%" for n in HORIZONS]
    extra_cols = [f"T{MAX_WINDOW}內最大報酬%", f"T{MAX_WINDOW}內最大報酬發生日"]
    all_cols = base_cols + return_cols + extra_cols

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
        ws = ss.add_worksheet(title=SHEET_BACKTEST, rows=20000, cols=20)
    else:
        ws = ss.worksheet(SHEET_BACKTEST)
    ws.clear()
    ws.append_row(df.columns.tolist())
    if not df.empty:
        rows = df.fillna("").values.tolist()
        chunk = 5000
        for i in range(0, len(rows), chunk):
            ws.append_rows(rows[i:i + chunk], value_input_option="USER_ENTERED")


def record_daily_snapshot(ss, smart_df: pd.DataFrame, trade_date: str):
    """
    每日記錄快照：把今天有評分/收盤價的股票各存一筆獨立紀錄
    建議在 inst 模式（16:45）、cross_df（多方驗證名單）已經算好各項法人指標之後呼叫
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
            **{f"T{n}報酬率%": "" for n in HORIZONS},
            f"T{MAX_WINDOW}內最大報酬%": "",
            f"T{MAX_WINDOW}內最大報酬發生日": "",
        })

    if not new_rows:
        log.info("回測記錄：本日無有效資料可記錄")
        return

    combined = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True) if not df.empty else pd.DataFrame(new_rows)
    _write_backtest_sheet(ss, combined)
    log.info(f"回測記錄：{trade_date} 新增 {len(new_rows)} 筆快照")


def backfill_returns(ss):
    """
    回填報酬率：掃描所有還沒填報酬率的舊紀錄，用「同股票、N個交易日後」的紀錄回填
    同時計算「T+20內最大報酬%」：掃描整個T+1~T+20區間找最高點，
    而不是只看第20天當天的價格，避免漏掉「盤整後才噴出」的波段行情
    建議每天執行一次（inst模式尾聲），會自動處理所有累積未完成的回填
    """
    df = _load_backtest_sheet(ss)
    if df.empty:
        return

    df["進場收盤價"] = pd.to_numeric(df["進場收盤價"], errors="coerce")

    trading_days = sorted(df["記錄日期"].unique().tolist())
    day_index = {d: i for i, d in enumerate(trading_days)}

    price_lookup = {}  # (股票代號, 記錄日期) -> 進場收盤價
    for _, row in df.iterrows():
        price_lookup[(row["股票代號"], row["記錄日期"])] = row["進場收盤價"]

    updated_count = 0
    max_updated_count = 0

    for idx, row in df.iterrows():
        code = row["股票代號"]
        rec_date = row["記錄日期"]
        entry_price = row["進場收盤價"]
        if pd.isna(entry_price) or rec_date not in day_index:
            continue

        rec_idx = day_index[rec_date]

        # ── 固定天數 T+N 報酬率 ──────────────────────────
        for n in HORIZONS:
            col = f"T{n}報酬率%"
            if row.get(col, "") not in ["", None] and not pd.isna(row.get(col, "")):
                continue

            target_idx = rec_idx + n
            if target_idx >= len(trading_days):
                continue

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

        # ── T+20內最大報酬% （掃描整個區間找最高點，不是只看第20天）──
        max_col = f"T{MAX_WINDOW}內最大報酬%"
        date_col = f"T{MAX_WINDOW}內最大報酬發生日"
        already_has_max = row.get(max_col, "") not in ["", None] and not pd.isna(row.get(max_col, ""))
        window_end_idx = rec_idx + MAX_WINDOW
        window_closed = window_end_idx < len(trading_days)  # 完整20天資料都已存在，才算「最終結果」

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
                # 區間尚未走完前，先存入「目前為止的最大值」，等區間走完（window_closed）才不再更新，視為最終結果
                # （這樣可以提早看到趨勢，不用整整等20天才有資料）
                df.at[idx, max_col] = round(best_ret, 2)
                df.at[idx, date_col] = best_date
                max_updated_count += 1

    if updated_count > 0 or max_updated_count > 0:
        _write_backtest_sheet(ss, df)
        log.info(f"回測回填完成：T+N報酬率 {updated_count} 筆，T{MAX_WINDOW}內最大報酬 {max_updated_count} 筆")
    else:
        log.info("回測回填：本次無新資料可回填")


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
    """依「綜合評分區間」分組，統計各期間平均報酬率、勝率、以及T20內最大報酬%"""
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