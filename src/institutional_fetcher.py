"""
institutional_fetcher.py
三大法人買賣超資料抓取
來源：TWSE 公開資料
外資 + 投信 + 自營商 每日買賣超
"""
import requests
import pandas as pd
import time
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
import pytz

log = logging.getLogger(__name__)
TW_TZ = pytz.timezone("Asia/Taipei")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.twse.com.tw/",
})


def get_trade_date() -> str:
    now = datetime.now(TW_TZ)
    if now.hour < 16:
        now -= timedelta(days=1)
    while now.weekday() >= 5:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


def fetch_institutional_all(trade_date: Optional[str] = None) -> pd.DataFrame:
    """
    抓取全市場三大法人買賣超彙總
    回傳：外資、投信、自營商各自買超金額/張數
    """
    if not trade_date:
        trade_date = get_trade_date()

    url = "https://www.twse.com.tw/fund/TWT38U"
    params = {"response": "json", "date": trade_date, "selectType": "ALL"}

    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()

        if data.get("stat") != "OK" or not data.get("data"):
            log.warning(f"三大法人彙總無資料 ({trade_date})")
            return pd.DataFrame()

        fields = data.get("fields", [])
        rows   = data.get("data", [])
        df = pd.DataFrame(rows, columns=fields)

        # 清洗數字欄位
        for col in df.columns:
            if col not in ["證券代號","證券名稱","名稱"]:
                df[col] = df[col].astype(str).str.replace(",","").str.replace("+","")
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["抓取日期"] = trade_date
        log.info(f"三大法人彙總：{len(df)} 筆 ({trade_date})")
        return df

    except Exception as e:
        log.error(f"三大法人彙總失敗: {e}")
        return pd.DataFrame()


def fetch_all_institutional(trade_date: Optional[str] = None) -> pd.DataFrame:
    """一次抓全市場三大法人，再過濾目標股票（比逐一抓取快且穩定）"""
    if not trade_date:
        trade_date = get_trade_date()
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"response": "json", "date": trade_date, "selectType": "ALLBUT0999"}
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            log.warning(f"三大法人全市場無資料 ({trade_date})")
            return pd.DataFrame()

        fields = data.get("fields", [])
        rows = data.get("data", [])
        df = pd.DataFrame(rows, columns=fields)

        def find_col(df, keywords):
            for col in df.columns:
                if all(k in col for k in keywords):
                    return col
            return None

        code_col    = find_col(df, ["證券代號"])
        name_col    = find_col(df, ["證券名稱"])
        
        def find_col_exact(df, name):
            return name if name in df.columns else None

        foreign_col    = find_col_exact(df, "外陸資買賣超股數(不含外資自營商)")
        dealer_fii_col = find_col_exact(df, "外資自營商買賣超股數")
        trust_col      = find_col_exact(df, "投信買賣超股數")
        dealer_col     = find_col_exact(df, "自營商買賣超股數")
        total_col      = find_col_exact(df, "三大法人買賣超股數")

        for name, col in [("foreign_col",foreign_col),("dealer_fii_col",dealer_fii_col),
                        ("trust_col",trust_col),("dealer_col",dealer_col),("total_col",total_col)]:
            if col is None:
                log.error(f"{name} 找不到對應欄位，TWSE 欄位可能又改了")

        df = df.rename(columns={code_col: "證券代號", name_col: "證券名稱"})

        # 清洗數字欄位（把千分位逗號去掉、轉數字）
        numeric_cols = [foreign_col, dealer_fii_col, trust_col, dealer_col, total_col]
        for col in numeric_cols:
            df[col] = df[col].astype(str).str.replace(",", "").str.replace("+", "")
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # 外資買賣超 = 一般外資 + 外資自營商（業界慣例外資通常合併計算）
        df["外資買賣超"] = df[foreign_col] + df[dealer_fii_col]
        df["投信買賣超"] = df[trust_col]
        df["自營買賣超"] = df[dealer_col]
        df["三大合計"]   = df[total_col]  # 直接用 API 算好的合計，不要自己重算

        df["證券代號"] = df["證券代號"].astype(str).str.strip()
        df["抓取日期"] = trade_date
        log.info(f"三大法人全市場：{len(df)} 筆 ({trade_date})")
        return df
    except Exception as e:
        log.error(f"三大法人全市場失敗: {e}")
        return pd.DataFrame()

