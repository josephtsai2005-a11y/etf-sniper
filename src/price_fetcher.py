"""
price_fetcher.py v3
串接 TWSE 股價 API
取得：收盤價、漲跌、漲跌幅%、MA20、站上月線、成交量、成交金額
注意：同時保留股票名稱（從 holdings_df 帶入，不從 TWSE 另外抓）
"""
import requests
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from retry_utils import retry_sheets_write

log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.twse.com.tw/",
})


def _roc_date_to_gregorian(roc_date_str: str) -> str:
    """
    把TWSE回傳的民國年日期字串轉成西元年8碼（YYYYMMDD），供跟TRADE_DATE比較用。

    背景：TWSE的STOCK_DAY等API固定回傳民國年格式的「日期」欄位（例如"115/08/31"代表
    2026-08-31，115=年份、用"/"分隔），但系統其他地方（TRADE_DATE、main.py的過期偵測、
    backfill_prices_to_multi_sheet的資料日期比對）用的都是西元年8碼格式（例如"20260831"）。

    2026-08-30部署的「資料日期」欄位／過期偵測／股價回填機制，一直沒有做這個轉換，
    直接拿民國年格式的字串（"115/08/31"）跟西元年格式（"20260831"）比較，
    這兩種格式不管實際資料新不新，字串永遠不會相等——等於這個比對從一開始就是壞的，
    「過期資料偵測」log天天都會誤報、「股價回填機制」永遠不會真的覆蓋任何資料，
    不是TWSE真的每次都延遲，是比對邏輯本身有問題。
    """
    try:
        parts = roc_date_str.strip().split("/")
        if len(parts) != 3:
            return ""
        roc_year, month, day = parts
        gregorian_year = int(roc_year) + 1911
        return f"{gregorian_year:04d}{int(month):02d}{int(day):02d}"
    except Exception:
        return ""


def _looks_like_futures_or_invalid(stock_code: str) -> bool:
    """
    過濾明顯不是個股代號的項目（例如期貨合約 "202608 臺股期貨08/26"）
    真正的TWSE個股代號多為4碼數字，或4碼數字+英文字母（如興櫃/特別股）；
    6碼且以"20"開頭、全為數字的，高機率是期貨合約的到期年月，直接跳過避免浪費API呼叫
    """
    if not stock_code:
        return True
    code = stock_code.strip()
    if len(code) == 6 and code.isdigit() and code.startswith("20"):
        return True
    return False


