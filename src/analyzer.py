"""
analyzer.py
8 點籌碼演算法 — 對每檔成分股評分，輸出狙擊分數 0–8
"""
import pandas as pd
import numpy as np
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ── 8 點評分標準（可調整閾值） ──────────────────────────────
THRESHOLDS = {
    "trust_net_min":     500,    # 投信單日買超最低張數
    "trust_cum_min":    2000,    # 投信累計買超最低張數（近5日）
    "consec_days_min":     3,    # 最低連續買超天數
    "amount_min":    5_000_000,  # 最低成交金額（萬元 * 10000）
    "volume_ratio_min":  1.2,    # 量能增幅倍數（今日/5日均量）
    "amplitude_max":    0.07,    # 震幅上限（7%，過高視為高風險當沖）
    "fund_growth_min":   0.05,   # 五日資金增幅下限（5%）
    "weight_change_warn": 0.30,  # ETF 權重單日變動警戒（±30%）
}


def score_trust_cumulative(row: pd.Series) -> int:
    """指標1：投信累計買超金額 — 偵測主力重押"""
    return 1 if row.get("trust_cum_5d", 0) >= THRESHOLDS["trust_cum_min"] else 0


def score_consecutive_buying(row: pd.Series) -> int:
    """指標2：連續建倉趨勢 — 5日以上籌碼穩定流入"""
    return 1 if row.get("consec_buy_days", 0) >= THRESHOLDS["consec_days_min"] else 0


def score_above_ma20(row: pd.Series) -> int:
    """指標3：主力建倉與 MA20 關係 — 站上月線"""
    return 1 if row.get("above_ma20", False) else 0


def score_trading_amount(row: pd.Series) -> int:
    """指標4：成交金額 — 流動性與買盤集中度"""
    return 1 if row.get("amount", 0) >= THRESHOLDS["amount_min"] else 0


def score_volume_ratio(row: pd.Series) -> int:
    """指標5：量能增幅 — 攻擊力道"""
    return 1 if row.get("volume_ratio", 0) >= THRESHOLDS["volume_ratio_min"] else 0


def score_amplitude_control(row: pd.Series) -> int:
    """指標6：震幅控制 — 排除高風險當沖（震幅越小越好）"""
    amp = row.get("amplitude", 1.0)
    return 1 if amp <= THRESHOLDS["amplitude_max"] else 0


def score_fund_growth(row: pd.Series) -> int:
    """指標7：五日資金增幅 vs 跌幅 — 籌碼穩定度"""
    return 1 if row.get("fund_growth_5d", 0) >= THRESHOLDS["fund_growth_min"] else 0


def score_weight_change(row: pd.Series) -> tuple[int, str]:
    """
    指標8：權重異常變動偵測
    回傳 (分數, 警示標籤)
    正常加碼 → 1分；異常突發減碼 → 0分 + ⚠️
    """
    change = abs(row.get("weight_change_pct", 0))
    is_buying = row.get("trust_net", 0) > 0

    if change >= THRESHOLDS["weight_change_warn"] and not is_buying:
        return 0, "⚠️ 權重異常"
    elif change >= THRESHOLDS["weight_change_warn"] and is_buying:
        return 1, "🔔 突發加碼"
    else:
        return 1, ""


def compute_labels(score: int, row: pd.Series) -> str:
    """根據總分與指標產出標籤"""
    labels = []

    if row.get("consec_buy_days", 0) >= THRESHOLDS["consec_days_min"]:
        labels.append("🔥 連續建倉")
    if row.get("above_ma20", False) and score >= 5:
        labels.append("✅ 強勢月線")
    if row.get("amplitude", 1) > THRESHOLDS["amplitude_max"]:
        labels.append("⚠️ 高波動")
    weight_warning = row.get("weight_warning", "")
    if weight_warning:
        labels.append(weight_warning)

    return "  ".join(labels)


def analyze_stock(row: pd.Series) -> dict:
    """對單檔股票執行 8 點評分，回傳評分結果"""
    w_score, w_label = score_weight_change(row)

    row = row.copy()
    row["weight_warning"] = w_label

    scores = {
        "s1_trust_cum":    score_trust_cumulative(row),
        "s2_consec_buy":   score_consecutive_buying(row),
        "s3_above_ma20":   score_above_ma20(row),
        "s4_amount":       score_trading_amount(row),
        "s5_vol_ratio":    score_volume_ratio(row),
        "s6_amplitude":    score_amplitude_control(row),
        "s7_fund_growth":  score_fund_growth(row),
        "s8_weight":       w_score,
    }

    total = sum(scores.values())
    label = compute_labels(total, row)

    return {
        **scores,
        "sniper_score":    total,
        "label":           label,
        "weight_warning":  w_label,
    }