def fetch_batch_institutional(
    stock_codes: list,
    trade_date: Optional[str] = None,
    delay: float = 0.4,
) -> pd.DataFrame:
    """
    批次抓取多檔股票三大法人資料
    """
    if not trade_date:
        trade_date = get_trade_date()

    # 一次抓全市場再過濾
    all_df = fetch_all_institutional(trade_date)
    if all_df.empty:
        log.warning("批次法人資料：無結果")
        return pd.DataFrame()
    codes = [str(c).strip() for c in stock_codes]
    df = all_df[all_df["證券代號"].isin(codes)].copy()
    df = df.rename(columns={"證券代號":"股票代號"})
    log.info(f"批次法人資料完成：{len(df)}/{len(stock_codes)} 筆")
    return df
    return df


def compute_institutional_signal(inst_df: pd.DataFrame) -> pd.DataFrame:
    """
    計算三大法人訊號強度
    外資、投信、自營同向買超 = 最強訊號
    """
    if inst_df.empty:
        return inst_df

    df = inst_df.copy()

    # 各法人方向（買超>0為True）
    df["外資買超"] = df["外資買賣超"] > 0
    df["投信買超"] = df["投信買賣超"] > 0
    df["自營買超"] = df["自營買賣超"] > 0

    # 同向買超法人數
    df["買超法人數"] = df[["外資買超","投信買超","自營買超"]].sum(axis=1).astype(int)

    # 訊號標籤
    def signal_label(row):
        n = row["買超法人數"]
        total = row["三大合計"]
        if n == 3:
            return "🔥 三大齊買"
        elif n == 2 and row["外資買超"] and row["投信買超"]:
            return "⚡ 外資+投信"
        elif n == 2 and row["外資買超"]:
            return "⚡ 外資主導"
        elif n == 2:
            return "⚡ 雙向買超"
        elif row["投信買超"]:
            return "🌱 投信單買"
        elif row["外資買超"]:
            return "🌱 外資單買"
        elif total < 0:
            return "🔻 法人賣超"
        else:
            return "➖ 混合"

    df["法人訊號"] = df.apply(signal_label, axis=1)

    # 排序：三大齊買 > 外資+投信 > 其他
    order = {"🔥 三大齊買":0,"⚡ 外資+投信":1,"⚡ 外資主導":2,
             "⚡ 雙向買超":3,"🌱 投信單買":4,"🌱 外資單買":5,"➖ 混合":6,"🔻 法人賣超":7}
    df["排序"] = df["法人訊號"].map(order).fillna(8)
    df = df.sort_values(["排序","三大合計"], ascending=[True,False])
    df = df.drop("排序", axis=1).reset_index(drop=True)
    df.insert(0, "排名", range(1, len(df)+1))

    buy3 = (df["買超法人數"] == 3).sum()
    buy2 = (df["買超法人數"] == 2).sum()
    log.info(f"法人訊號：三大齊買 {buy3} 檔，雙向買超 {buy2} 檔")
    return df


