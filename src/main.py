"""
main.py v2
整合新版 fetcher（etfinfo.tw）+ analyzer + sheets_writer
Cloud Run Jobs 執行入口
"""
import os
import pandas as pd
import sys
import logging
from datetime import datetime

# 確保 src 目錄在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytz
from fetcher import fetch_all_etfs, aggregate_smart_money, get_last_trading_date
from price_fetcher import enrich_with_prices, get_stock_price_single
from diff_analyzer import load_history_from_sheets, compute_daily_diff, compute_fund_flow, aggregate_stock_diff
from news_fetcher import fetch_all_news, tag_articles, auto_extract_hot_words
from institutional_fetcher import fetch_batch_institutional, compute_institutional_signal, cross_with_etf
from fundamental_fetcher import fetch_batch_fundamental
from trends_fetcher import fetch_all_trends, compute_trends_signal, cross_news_and_trends
from trend_analyzer import compute_keyword_timeseries, compute_trend_report, match_keywords_to_stocks
from sheets_writer import get_client, get_or_create_spreadsheet, write_all, read_history
from analyzer import run_analysis

def now_tw():
    return datetime.now(pytz.timezone("Asia/Taipei"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "")
SERPAPI_KEY      = os.environ.get("SERPAPI_KEY", "")
CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
LINE_TOKEN       = os.environ.get("LINE_NOTIFY_TOKEN", "")
# 交易日判斷：15:30 前用前一個交易日，15:30 後用今日
import pytz as _pytz
from datetime import timedelta
_tw_now = __import__("datetime").datetime.now(_pytz.timezone("Asia/Taipei"))
if _tw_now.hour < 15 or (_tw_now.hour == 15 and _tw_now.minute < 30):
    _trade_day = _tw_now - timedelta(days=1)
    # 若前一天是週日(6)或週一(0)要再往前
    while _trade_day.weekday() >= 5:
        _trade_day -= timedelta(days=1)
else:
    _trade_day = _tw_now
_today_str = _trade_day.strftime("%Y%m%d")
TRADE_DATE = os.environ.get("TRADE_DATE", _today_str)
RUN_MODE = os.environ.get("RUN_MODE", "core")  # core | inst | news


def send_line_notify(message: str):
    if not LINE_TOKEN:
        return
    import requests
    try:
        requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_TOKEN}"},
            data={"message": message},
            timeout=10,
        )
        log.info("LINE 通知已送出")
    except Exception as e:
        log.warning(f"LINE 通知失敗: {e}")


def write_smart_money_to_sheets(ss, smart_df, trade_date: str):
    """將聰明錢名單寫入 Google Sheets 專用分頁"""
    import gspread

    SHEET_SMART = "聰明錢名單"
    SHEET_RAW   = "盤後原始數據庫"

    existing = [ws.title for ws in ss.worksheets()]

    # 建立分頁（若不存在）
    for name in [SHEET_SMART, SHEET_RAW]:
        if name not in existing:
            ss.add_worksheet(title=name, rows=3000, cols=20)
            log.info(f"建立分頁：{name}")

    # ── 寫入聰明錢名單（每日覆寫）──
    ws_smart = ss.worksheet(SHEET_SMART)
    ws_smart.clear()

    header_row = [f"⚡ 聰明錢名單 {trade_date}　更新：{now_tw().strftime('%H:%M')}"]
    ws_smart.append_row(header_row)

    cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "平均權重%", "訊號", "收盤價", "漲跌幅%", "MA20", "站上MA20", "持股市值(萬)", "持有ETF清單"]
    available = [c for c in cols if c in smart_df.columns]
    ws_smart.append_row(available)

    rows = smart_df[available].fillna("").values.tolist()
    ws_smart.append_rows(rows, value_input_option="USER_ENTERED")

    # 高分行標記顏色
    try:
        for i, (_, row) in enumerate(smart_df.iterrows(), start=3):
            n = row.get("持有ETF數", 0)
            if n >= 10:
                color = {"red": 0.88, "green": 1.0, "blue": 0.88}  # 深綠
            elif n >= 5:
                color = {"red": 1.0, "green": 0.95, "blue": 0.80}  # 淺黃
            else:
                continue
            ws_smart.format(f"A{i}:G{i}", {
                "backgroundColor": color,
                "textFormat": {"bold": n >= 10}
            })
    except Exception as e:
        log.warning(f"格式化失敗（不影響資料）: {e}")

    log.info(f"聰明錢名單寫入完成：{len(smart_df)} 檔 → {SHEET_SMART}")
    return ws_smart