def get_stock_price_single(stock_code: str, retries: int = 2) -> dict:
    """
    取得單一股票近期行情（跨月合併，確保有足夠交易日計算 MA20）
    新增：MA5/MA10、均線排列狀態、連續站上月線天數、量能比
    retries: 抓取失敗時的重試次數（避免單次網路異常/TWSE暫時異常就整檔放棄）
    """
    if _looks_like_futures_or_invalid(stock_code):
        log.debug(f"{stock_code} 疑似非個股代號（期貨/無效），跳過股價抓取")
        return {}

    today = datetime.now()
    this_month = today.strftime("%Y%m") + "01"
    prev_month_date = (today.replace(day=1) - timedelta(days=1)).strftime("%Y%m") + "01"

    url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

    def fetch_month(date_str):
        params = {"response": "json", "date": date_str, "stockNo": stock_code}
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return pd.DataFrame()
        fields = data.get("fields", [])
        rows = data.get("data", [])
        return pd.DataFrame(rows, columns=fields)

    last_error = None
    for attempt in range(retries + 1):
        try:
            df_this = fetch_month(this_month)
            df_prev = fetch_month(prev_month_date)
            df = pd.concat([df_prev, df_this], ignore_index=True) if not df_prev.empty else df_this

            if df.empty:
                # TWSE本身回傳「無資料」（例如真的還沒開始交易），重試沒有意義，直接放棄
                return {}
            break  # 成功拿到資料，跳出重試迴圈
        except Exception as e:
            last_error = e
            if attempt < retries:
                log.debug(f"{stock_code} 第{attempt+1}次抓取失敗，重試中: {e}")
                time.sleep(1.5)
                continue
            log.warning(f"{stock_code} 股價抓取失敗（已重試{retries}次）: {e}")
            return {}

    try:
        if df.empty:
            return {}

        for col in df.columns:
            if col not in ["日期"]:
                df[col] = df[col].astype(str).str.replace(",", "").str.replace("+", "")
                df[col] = pd.to_numeric(df[col], errors="coerce")

        close_col  = next((c for c in df.columns if "收盤" in c), None)
        high_col   = next((c for c in df.columns if "最高" in c), None)
        low_col    = next((c for c in df.columns if "最低" in c), None)
        change_col = next((c for c in df.columns if "漲跌" in c and "幅" not in c), None)
        vol_col    = next((c for c in df.columns if "成交股數" in c or "成交量" in c), None)
        amt_col    = next((c for c in df.columns if "成交金額" in c), None)

        if not close_col or df.empty:
            return {}

        closes = df[close_col].dropna().tolist()
        if not closes:
            return {}

        latest_close = closes[-1]
        ma5  = round(sum(closes[-5:])  / min(len(closes), 5),  2)
        ma10 = round(sum(closes[-10:]) / min(len(closes), 10), 2)
        ma20 = round(sum(closes[-20:]) / min(len(closes), 20), 2)
        above_ma20 = latest_close > ma20

        # 均線排列狀態
        if ma5 > ma10 > ma20:
            ma_alignment = "多頭排列"
        elif ma5 < ma10 < ma20:
            ma_alignment = "空頭排列"
        else:
            ma_alignment = "糾結"

        # 連續站上月線天數：回溯計算過去每一天的MA20，反推連續天數
        consecutive_above = 0
        if len(closes) >= 21:
            for i in range(len(closes) - 1, 19, -1):  # 從最新一天往回，至少要有20天可算MA20
                day_ma20 = sum(closes[i-20:i]) / 20
                if closes[i] > day_ma20:
                    consecutive_above += 1
                else:
                    break

        # 量能比：今日成交量 / 近5日均量
        volume_ratio = 0
        if vol_col and len(df) >= 5:
            recent_vols = df[vol_col].dropna().tolist()
            if len(recent_vols) >= 5:
                today_vol = recent_vols[-1]
                avg5_vol = sum(recent_vols[-6:-1]) / 5  # 不含今天的前5日均量
                volume_ratio = round(today_vol / avg5_vol, 2) if avg5_vol > 0 else 0

        # ── KD值（隨機指標，9,3,3）──────────────────────
        # RSV = (收盤-N日最低) / (N日最高-N日最低) * 100，K/D皆用3日平滑
        k_val, d_val, kd_signal = None, None, ""
        if high_col and low_col and len(closes) >= 9:
            n = 9
            highs = df[high_col].tolist()
            lows = df[low_col].tolist()
            k_series, d_series = [], []
            prev_k, prev_d = 50.0, 50.0  # 起始值慣例用50
            for i in range(len(closes)):
                if i < n - 1:
                    k_series.append(prev_k)
                    d_series.append(prev_d)
                    continue
                period_high = max(highs[i - n + 1:i + 1])
                period_low = min(lows[i - n + 1:i + 1])
                if period_high == period_low:
                    rsv = 50.0
                else:
                    rsv = (closes[i] - period_low) / (period_high - period_low) * 100
                cur_k = prev_k * 2 / 3 + rsv * 1 / 3
                cur_d = prev_d * 2 / 3 + cur_k * 1 / 3
                k_series.append(cur_k)
                d_series.append(cur_d)
                prev_k, prev_d = cur_k, cur_d

            k_val = round(k_series[-1], 1)
            d_val = round(d_series[-1], 1)

            if len(k_series) >= 3:
                diff_series = [k_series[i] - d_series[i] for i in range(len(k_series))]
                prev_diff = diff_series[-2]
                cur_diff = diff_series[-1]
                # 差距是否連續2天在縮小（不論正負，代表兩線正在靠近，交叉在醞釀中）
                gap_narrowing = abs(diff_series[-1]) < abs(diff_series[-2]) < abs(diff_series[-3])

                if prev_diff <= 0 and cur_diff > 0:
                    kd_signal = "🟢 黃金交叉"
                elif prev_diff >= 0 and cur_diff < 0:
                    kd_signal = "🔴 死亡交叉"
                elif cur_diff < 0 and gap_narrowing and k_val < 50:
                    kd_signal = "🌱 醞釀黃金交叉"  # 提早訊號：還沒交叉，但K正在低檔追上D
                elif cur_diff > 0 and gap_narrowing and k_val > 50:
                    kd_signal = "🍂 醞釀死亡交叉"  # 提早訊號：還沒交叉，但K正在高檔被D追上
                elif cur_diff > 0:
                    kd_signal = "K>D"
                else:
                    kd_signal = "K<D"

                # 高檔過熱：K、D兩者都卡在80以上，不論有沒有交叉都值得留意——
                # 這種情況常常是「持續噴出、指標鈍化」，可能還沒死叉但風險已經在累積
                # （2026-08-28使用者比對真實券商資料後提出的需求：K/D高檔糾結，比單純等死叉更早示警）
                if k_val >= 80 and d_val >= 80:
                    kd_signal = f"🌡️ 高檔過熱（{kd_signal}）"

        # ── MACD（12,26,9 EMA）───────────────────────────
        dif_val, macd_signal_val, macd_hist, macd_cross = None, None, None, ""
        if len(closes) >= 26:
            close_series = pd.Series(closes)
            ema12 = close_series.ewm(span=12, adjust=False).mean()
            ema26 = close_series.ewm(span=26, adjust=False).mean()
            dif_series = ema12 - ema26
            signal_series = dif_series.ewm(span=9, adjust=False).mean()
            hist_series = dif_series - signal_series

            dif_val = round(dif_series.iloc[-1], 2)
            macd_signal_val = round(signal_series.iloc[-1], 2)
            macd_hist = round(hist_series.iloc[-1], 2)

            if len(hist_series) >= 3:
                h = hist_series.tolist()
                prev_hist, cur_hist = h[-2], h[-1]
                # 柱狀連續2天縮小（力道衰竭中，不論正負）
                hist_shrinking = abs(h[-1]) < abs(h[-2]) < abs(h[-3])

                if prev_hist <= 0 and cur_hist > 0:
                    macd_cross = "🟢 黃金交叉"
                elif prev_hist >= 0 and cur_hist < 0:
                    macd_cross = "🔴 死亡交叉"
                elif cur_hist < 0 and hist_shrinking:
                    macd_cross = "🌱 空方動能趨緩"  # 提早訊號：柱狀仍是負的，但空方力道在減弱
                elif cur_hist > 0 and hist_shrinking:
                    macd_cross = "🍂 多方動能趨緩"  # 提早訊號：柱狀仍是正的，但多方力道在減弱
                elif cur_hist > 0:
                    macd_cross = "柱狀翻紅"
                else:
                    macd_cross = "柱狀翻綠"

        # ── 背離偵測（提早出場訊號中最經典的一種）─────────────
        # 股價創近期新高，但KD沒有跟著創新高 → 動能其實已經衰竭，價格是靠慣性衝高
        divergence_signal = ""
        lookback = 10
        if len(closes) >= lookback and k_val is not None:
            try:
                recent_closes = closes[-lookback:]
                recent_k = k_series[-lookback:]
                price_making_new_high = recent_closes[-1] >= max(recent_closes)
                kd_not_confirming = recent_k[-1] < max(recent_k[:-1]) - 5  # K值明顯低於前段高點
                if price_making_new_high and kd_not_confirming:
                    divergence_signal = "⚠️ 頂部背離：價格創高但KD未跟上"
            except Exception:
                pass

        # ── 布林通道（20期，2倍標準差）────────────────────────
        # 中軌沿用MA20；上下軌反映近期波動範圍，可看「是否觸及極端」跟「通道寬窄變化（噴出前兆）」
        bb_upper, bb_lower, bb_position, bb_signal = None, None, "", ""
        if len(closes) >= 20:
            recent20 = closes[-20:]
            std20 = pd.Series(recent20).std()
            bb_mid = ma20
            bb_upper = round(bb_mid + 2 * std20, 2)
            bb_lower = round(bb_mid - 2 * std20, 2)
            bb_width = round((bb_upper - bb_lower) / bb_mid * 100, 2) if bb_mid else 0  # 通道寬度%，越窄代表波動壓縮

            if latest_close >= bb_upper:
                bb_position = "🔥 觸及上軌"
            elif latest_close <= bb_lower:
                bb_position = "❄️ 觸及下軌"
            elif latest_close >= bb_mid:
                bb_position = "中軌之上"
            else:
                bb_position = "中軌之下"

            # 通道壓縮偵測：近5天通道寬度是否持續收斂，是「即將噴出」的經典早期訊號（不分方向）
            if len(closes) >= 25:
                widths = []
                for i in range(5):
                    idx_end = len(closes) - i
                    window = closes[idx_end - 20:idx_end]
                    w_mid = sum(window) / 20
                    w_std = pd.Series(window).std()
                    w_width = (w_mid + 2 * w_std - (w_mid - 2 * w_std)) / w_mid * 100 if w_mid else 0
                    widths.append(w_width)
                widths = widths[::-1]  # 轉成時間正序
                if widths[-1] < widths[-3] < widths[-5]:
                    bb_signal = "🌊 通道壓縮中（波動率降低，可能醞釀噴出，方向未定）"

        # ── ATR 真實波動幅度（14期）────────────────────────────
        # 反映該股「正常波動的絕對金額」，可用來動態設計停損（波動大的股票給寬一點停損）
        atr_val, atr_pct = None, None
        if high_col and low_col and len(closes) >= 15:
            highs_full = df[high_col].tolist()
            lows_full = df[low_col].tolist()
            trs = []
            for i in range(1, len(closes)):
                tr = max(
                    highs_full[i] - lows_full[i],
                    abs(highs_full[i] - closes[i - 1]),
                    abs(lows_full[i] - closes[i - 1]),
                )
                trs.append(tr)
            if len(trs) >= 14:
                atr_val = round(sum(trs[-14:]) / 14, 2)
                atr_pct = round(atr_val / latest_close * 100, 2) if latest_close else None

        # ── 技術面共振燈號：把均線/MACD/KD三個不同週期指標的方向合成一個燈號 ──
        # 三個都同意才是「共振」；方向不一致時明確標示「分歧」，不強行合併成單一買賣訊號
        tech_score = 0
        if ma_alignment == "多頭排列":
            tech_score += 1
        elif ma_alignment == "空頭排列":
            tech_score -= 1

        macd_bull_set = {"🟢 黃金交叉", "柱狀翻紅", "🌱 空方動能趨緩"}
        macd_bear_set = {"🔴 死亡交叉", "柱狀翻綠", "🍂 多方動能趨緩"}
        if macd_cross in macd_bull_set:
            tech_score += 1
        elif macd_cross in macd_bear_set:
            tech_score -= 1

        kd_bull_set = {"🟢 黃金交叉", "🌱 醞釀黃金交叉", "K>D"}
        kd_bear_set = {"🔴 死亡交叉", "🍂 醞釀死亡交叉", "K<D"}
        if kd_signal in kd_bull_set:
            tech_score += 1
        elif kd_signal in kd_bear_set:
            tech_score -= 1

        if tech_score == 3:
            resonance_signal = "🟢🟢 多頭共振"
        elif tech_score >= 1:
            resonance_signal = "🟢 偏多"
        elif tech_score == 0:
            resonance_signal = "⚠️ 訊號分歧"
        elif tech_score >= -2:
            resonance_signal = "🔴 偏空"
        else:
            resonance_signal = "🔴🔴 空頭共振"

        # 漲跌/漲跌幅：改用收盤價序列自己算（今日收盤 - 昨日收盤），
        # 不再直接信任TWSE原始「漲跌價差」欄位的文字格式——
        # 該欄位的正負號編碼在TWSE不同回應裡不一定一致，直接float()轉換曾經出現正負號顛倒的案例
        # （2026-08-28發現：某股實際上漲+3.43%，此欄位算出來卻是-3.43%，數值大小對但方向錯）
        if len(closes) >= 2:
            change = round(closes[-1] - closes[-2], 2)
            change_pct = round(change / closes[-2] * 100, 2) if closes[-2] else 0
        else:
            change = float(df[change_col].iloc[-1]) if change_col else 0
            change_pct = round(change / (latest_close - change) * 100, 2) if (latest_close - change) else 0

        # 資料日期：回傳實際抓到的最新一筆日期，供上層比對是否跟預期交易日一致，
        # 偵測「資料整天沒更新、停留在前一天」這種過期狀況（不會自動修正，只是讓過期狀況可被看見）。
        #
        # 重要：TWSE回傳的「日期」欄位是民國年格式（例如"115/08/31"），這裡一定要轉成
        # 西元年8碼（"20260831"）才能跟系統其他地方用的TRADE_DATE正確比較——
        # 這是2026-08-31發現的問題：轉換這一步原本漏掉了，導致「資料日期」跟TRADE_DATE
        # 用的是兩種不同曆法，字串永遠不會相等，讓「過期資料偵測」天天誤報、
        # 「股價回填機制」永遠判定為失敗、無法真的把資料寫回去，即使TWSE其實已經更新了。
        date_col_name = next((c for c in df.columns if "日期" in c), None)
        raw_data_date = str(df[date_col_name].iloc[-1]).strip() if date_col_name else ""
        latest_data_date = _roc_date_to_gregorian(raw_data_date)

        volume = float(df[vol_col].iloc[-1]) if vol_col else 0
        amount = float(df[amt_col].iloc[-1]) if amt_col else 0

        return {
            "股票代號": stock_code,
            "收盤價":   latest_close,
            "漲跌":     change,
            "漲跌幅%":  change_pct,
            "資料日期": latest_data_date,
            "MA5":      ma5,
            "MA10":     ma10,
            "MA20":     ma20,
            "站上MA20": above_ma20,
            "均線排列": ma_alignment,
            "連續站上月線天數": consecutive_above,
            "量能比":   volume_ratio,
            "K值":      k_val,
            "D值":      d_val,
            "KD訊號":   kd_signal,
            "DIF":      dif_val,
            "MACD":     macd_signal_val,
            "MACD柱狀": macd_hist,
            "MACD訊號": macd_cross,
            "背離警示": divergence_signal,
            "布林上軌": bb_upper,
            "布林下軌": bb_lower,
            "布林位置": bb_position,
            "布林壓縮": bb_signal,
            "ATR":      atr_val,
            "ATR%":     atr_pct,
            "技術面共振": resonance_signal,
            "成交量":   volume,
            "成交金額": amount,
        }

    except Exception as e:
        log.debug(f"{stock_code} 股價失敗: {e}")
        return {}


