"""
main.py v2
整合新版 fetcher（etfinfo.tw）+ analyzer + sheets_writer
Cloud Run Jobs 執行入口
"""
import os
import sys
import logging
from datetime import datetime

# 確保 src 目錄在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytz
from fetcher import fetch_all_etfs, aggregate_smart_money, get_last_trading_date
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
CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
LINE_TOKEN       = os.environ.get("LINE_NOTIFY_TOKEN", "")
TRADE_DATE       = os.environ.get("TRADE_DATE", get_last_trading_date())


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

    cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "平均權重%", "訊號", "持有ETF清單"]
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

    # ── 階段三：寫入 Google Sheets ──────────────────────────
    log.info("[3/3] 寫入 Google Sheets...")
    try:
        client = get_client(CREDENTIALS_PATH)
        ss = get_or_create_spreadsheet(client, SPREADSHEET_ID)
        write_smart_money_to_sheets(ss, smart_df, TRADE_DATE)
        log.info("Google Sheets 寫入完成！")
    except Exception as e:
        log.error(f"Sheets 寫入失敗: {e}")
        sys.exit(1)

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