def _write_fundamental_to_sheets(ss, fund_df, trade_date):
    """寫入基本面資料到 Sheets"""
    import time
    SHEET_FUND = "基本面資料"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_FUND not in existing:
        ss.add_worksheet(title=SHEET_FUND, rows=500, cols=15)
    ws = ss.worksheet(SHEET_FUND)
    ws.clear()
    ws.append_row([f"基本面資料 {trade_date}　更新：{now_tw().strftime('%H:%M')}"])
    if not fund_df.empty:
        cols = ["股票代號","最新月份","月營收(億)","年增率%","月增率%","營收訊號","本益比","本益比訊號","基本面分數"]
        avail = [c for c in cols if c in fund_df.columns]
        time.sleep(3)
        ws.append_row(avail)
        rows = fund_df[avail].fillna("").values.tolist()
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    log.info(f"基本面資料 寫入完成")


def _write_trends_to_sheets(ss, trends_df, cross_df, trade_date):
    """寫入 Google Trends 資料到 Sheets"""
    import time
    for sheet_name, df in [("散戶情緒", trends_df), ("題材位置", cross_df)]:
        existing = [ws.title for ws in ss.worksheets()]
        if sheet_name not in existing:
            ss.add_worksheet(title=sheet_name, rows=500, cols=15)
        ws = ss.worksheet(sheet_name)
        ws.clear()
        ws.append_row([f"{sheet_name} {trade_date}　更新：{now_tw().strftime('%H:%M')}"])
        if not df.empty:
            time.sleep(5)
            ws.append_row(df.columns.tolist())
            time.sleep(3)
            rows = df.fillna("").values.tolist()
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"{sheet_name} 寫入完成")
        time.sleep(10)


def _write_institutional_to_sheets(ss, inst_df, cross_df, trade_date):
    """寫入三大法人資料到 Sheets"""
    import time
    for sheet_name, df, cols in [
        ("三大法人", inst_df, ["排名","股票代號","外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數","法人訊號"]),
        ("多方驗證名單", cross_df, ["排名","股票代號","股票名稱","持有ETF數","買超法人數","法人訊號","綜合評分","多方驗證","三大合計","收盤價","漲跌幅%"]),
    ]:
        existing = [ws.title for ws in ss.worksheets()]
        if sheet_name not in existing:
            ss.add_worksheet(title=sheet_name, rows=1000, cols=20)
        ws = ss.worksheet(sheet_name)
        ws.clear()
        ws.append_row([f"{sheet_name} {trade_date}　更新：{now_tw().strftime('%H:%M')}"])
        if not df.empty:
            avail = [c for c in cols if c in df.columns]
            time.sleep(2)
            ws.append_row(avail)
            rows = df[avail].fillna("").values.tolist()
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"{sheet_name} 寫入完成")
        time.sleep(5)


def _write_news_to_sheets(ss, news_df, trade_date):
    """寫入新聞歷史庫（每日追加）"""
    SHEET_NEWS = "新聞歷史庫"
    existing = [ws.title for ws in ss.worksheets()]
    if SHEET_NEWS not in existing:
        ss.add_worksheet(title=SHEET_NEWS, rows=50000, cols=15)
        log.info(f"建立分頁：{SHEET_NEWS}")

    ws = ss.worksheet(SHEET_NEWS)
    all_vals = ws.get_all_values()

    # 只保留有命中關鍵字的新聞（節省空間）
    tagged = news_df[news_df["關鍵字數"] > 0].copy() if "關鍵字數" in news_df.columns else news_df

    cols = ["抓取日期", "來源", "標題", "命中關鍵字", "發布時間", "連結"]
    avail = [c for c in cols if c in tagged.columns]

    if not all_vals or all_vals == [[]]:
        ws.append_row(avail)

    rows = tagged[avail].fillna("").values.tolist()
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    log.info(f"新聞寫入：{len(rows)} 篇 → {SHEET_NEWS}")