def enrich_with_prices(df: pd.DataFrame, top_n: Optional[int] = None) -> pd.DataFrame:
    """
    主入口：把股價欄位合併進 DataFrame
    - 預設抓「全部」追蹤股票（不再截斷前50檔，避免排名50名後的股票永遠抓不到價格）
    - 若明確傳入 top_n，才會限制只抓前N檔（保留彈性給未來需要限流的情境）
    - 自動過濾疑似期貨合約等非個股代號，避免浪費API呼叫時間
    - 股票名稱從原本的 df 保留，不會被覆蓋
    - 計算「持股市值(千萬)」= 持股數 × 收盤價 / 10000000
    """
    if df.empty or "股票代號" not in df.columns:
        return df

    all_codes = df["股票代號"].dropna().astype(str).unique().tolist()
    codes = [c for c in all_codes if not _looks_like_futures_or_invalid(c)]
    skipped = len(all_codes) - len(codes)
    if skipped > 0:
        log.info(f"過濾 {skipped} 檔疑似非個股代號（期貨/無效），不列入股價抓取")

    if top_n is not None:
        codes = codes[:top_n]

    log.info(f"抓取 {len(codes)} 檔股價...")

    records = []
    failed_codes = []
    for i, code in enumerate(codes, 1):
        result = get_stock_price_single(code)
        if result:
            records.append(result)
        else:
            failed_codes.append(code)
        if i % 10 == 0:
            log.info(f"  股價進度 {i}/{len(codes)}")
        time.sleep(0.35)

    if failed_codes:
        log.warning(f"以下 {len(failed_codes)} 檔股價抓取失敗（可能是TWSE無資料/新股/興櫃/暫停交易）: {failed_codes}")

    if not records:
        log.warning("無法取得任何股價")
        return df

    price_df = pd.DataFrame(records)
    price_df["股票代號"] = price_df["股票代號"].astype(str).str.strip()
    df["股票代號"] = df["股票代號"].astype(str).str.strip()

    # 保留原本名稱欄，合併股價（不合入名稱）
    price_cols = ["股票代號", "收盤價", "漲跌", "漲跌幅%", "資料日期", "MA5", "MA10", "MA20", "站上MA20",
              "均線排列", "連續站上月線天數", "量能比", "K值", "D值", "KD訊號",
              "DIF", "MACD", "MACD柱狀", "MACD訊號", "背離警示",
              "布林上軌", "布林下軌", "布林位置", "布林壓縮", "ATR", "ATR%", "技術面共振",
              "成交量", "成交金額"]
    price_df = price_df[[c for c in price_cols if c in price_df.columns]]

    merged = df.merge(price_df, on="股票代號", how="left")

    # 計算持股市值
    if "持股數" in merged.columns and "收盤價" in merged.columns:
        shares = pd.to_numeric(
            merged["持股數"].astype(str).str.replace(",", ""), errors="coerce"
        )
        merged["持股市值(千萬)"] = (shares * merged["收盤價"] / 10000000).round(0)

    got = merged["收盤價"].notna().sum()
    log.info(f"股價合併完成：{got}/{len(merged)} 筆有股價")
    return merged