def enrich_with_history(df: pd.DataFrame, history_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    加入歷史欄位計算（連續買超天數、累計買超、資金增幅等）
    history_df：過去 N 日的原始資料，從 Google Sheets 讀入
    """
    if history_df is None or history_df.empty:
        log.warning("無歷史資料，部分指標將以 0 計算")
        df["trust_cum_5d"]    = df.get("trust_net", pd.Series(0, index=df.index)).fillna(0)
        df["consec_buy_days"] = 0
        df["volume_ratio"]    = 1.0
        df["fund_growth_5d"]  = 0.0
        df["weight_change_pct"] = 0.0
        df["amplitude"]       = df.get("amplitude", pd.Series(0.03, index=df.index)).fillna(0.03)
        return df

    # 近5日投信累計買超
    recent5 = history_df[history_df["日期"].isin(
        sorted(history_df["日期"].unique())[-5:]
    )]
    cum_trust = (
        recent5.groupby("股票代號")["trust_net"]
        .sum()
        .reset_index()
        .rename(columns={"trust_net": "trust_cum_5d"})
    )
    df = df.merge(cum_trust, on="股票代號", how="left")
    df["trust_cum_5d"] = df["trust_cum_5d"].fillna(0)

    # 連續買超天數（從最新往回數）
    def count_consec(code):
        sub = history_df[history_df["股票代號"] == code].sort_values("日期", ascending=False)
        count = 0
        for _, r in sub.iterrows():
            if r.get("trust_net", 0) > 0:
                count += 1
            else:
                break
        return count

    stocks = df["股票代號"].unique()
    consec_map = {s: count_consec(s) for s in stocks}
    df["consec_buy_days"] = df["股票代號"].map(consec_map).fillna(0).astype(int)

    # 五日資金增幅（成交金額）
    if "amount" in history_df.columns:
        avg_amt = (
            recent5.groupby("股票代號")["amount"]
            .mean()
            .reset_index()
            .rename(columns={"amount": "avg_amount_5d"})
        )
        df = df.merge(avg_amt, on="股票代號", how="left")
        df["fund_growth_5d"] = (
            (df["amount"] - df["avg_amount_5d"]) / df["avg_amount_5d"].replace(0, np.nan)
        ).fillna(0)

    # 量能比（今日量 / 5日均量）
    if "volume" in history_df.columns:
        avg_vol = (
            recent5.groupby("股票代號")["volume"]
            .mean()
            .reset_index()
            .rename(columns={"volume": "avg_vol_5d"})
        )
        df = df.merge(avg_vol, on="股票代號", how="left")
        df["volume_ratio"] = (
            df["volume"] / df["avg_vol_5d"].replace(0, np.nan)
        ).fillna(1.0)

    return df


def run_analysis(raw_df: pd.DataFrame, history_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    主分析入口：傳入今日原始 DataFrame，回傳帶評分的結果
    """
    if raw_df.empty:
        log.error("輸入資料為空，無法執行分析")
        return pd.DataFrame()

    log.info(f"開始分析 {len(raw_df)} 筆持股記錄...")

    # 欄位標準化（處理 TWSE API 不同格式）
    col_map = {
        "股票代號": ["股票代號", "證券代號", "股號", "Code"],
        "股票名稱": ["股票名稱", "證券名稱", "名稱", "Name"],
        "持股比例": ["持股比例", "權重", "佔淨值比例"],
        "trust_net": ["投信買賣超", "投信淨買", "trust_net"],
        "close":     ["收盤價", "close"],
        "volume":    ["成交股數", "volume"],
        "amount":    ["成交金額", "amount"],
        "amplitude": ["震幅", "amplitude"],
        "above_ma20":["站上月線", "above_ma20"],
    }

    for target, candidates in col_map.items():
        if target not in raw_df.columns:
            for c in candidates:
                if c in raw_df.columns:
                    raw_df[target] = raw_df[c]
                    break
            if target not in raw_df.columns:
                raw_df[target] = 0

    # 填入預設值
    raw_df["trust_net"]  = pd.to_numeric(raw_df["trust_net"], errors="coerce").fillna(0)
    raw_df["close"]      = pd.to_numeric(raw_df["close"], errors="coerce").fillna(0)
    raw_df["volume"]     = pd.to_numeric(raw_df["volume"], errors="coerce").fillna(0)
    raw_df["amount"]     = pd.to_numeric(raw_df["amount"], errors="coerce").fillna(0)
    raw_df["amplitude"]  = pd.to_numeric(raw_df["amplitude"], errors="coerce").fillna(0.03)
    raw_df["weight_change_pct"] = 0.0

    # 加入歷史計算欄位
    df = enrich_with_history(raw_df, history_df)

    # 執行 8 點評分
    score_results = df.apply(analyze_stock, axis=1, result_type="expand")
    result = pd.concat([df, score_results], axis=1)

    # 找出同時被多檔 ETF 持有的股票（主力集中度加分依據）
    etf_coverage = (
        result.groupby("股票代號")["ETF代碼"]
        .nunique()
        .reset_index()
        .rename(columns={"ETF代碼": "etf_count"})
    )
    result = result.merge(etf_coverage, on="股票代號", how="left")

    # 依分數排序
    result = result.sort_values(
        ["sniper_score", "etf_count", "trust_cum_5d"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    result["排名"] = result.index + 1

    log.info(f"分析完成，共 {len(result)} 筆。滿分(8分)：{(result['sniper_score']==8).sum()} 筆")
    return result


if __name__ == "__main__":
    # 測試用：讀入 fetcher 產出的 CSV
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/etf_raw_test.csv"
    try:
        raw = pd.read_csv(path)
        result = run_analysis(raw)
        print(result[["股票代號", "股票名稱", "sniper_score", "label", "etf_count"]].head(20))
        result.to_csv("/tmp/etf_scored.csv", index=False, encoding="utf-8-sig")
        print("評分結果已存至 /tmp/etf_scored.csv")
    except FileNotFoundError:
        print(f"找不到 {path}，請先執行 fetcher.py")