def _load_news_history(ss, days: int = 14) -> pd.DataFrame:
    """讀取最近 N 天的新聞歷史"""
    try:
        ws = ss.worksheet("新聞歷史庫")
        all_vals = ws.get_all_values()
        if not all_vals or len(all_vals) < 2:
            return pd.DataFrame()
        df = pd.DataFrame(all_vals[1:], columns=all_vals[0])
        df = df[df.apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)]

        if "抓取日期" in df.columns:
            dates = sorted(df["抓取日期"].unique())[-days:]
            df = df[df["抓取日期"].isin(dates)]
        return df
    except Exception as e:
        log.warning(f"讀取新聞歷史失敗: {e}")
        return pd.DataFrame()


def _write_trend_to_sheets(ss, trend_df, cross_df, trade_date):
    """寫入題材趨勢報告"""
    for sheet_name, df in [("題材趨勢", trend_df), ("新聞×籌碼交叉", cross_df)]:
        existing = [ws.title for ws in ss.worksheets()]
        if sheet_name not in existing:
            ss.add_worksheet(title=sheet_name, rows=1000, cols=20)

        ws = ss.worksheet(sheet_name)
        ws.clear()
        ws.append_row([f"題材分析 {trade_date}　更新：{now_tw().strftime('%H:%M')}"])
        if not df.empty:
            ws.append_row(df.columns.tolist())
            rows = df.fillna("").values.tolist()
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"{sheet_name} 寫入完成")


def _write_diff_to_sheets(ss, stock_diff, diff_detail, trade_date):
    """寫入差異比對結果到 Google Sheets"""
    SHEET_DIFF    = "今日訊號"
    SHEET_DETAIL  = "持股異動明細"

    existing = [ws.title for ws in ss.worksheets()]
    for name in [SHEET_DIFF, SHEET_DETAIL]:
        if name not in existing:
            ss.add_worksheet(title=name, rows=3000, cols=20)
            log.info(f"建立分頁：{name}")

    # 寫入今日訊號（聚合）
    ws_diff = ss.worksheet(SHEET_DIFF)
    ws_diff.clear()
    header = [f"⚡ 今日訊號 {trade_date}　更新：{now_tw().strftime('%H:%M')}"]
    ws_diff.append_row(header)

    if not stock_diff.empty:
        cols = ["排名","股票代號","股票名稱","主要狀態",
                "加碼ETF數","減碼ETF數","新增ETF數","清倉ETF數",
                "總變動張數","平均權重變動%","總資金動向","收盤價"]
        available = [c for c in cols if c in stock_diff.columns]
        ws_diff.append_row(available)
        rows = stock_diff[available].fillna("").values.tolist()
        ws_diff.append_rows(rows, value_input_option="USER_ENTERED")

        # 格式化加碼行（綠色）
        try:
            for i, (_, row) in enumerate(stock_diff.iterrows(), start=3):
                status = row.get("主要狀態", "")
                if "加碼" in status or "新增" in status:
                    color = {"red": 0.88, "green": 1.0, "blue": 0.88}
                elif "減碼" in status or "清倉" in status:
                    color = {"red": 1.0, "green": 0.88, "blue": 0.88}
                else:
                    continue
                ws_diff.format(f"A{i}:K{i}", {"backgroundColor": color})
        except Exception as e:
            log.warning(f"格式化失敗: {e}")

    log.info(f"今日訊號寫入完成 → {SHEET_DIFF}")

    # 寫入異動明細
    ws_detail = ss.worksheet(SHEET_DETAIL)
    ws_detail.clear()
    if not diff_detail.empty:
        detail_cols = ["股票代號","股票名稱","ETF代碼","狀態",
                       "持股數_今","持股數_昨","變動張數","資金動向(萬)","今日","昨日"]
        avail = [c for c in detail_cols if c in diff_detail.columns]
        ws_detail.append_row(avail)
        rows = diff_detail[avail].fillna("").values.tolist()
        ws_detail.append_rows(rows, value_input_option="USER_ENTERED")
    log.info(f"異動明細寫入完成 → {SHEET_DETAIL}")