def backfill_prices_to_multi_sheet(ss, trade_date: str, delay: float = 0.3) -> int:
    """
    股價回填機制：2026-08-28發現TWSE股價資料當天公布得比平常晚，16:45的daily job
    抓到的整批股票都停留在「前一交易日」的舊資料（收盤價、漲跌幅、KD、MACD等全部過期），
    卻沒有任何錯誤訊息，因為抓取邏輯只是「拿最後一筆」，沒有檢查那筆資料的日期是否真的是今天。

    這個函式設計成在較晚時段（23:00 ai job，比16:45多爭取6小時公布時間）呼叫，
    對「多方驗證名單」裡的每檔股票重新呼叫一次get_stock_price_single()，
    只有新抓到的「資料日期」確認等於trade_date，才會覆蓋更新該列的股價/技術指標欄位，
    避免用另一批依然過期的資料去覆蓋，白忙一場。

    回傳：成功回填的股票筆數（0代表這次重抓依然拿不到當天資料，可能TWSE延遲更嚴重）
    """
    SHEET_MULTI = "多方驗證名單"
    try:
        ws = ss.worksheet(SHEET_MULTI)
        all_values = ws.get_all_values()
    except Exception as e:
        log.warning(f"股價回填失敗，讀取「{SHEET_MULTI}」失敗: {e}")
        return 0

    if len(all_values) < 3:
        log.warning(f"股價回填失敗：「{SHEET_MULTI}」目前沒有足夠資料")
        return 0

    header = all_values[1]
    data_rows = all_values[2:]
    if "股票代號" not in header:
        log.warning(f"股價回填失敗：「{SHEET_MULTI}」找不到「股票代號」欄位")
        return 0

    df = pd.DataFrame(data_rows, columns=header)
    stock_codes = df["股票代號"].dropna().astype(str).unique().tolist()
    if not stock_codes:
        return 0

    # 這批欄位是股價/技術指標相關，過期時需要一併回填更新
    backfill_cols = ["收盤價", "漲跌", "漲跌幅%", "KD訊號", "MACD訊號", "背離警示", "ATR%", "技術面共振"]
    for col in backfill_cols:
        if col not in df.columns:
            df[col] = ""

    updated = 0
    stale_still = 0
    for idx, row in df.iterrows():
        code = str(row["股票代號"]).strip()
        try:
            live = get_stock_price_single(code)
        except Exception:
            live = None
        time.sleep(delay)

        if not live:
            continue

        fetched_date = str(live.get("資料日期", "")).replace("-", "").strip()
        if fetched_date and fetched_date != trade_date:
            stale_still += 1
            continue  # 這次重抓依然是舊資料，不覆蓋，維持原值

        for col in backfill_cols:
            if col in live:
                df.at[idx, col] = live[col]
        updated += 1

    if updated > 0:
        title_row = [all_values[0][0] if all_values[0] else f"{SHEET_MULTI} {trade_date}"]
        cols = df.columns.tolist()
        rows = df.fillna("").values.tolist()

        def _do_write():
            ws.clear()
            ws.append_row(title_row)
            time.sleep(2)
            ws.append_row(cols)
            ws.append_rows(rows, value_input_option="USER_ENTERED")

        try:
            # 這裡是clear()+整表重寫「多方驗證名單」，不是只回填的幾個欄位——寫入失敗時
            # 值得多重試幾次，因為失敗代表整張表被清空後沒寫回去，不只是回填的部分沒生效
            retry_sheets_write(_do_write, retries=3, base_wait=8, label="股價回填寫入")
            log.info(f"股價回填完成：{updated}/{len(df)} 檔已更新（資料日期：{trade_date}）"
                      f"，仍有{stale_still}檔重抓後依然是舊資料")
        except Exception as e:
            log.error(f"股價回填寫入失敗（已重試仍失敗）：「{SHEET_MULTI}」可能已被清空但寫入未完成，請檢查Sheets: {e}")
            return 0
    else:
        log.warning(f"股價回填：本次重抓{len(stock_codes)}檔全部依然是舊資料（TWSE延遲比預期更嚴重）")

    return updated