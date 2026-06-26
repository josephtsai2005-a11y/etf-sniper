"""
fetcher.py v4
主要來源：etfinfo.tw (BeautifulSoup 解析)
備用來源：個股排行 API
"""
import requests
import pandas as pd
import time
import logging
import re
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ETF_LIST = [
    "00403A","00981A","00991A","00405A","00988A","00400A","00992A","00990A",
    "00406A","00982A","00999A","00997A","00402A","00404A","00984A","00980A",
    "00994A","00401A","00996A","00984D","00993A","00985A","00995A","00987A",
    "00998A","00983A","00981D","00989A","00982D","00986A","00980D","00983D",
    "00986D","00985D"
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})


def get_last_trading_date() -> str:
    import pytz
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz)
    if today.hour < 16:
        today -= timedelta(days=1)
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    return today.strftime("%Y%m%d")


def fetch_etfinfo_holdings(etf_code: str, trade_date: str = None) -> pd.DataFrame:
    """
    爬取 etfinfo.tw 成分股頁面（BeautifulSoup 解析）
    資料：代號、名稱、權重、股數
    """
    url = f"https://www.etfinfo.tw/etf/{etf_code}/holdings"
    try:
        resp = SESSION.get(url, timeout=20)
        if resp.status_code != 200:
            log.debug(f"  {etf_code} HTTP {resp.status_code}")
            return pd.DataFrame()

        soup = BeautifulSoup(resp.text, "html.parser")

        # 找持股 table（有 代號/名稱/權重 欄位）
        rows = []
        table = soup.find("table")
        if not table:
            log.debug(f"  {etf_code} 無 table")
            return pd.DataFrame()

        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 2:
                continue
            row_text = [td.get_text(strip=True) for td in tds]
            rows.append(row_text)

        if len(rows) < 2:
            return pd.DataFrame()

        # 第一行為 header
        header = rows[0]
        data = rows[1:]
        df = pd.DataFrame(data, columns=header[:len(data[0])] if data else header)

        # etfinfo HTML 結構（已確認）：
        # <a href="/stock/2330" class="stock-code-link">2330</a>
        # <span class="stock-name-sub">台積電</span>
        stock_rows = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue

            first_td = tds[0]
            stock_code = None
            stock_name = None

            # 代號：從 <a href="/stock/XXXX"> 取
            a_tag = first_td.find("a", href=True)
            if a_tag:
                m = re.search(r"/stock/(\d{4,6})", a_tag.get("href", ""))
                if m:
                    stock_code = m.group(1)

            # 名稱：從 <span class="stock-name-sub"> 取（已確認此 class 名稱）
            name_span = first_td.find("span", class_="stock-name-sub")
            if name_span:
                stock_name = name_span.get_text(strip=True)

            if not stock_code:
                continue

            # 其餘欄位
            all_text = [td.get_text(strip=True) for td in tds]

            # 找權重（含%的數字）
            weight = ""
            shares = ""
            for cell in all_text[1:]:
                if "%" in cell and not weight:
                    w = re.search(r"([\d.]+)%", cell)
                    if w:
                        weight = w.group(1)
                # 找股數（純數字，通常較大）
                if re.match(r"^[\d,]+$", cell) and not shares:
                    shares = cell.replace(",", "")

            stock_rows.append({
                "股票代號": stock_code,
                "股票名稱": stock_name,
                "權重%": weight,
                "持股數": shares,
                "ETF代碼": etf_code,
                "資料來源": "etfinfo",
                "抓取時間": trade_date if trade_date else datetime.now(__import__("pytz").timezone("Asia/Taipei")).strftime("%Y%m%d"),
            })

        if not stock_rows:
            log.debug(f"  {etf_code} 解析不到股票行")
            return pd.DataFrame()

        result = pd.DataFrame(stock_rows)
        log.info(f"  {etf_code} OK: {len(result)} 檔持股")
        return result

    except Exception as e:
        log.error(f"  {etf_code} 錯誤: {e}")
        return pd.DataFrame()


def fetch_etfinfo_active_changes(etf_code: str) -> dict:
    """
    從 etfinfo.tw holdings 頁面抓最新異動摘要
    回傳：{'加碼': [...], '減碼': [...], '新增': [...], '清倉': [...]}
    """
    url = f"https://www.etfinfo.tw/etf/{etf_code}/holdings"
    changes = {"加碼": [], "減碼": [], "新增": [], "清倉": []}
    try:
        resp = SESSION.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        # 找「最新持股異動」區塊
        for tag in soup.find_all(["h2", "h3", "div", "section"]):
            text = tag.get_text()
            if "持股異動" in text or "加碼" in text:
                # 抓所有連結中的加碼/減碼標的
                for a in tag.find_all("a", href=True):
                    label = a.get_text(strip=True)
                    m = re.search(r"(\d{4})", a.get("href", ""))
                    if not m:
                        continue
                    code = m.group(1)
                    if "加碼" in label:
                        changes["加碼"].append(code)
                    elif "減碼" in label:
                        changes["減碼"].append(code)
                    elif "新增" in label:
                        changes["新增"].append(code)
                    elif "清倉" in label or "刪除" in label:
                        changes["清倉"].append(code)
                break
    except Exception as e:
        log.debug(f"  {etf_code} active changes 失敗: {e}")
    return changes