def main():
    log.info(f"===== ETF 狙擊系統啟動 | {TRADE_DATE} =====")

    if not SPREADSHEET_ID:
        log.error("缺少 SPREADSHEET_ID 環境變數")
        sys.exit(1)
    if not CREDENTIALS_PATH:
        log.error("缺少 GOOGLE_APPLICATION_CREDENTIALS 環境變數")
        sys.exit(1)

    # ── 階段一：採集 34 檔 ETF ──────────────────────────────
    log.info("[1/3] 抓取 34 檔主動式 ETF 持股...")

    if RUN_MODE in ("inst", "news"):
        # inst/news 模式：直接從 Sheets 讀取今日資料，不重新抓取
        log.info(f"RUN_MODE={RUN_MODE}，從 Sheets 讀取今日資料...")
        _client0 = get_client(CREDENTIALS_PATH)
        _ss0 = get_or_create_spreadsheet(_client0, SPREADSHEET_ID)
        raw_df = load_history_from_sheets(_ss0, days=1)
        raw_df = raw_df[raw_df["抓取時間"] == TRADE_DATE].copy() if not raw_df.empty else pd.DataFrame()
        if raw_df.empty:
            log.warning(f"Sheets 無 {TRADE_DATE} 資料，改為重新抓取")
            raw_df = fetch_all_etfs(TRADE_DATE)
    else:
        raw_df = fetch_all_etfs(TRADE_DATE)

    if raw_df.empty:
        msg = f"[{TRADE_DATE}] 無資料（可能非交易日）"
        log.warning(msg)
        send_line_notify(f"\n⚠️ {msg}")
        sys.exit(0)

    log.info(f"採集完成：{len(raw_df)} 筆持股記錄")

    # ── 階段二：聰明錢聚合分析 ──────────────────────────────
    log.info("[2/3] 執行聰明錢聚合分析...")
    smart_df = aggregate_smart_money(raw_df)

    if smart_df.empty:
        log.error("聚合結果為空")
        sys.exit(1)

    # 印出 Top 10
    log.info("今日 Top 10 聰明錢標的：")
    cols_show = ["排名", "股票代號", "股票名稱", "持有ETF數", "訊號"]
    available = [c for c in cols_show if c in smart_df.columns]
    for _, row in smart_df.head(10).iterrows():
        log.info(f"  [{row.get('排名','?'):2}] {row.get('股票代號','')} {row.get('股票名稱',''):8} "
                 f"被 {row.get('持有ETF數',0):2d} 檔ETF持有  {row.get('訊號','')}")

    # ── 階段二.五：串接股價（寫入前先抓） ──────────────────────
    log.info("[+] 串接 TWSE 股價（收盤價、漲跌幅、持股市值）...")
    try:
        smart_df = enrich_with_prices(smart_df)
        got = smart_df['收盤價'].notna().sum() if '收盤價' in smart_df.columns else 0
        log.info(f"股價合併完成，有收盤價：{got} 檔")
    except Exception as e:
        log.warning(f"股價串接失敗（不影響主流程）: {e}")

    # ── 階段三：寫入 Google Sheets（僅 core 模式）────────────
    log.info("[3/3] 寫入 Google Sheets...")
    try:
        client = get_client(CREDENTIALS_PATH)
        ss = get_or_create_spreadsheet(client, SPREADSHEET_ID)
        if RUN_MODE == "core":
            write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)
            log.info("Google Sheets 寫入完成！")
        else:
            log.info(f"RUN_MODE={RUN_MODE}，跳過聰明錢/盤後寫入")

        # ── 追加盤後原始數據庫 ──
        try:
            ws_raw = ss.worksheet("盤後原始數據庫")
            all_vals = ws_raw.get_all_values()
            raw_cols = ["股票代號","股票名稱","權重%","持股數","ETF代碼","資料來源","抓取時間"]
            avail = [c for c in raw_cols if c in raw_df.columns]
            if not all_vals or all_vals == [[]]:
                ws_raw.append_row(avail)
            today_dates = [r[avail.index("抓取時間")] if "抓取時間" in avail else "" for r in all_vals[1:]]
            if TRADE_DATE not in today_dates:
                import time
                time.sleep(3)
                rows = raw_df[avail].fillna("").values.tolist()
                ws_raw.append_rows(rows, value_input_option="USER_ENTERED")
                log.info(f"盤後原始數據庫追加完成：{len(rows)} 筆 ({TRADE_DATE})")
            else:
                log.info(f"盤後原始數據庫已有 {TRADE_DATE} 資料，跳過")
        except Exception as e:
            log.warning(f"盤後原始數據庫寫入失敗（不影響主流程）: {e}")
    except Exception as e:
        log.error(f"Sheets 寫入失敗: {e}")
        sys.exit(1)

    # ── 階段四：每日差異比對（僅 core 模式）───────────────────────
    log.info("[4/4] 執行每日差異比對...")
    if RUN_MODE != "core":
        log.info(f"RUN_MODE={RUN_MODE}，跳過差異比對")
        else:
        try:
            client2 = get_client(CREDENTIALS_PATH)
            ss2 = get_or_create_spreadsheet(client2, SPREADSHEET_ID)
            history_df = load_history_from_sheets(ss2, days=2)

            if history_df.empty:
            log.warning("歷史資料不足，跳過差異比對（需要兩天資料）")
            else:
                # 今日原始資料
                diff_detail = compute_daily_diff(raw_df, history_df, TRADE_DATE)

                if not diff_detail.empty:
                    # 加入股價計算資金動向
                    if "收盤價" in smart_df.columns:
                        price_ref = smart_df[["股票代號","收盤價"]].drop_duplicates()
                        diff_detail = compute_fund_flow(diff_detail, price_ref)

                    # 跨ETF聚合
                    stock_diff = aggregate_stock_diff(diff_detail)

                    # 寫入 Sheets
                    _write_diff_to_sheets(ss2, stock_diff, diff_detail, TRADE_DATE)
                    log.info(f"差異比對完成：{len(stock_diff)} 檔有變動")
                else:
                    log.warning("差異比對無結果")
        except Exception as e:
            log.warning(f"差異比對失敗（不影響主流程）: {e}")

        # ── core 模式到此結束 ───────────────────────────────────────
        if RUN_MODE == "core":
            log.info("RUN_MODE=core，核心階段完成")
            log.info("===== 全部完成 =====")
            return

    # ── 階段五：新聞熱度收集與題材分析 ──────────────────────────
    log.info("[5/5] 收集財經新聞 + 題材生命週期分析...")
    try:
        # 抓取最新新聞
        news_df = fetch_all_news(hours_back=26)
        if not news_df.empty:
            news_df = tag_articles(news_df)
            hot_words = auto_extract_hot_words(news_df)
            log.info(f"新聞抓取：{len(news_df)} 篇，命中關鍵字文章：{(news_df['關鍵字數']>0).sum()} 篇")
            log.info(f"自動偵測熱詞：{hot_words[:10]}")

            # 寫入新聞歷史庫
            _write_news_to_sheets(ss2, news_df, TRADE_DATE)

            # 讀取歷史新聞做趨勢分析
            news_history = _load_news_history(ss2)
            if not news_history.empty:
                pivot = compute_keyword_timeseries(news_history)
                trend_df = compute_trend_report(pivot)
                cross_df = match_keywords_to_stocks(trend_df, smart_df)

                # 寫入趨勢報告
                _write_trend_to_sheets(ss2, trend_df, cross_df, TRADE_DATE)
                log.info(f"題材分析：{len(trend_df)} 個關鍵字，{len(cross_df)} 檔個股有題材支撐")
    except Exception as e:
        log.warning(f"新聞模組失敗（不影響主流程）: {e}")
        import traceback
        log.debug(traceback.format_exc())

    # ── news 模式到此結束，inst 模式跑法人/基本面 ────────────
    if RUN_MODE == "news":
        log.info("RUN_MODE=news，新聞階段完成")
        log.info("===== 全部完成 =====")
        return

    # ── 階段六.五：基本面資料 ───────────────────────────────────
    log.info("[6.5] 抓取基本面資料（月營收、本益比）...")
    fundamental_df = pd.DataFrame()
    try:
        stock_codes = smart_df["股票代號"].dropna().astype(str).unique().tolist()[:30]
        fundamental_df = fetch_batch_fundamental(stock_codes, delay=0.5)
        if not fundamental_df.empty:
            log.info(f"基本面完成：{len(fundamental_df)} 檔，高速成長：{fundamental_df.get('營收訊號','').eq('🚀 高速成長').sum() if '營收訊號' in fundamental_df.columns else 0} 檔")
            # 寫入 Sheets
            import time as _t; _t.sleep(15)
            _write_fundamental_to_sheets(ss2, fundamental_df, TRADE_DATE)
    except Exception as e:
        log.warning(f"基本面失敗（不影響主流程）: {e}")

    # ── 階段六：三大法人買賣超 ─────────────────────────────────
    log.info("[6] 抓取三大法人買賣超...")
    try:
        stock_codes = smart_df["股票代號"].dropna().astype(str).unique().tolist()[:50]
        inst_df = fetch_batch_institutional(stock_codes, TRADE_DATE)

        if not inst_df.empty:
            inst_df = compute_institutional_signal(inst_df)
            cross_df = cross_with_etf(inst_df, smart_df, fundamental_df)

            # 寫入 Sheets
            import time as _t; _t.sleep(15)
            _write_institutional_to_sheets(ss2, inst_df, cross_df, TRADE_DATE)
            log.info(f"法人資料完成：{len(inst_df)} 檔，三大齊買：{(inst_df['買超法人數']==3).sum()} 檔")
        else:
            log.warning("法人資料為空（盤後 16:30 後才有）")
    except Exception as e:
        log.warning(f"法人模組失敗（不影響主流程）: {e}")

    # ── 階段七：Google Trends 散戶情緒 ──────────────────────────
    log.info("[7] 抓取 Google Trends 散戶情緒...")
    try:
        if SERPAPI_KEY:
            import os as _os
            _os.environ["SERPAPI_KEY"] = SERPAPI_KEY
            trends_raw = fetch_all_trends()
            if not trends_raw.empty:
                trends_signal = compute_trends_signal(trends_raw)
                # 與新聞趨勢交叉
                news_hist2 = _load_news_history(ss2)
                cross_df2 = pd.DataFrame()
                if not news_hist2.empty:
                    pivot2 = compute_keyword_timeseries(news_hist2)
                    news_trend2 = compute_trend_report(pivot2)
                    cross_df2 = cross_news_and_trends(news_trend2, trends_signal)
                    cross_df2 = cross_df2.loc[:,~cross_df2.columns.duplicated()]
                    if "排名" in cross_df2.columns: cross_df2 = cross_df2.drop(columns=["排名"])

                _write_trends_to_sheets(ss2, trends_signal, cross_df2, TRADE_DATE)
                log.info(f"Google Trends 完成：{len(trends_signal)} 個主題")
        else:
            log.warning("缺少 SERPAPI_KEY，跳過 Google Trends")
    except Exception as e:
        log.warning(f"Google Trends 失敗（不影響主流程）: {e}")

    # ── LINE 通知 Top 5 ──────────────────────────────────────
    top5 = smart_df.head(5)
    lines = [f"\n⚡ 聰明錢名單 {TRADE_DATE}\n"]
    for _, row in top5.iterrows():
        lines.append(
            f"[{row.get('持有ETF數',0)}檔] "
            f"{row.get('股票代號','')} {row.get('股票名稱','')} "
            f"{row.get('訊號','')}"
        )
    lines.append("\n(ETF狙擊系統自動產生)")
    send_line_notify("\n".join(lines))

    log.info("===== 全部完成 =====")


if __name__ == "__main__":
    main()