def cross_with_etf(
    inst_df: pd.DataFrame,
    smart_df: pd.DataFrame,
    fundamental_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    三大法人 × 主動ETF持股 × 基本面 交叉驗證
    綜合評分 0-10 分
    """
    if inst_df.empty or smart_df.empty:
        return pd.DataFrame()

    inst_df  = inst_df.copy()
    smart_df = smart_df.copy()

    inst_df["股票代號"]  = inst_df["股票代號"].astype(str).str.strip()
    smart_df["股票代號"] = smart_df["股票代號"].astype(str).str.strip()

    merged = smart_df.merge(
        inst_df[["股票代號","外資買賣超","投信買賣超","自營買賣超","三大合計","買超法人數","法人訊號"]],
        on="股票代號", how="left",
    )

    # 合併基本面
    if fundamental_df is not None and not fundamental_df.empty:
        fundamental_df = fundamental_df.copy()
        fundamental_df["股票代號"] = fundamental_df["股票代號"].astype(str).str.strip()
        fund_cols = ["股票代號","年增率%","營收訊號","本益比","本益比訊號","基本面分數"]
        avail_fund = [c for c in fund_cols if c in fundamental_df.columns]
        merged = merged.merge(fundamental_df[avail_fund], on="股票代號", how="left")

    merged["買超法人數"] = pd.to_numeric(merged.get("買超法人數"), errors="coerce").fillna(0).astype(int)
    merged["三大合計"]   = pd.to_numeric(merged.get("三大合計"),   errors="coerce").fillna(0)
    merged["基本面分數"] = pd.to_numeric(merged.get("基本面分數"), errors="coerce").fillna(0)

    # ── 綜合評分（0-10分）──────────────────────────────────────
    def total_score(row):
        # ETF 持股共識（0-3分）
        etf_n = int(row.get("持有ETF數", 0))
        etf_score = 3 if etf_n >= 10 else 2 if etf_n >= 5 else 1 if etf_n >= 3 else 0

        # 三大法人（0-3分）
        inst_n = int(row.get("買超法人數", 0))
        inst_score = 3 if inst_n == 3 else 2 if inst_n == 2 else 1 if inst_n == 1 else 0

        # 基本面月營收（0-2分）
        fund_score = min(float(row.get("基本面分數", 0)), 2)

        # 技術面（0-1分）
        ma_score = 1 if str(row.get("站上MA20","")).lower() in ["true","1","是"] else 0

        # 散戶情緒（0-1分，搜尋量低=好）
        # 暫時不加，等 Trends 資料穩定後加入

        return round(etf_score + inst_score + fund_score + ma_score, 1)

    merged["綜合評分"] = merged.apply(total_score, axis=1)

    # ── 多方驗證標籤 ────────────────────────────────────────────
    def multi_verify(row):
        tags = []
        if int(row.get("持有ETF數",0)) >= 5:
            tags.append("ETF✅")
        if int(row.get("買超法人數",0)) >= 2:
            tags.append("法人✅")
        rev_signal = str(row.get("營收訊號",""))
        if "成長" in rev_signal or "高速" in rev_signal:
            tags.append("營收✅")
        if str(row.get("站上MA20","")).lower() in ["true","1","是"]:
            tags.append("月線✅")
        return " ".join(tags) if tags else "—"

    merged["多方驗證"] = merged.apply(multi_verify, axis=1)

    result = merged.copy()
    result = result.sort_values(["綜合評分","三大合計"], ascending=[False,False])
    result = result.reset_index(drop=True)
    if "排名" in result.columns:
        result = result.drop(columns=["排名"])
    result.insert(0, "排名", range(1, len(result)+1))

    strong = (
        (pd.to_numeric(result.get("持有ETF數",0), errors="coerce") >= 5) &
        (result["買超法人數"] >= 2)
    )
    log.info(f"多方驗證：{strong.sum()} 檔 ETF+法人雙重確認，最高評分：{result['綜合評分'].max():.1f}")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    trade_date = get_trade_date()
    log.info(f"=== 測試三大法人抓取 ({trade_date}) ===")

    # 測試個股
    test_stocks = ["2330","2454","2383","6223","2308"]
    log.info(f"測試 {len(test_stocks)} 檔個股...")

    df = fetch_batch_institutional(test_stocks, trade_date)
    if not df.empty:
        df = compute_institutional_signal(df)
        print(df[["股票代號","外資買賣超","投信買賣超","自營買賣超","三大合計","法人訊號"]].to_string(index=False))
    else:
        log.warning("無法人資料（盤後 16:30 後才有）")