def fetch_all_etfs(trade_date: Optional[str] = None) -> pd.DataFrame:
    """批次抓取 34 檔 ETF 持股"""
    if not trade_date:
        trade_date = get_last_trading_date()
    log.info(f"開始抓取，共 {len(ETF_LIST)} 檔 ETF")

    frames, fail = [], []
    for i, code in enumerate(ETF_LIST, 1):
        log.info(f"[{i:02d}/{len(ETF_LIST)}] {code}")
        df = fetch_etfinfo_holdings(code, trade_date=trade_date)
        if not df.empty:
            frames.append(df)
        else:
            fail.append(code)
        time.sleep(1.5)

    log.info(f"完成：成功 {len(frames)} / {len(ETF_LIST)} 檔")
    if fail:
        log.warning(f"失敗：{fail}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def aggregate_smart_money(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """
    核心邏輯：統計每檔股票被幾檔ETF持有
    找出多方共識的「聰明錢集中股」
    """
    if holdings_df.empty:
        return pd.DataFrame()

    df = holdings_df.copy()
    df = df[df["股票代號"].str.match(r"^\d{4}$", na=False)]

    # 統計持有 ETF 數
    etf_count = (
        df.groupby("股票代號")["ETF代碼"]
        .nunique()
        .reset_index()
        .rename(columns={"ETF代碼": "持有ETF數"})
        .sort_values("持有ETF數", ascending=False)
    )

    # 加股票名稱
    name_map = df.drop_duplicates("股票代號")[["股票代號", "股票名稱"]]
    etf_count = etf_count.merge(name_map, on="股票代號", how="left")

    # 加持有 ETF 清單
    etf_list = (
        df.groupby("股票代號")["ETF代碼"]
        .apply(lambda x: " / ".join(sorted(x.unique())))
        .reset_index()
        .rename(columns={"ETF代碼": "持有ETF清單"})
    )
    etf_count = etf_count.merge(etf_list, on="股票代號", how="left")

    # 加平均權重
    df["權重%"] = pd.to_numeric(df["權重%"], errors="coerce")
    avg_w = df.groupby("股票代號")["權重%"].mean().round(2).reset_index()
    avg_w.columns = ["股票代號", "平均權重%"]
    etf_count = etf_count.merge(avg_w, on="股票代號", how="left")

    # 訊號標籤
    def label(n):
        if n >= 10: return "🔥🔥 超高集中"
        if n >= 5:  return "🔥 高度共識"
        if n >= 3:  return "⚡ 多方認同"
        return "— 單一持有"

    etf_count["訊號"] = etf_count["持有ETF數"].apply(label)
    etf_count.insert(0, "排名", range(1, len(etf_count) + 1))

    log.info(f"聚合完成：{len(etf_count)} 檔，3+ ETF 持有：{(etf_count['持有ETF數'] >= 3).sum()} 檔")
    return etf_count


if __name__ == "__main__":
    import sys

    # 確認 beautifulsoup4 已安裝
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("請先安裝：pip install beautifulsoup4 lxml")
        sys.exit(1)

    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    if mode == "test":
        code = sys.argv[2] if len(sys.argv) > 2 else "00981A"
        log.info(f"=== 測試 {code} ===")
        df = fetch_etfinfo_holdings(code)
        if df.empty:
            log.error("無資料！")
        else:
            print(f"\n成功！{len(df)} 檔持股：")
            print(df[["股票代號", "股票名稱", "權重%", "持股數"]].head(15).to_string(index=False))

        log.info(f"\n--- 持股異動 ---")
        changes = fetch_etfinfo_active_changes(code)
        for k, v in changes.items():
            if v:
                print(f"{k}：{v}")

    elif mode == "smart":
        quick = "--quick" in sys.argv
        target = ETF_LIST[:6] if quick else ETF_LIST
        log.info(f"=== 聰明錢模式：{'快速 6 檔' if quick else '全部 34 檔'} ===")

        frames = []
        for i, code in enumerate(target, 1):
            log.info(f"[{i}/{len(target)}] {code}")
            df = fetch_etfinfo_holdings(code)
            if not df.empty:
                frames.append(df)
            time.sleep(1.5)

        if frames:
            all_h = pd.concat(frames, ignore_index=True)
            smart = aggregate_smart_money(all_h)
            print("\n===== 聰明錢名單（前 25）=====")
            cols = ["排名", "股票代號", "股票名稱", "持有ETF數", "平均權重%", "訊號"]
            print(smart[cols].head(25).to_string(index=False))

            out = f"smart_money_{get_last_trading_date()}.csv"
            smart.to_csv(out, index=False, encoding="utf-8-sig")
            log.info(f"已存到 {out}")
        else:
            log.error("所有 ETF 均無資料")

    elif mode == "full":
        df = fetch_all_etfs()
        if not df.empty:
            out = f"etf_raw_{get_last_trading_date()}.csv"
            df.to_csv(out, index=False, encoding="utf-8-sig")
            smart = aggregate_smart_money(df)
            smart_out = f"smart_money_{get_last_trading_date()}.csv"
            smart.to_csv(smart_out, index=False, encoding="utf-8-sig")
            print(smart[["排名","股票代號","股票名稱","持有ETF數","訊號"]].head(20).to_string(index=False))
