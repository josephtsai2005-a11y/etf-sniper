"""
test_20260916_retail_sentiment_and_topic_position.py

驗證2026-09-16修正：「散戶情緒」頁面兩個圖表的問題根源都在trends_fetcher.py。

1. compute_trends_signal()：原本只有3級分類（散戶淡漠/散戶關注/散戶追捧），跟app.py
   散點圖畫的5色圖例（💤淡漠/🌱萌芽/⚡追進/🔥爆買/📉退場）名稱完全對不上，導致顏色套用
   不到、圖例塌縮成幾乎只剩一種顏色。這次改成5級分類，並新增「退場」（曾經有明顯高點、
   最近才滑落）跟「淡漠」（本來就一直沒人關注）的區分。
2. cross_news_and_trends()：原本只做資料合併，從沒有算出「題材位置」分類欄位，導致
   「題材位置分析」頁面永遠是空的。這次補上classify_topic_position()真正的交叉分類邏輯。

執行方式：python3 test_20260916_retail_sentiment_and_topic_position.py
"""
import sys
sys.path.insert(0, "/home/claude/etf_opt")
sys.path.insert(0, "/tmp/live_repo/src")

import pandas as pd
from trends_fetcher import compute_trends_signal, classify_topic_position, cross_news_and_trends


def _make_trends_df(keyword, values):
    """建立compute_trends_signal()吃的輸入格式：日期、搜尋量、關鍵字"""
    dates = [f"2026-09-{10+i:02d}" for i in range(len(values))]
    return pd.DataFrame({"日期": dates, "搜尋量": values, "關鍵字": [keyword] * len(values)})


print("=== 測試1：compute_trends_signal() 5級分類 ===")

# 1a. 一直沒人搜尋（從沒超過20）→ 淡漠，不能誤判成退場
df_dull = _make_trends_df("冷門題材", [0, 1, 0, 2, 1, 0, 1])
result = compute_trends_signal(df_dull)
row = result[result["主題"] == "冷門題材"].iloc[0]
assert row["散戶關注度"] == "💤 散戶淡漠", f"一直沒人搜尋應該是淡漠，實際：{row['散戶關注度']}"
print(f"✅ 一直沒人搜尋（峰值過低）-> {row['散戶關注度']}（正確排除退場誤判）")

# 1b. 幾天前有明顯高點（peak=80），現在已經滑落回接近0 -> 退場
df_faded = _make_trends_df("退燒題材", [5, 10, 80, 60, 20, 5, 3])
result = compute_trends_signal(df_faded)
row = result[result["主題"] == "退燒題材"].iloc[0]
assert row["散戶關注度"] == "📉 散戶退場", f"曾經有高點後滑落應該是退場，實際：{row['散戶關注度']}"
print(f"✅ 曾經有高點（80）後滑落到個位數 -> {row['散戶關注度']}")

# 1c. 萌芽區間 30-45（峰值出現在中間，最後一天已經從峰值回落到峰值的30-45%）
df_budding = _make_trends_df("萌芽題材", [20, 50, 100, 80, 60, 40, 35])
result = compute_trends_signal(df_budding)
row = result[result["主題"] == "萌芽題材"].iloc[0]
assert row["散戶關注度"] == "🌱 散戶萌芽", f"應為萌芽，實際：{row['散戶關注度']}（相對峰值%={row['相對峰值%']}）"
print(f"✅ 相對峰值{row['相對峰值%']}% -> {row['散戶關注度']}")

# 1d. 追進區間 45-60
df_chasing = _make_trends_df("追進題材", [20, 50, 100, 80, 60, 55, 50])
result = compute_trends_signal(df_chasing)
row = result[result["主題"] == "追進題材"].iloc[0]
assert row["散戶關注度"] == "⚡ 散戶追進", f"應為追進，實際：{row['散戶關注度']}（相對峰值%={row['相對峰值%']}）"
print(f"✅ 相對峰值{row['相對峰值%']}% -> {row['散戶關注度']}")

# 1e. 爆買區間 >=60（峰值出現在倒數第3天，最後一天仍維持在峰值的60%以上）
df_buying = _make_trends_df("爆買題材", [10, 30, 60, 100, 90, 80, 70])
result = compute_trends_signal(df_buying)
row = result[result["主題"] == "爆買題材"].iloc[0]
assert row["散戶關注度"] == "🔥 散戶爆買", f"應為爆買，實際：{row['散戶關注度']}"
print(f"✅ 相對峰值{row['相對峰值%']}% -> {row['散戶關注度']}")

# 1f. 圖表顏色映射對得上：確認5種分類字串都跟app.py stage_colors的key完全一致
expected_labels = {"💤 散戶淡漠", "🌱 散戶萌芽", "⚡ 散戶追進", "🔥 散戶爆買", "📉 散戶退場"}
all_df = pd.concat([df_dull, df_faded, df_budding, df_chasing, df_buying], ignore_index=True)
all_result = compute_trends_signal(all_df)
produced_labels = set(all_result["散戶關注度"].unique())
assert produced_labels.issubset(expected_labels), f"出現app.py stage_colors沒有定義的分類: {produced_labels - expected_labels}"
print(f"✅ 所有分類字串都在app.py stage_colors的5個key裡: {produced_labels}")

print("\n=== 測試2：classify_topic_position() 新聞×搜尋交叉分類 ===")

assert classify_topic_position("🔥 爆發", 15) == "🎯 法人期"
print("✅ 新聞爆發 + 搜尋冷(15) -> 🎯 法人期")

assert classify_topic_position("⚡ 成長", 50) == "⚠️ 過熱期"
print("✅ 新聞成長 + 搜尋熱(50) -> ⚠️ 過熱期")

assert classify_topic_position("🌱 萌芽", 10) == "💤 未發酵"
print("✅ 新聞萌芽（算冷） + 搜尋冷(10) -> 💤 未發酵")

assert classify_topic_position("💤 沉寂", 70) == "📉 退燒中"
print("✅ 新聞沉寂 + 搜尋熱(70) -> 📉 退燒中")

# 邊界：門檻剛好30算熱
assert classify_topic_position("🔥 爆發", 30) == "⚠️ 過熱期"
print("✅ 相對峰值剛好30% -> 算搜尋熱（跟散點圖的30%門檻線一致）")

# 缺資料（NaN/None）不應該crash，且視為搜尋冷
assert classify_topic_position("🔥 爆發", None) == "🎯 法人期"
assert classify_topic_position("🔥 爆發", float("nan")) == "🎯 法人期"
print("✅ 搜尋熱度資料缺失（None/NaN）不會crash，視為搜尋冷")

print("\n=== 測試3：cross_news_and_trends() 整合輸出 ===")

news_trend_df = pd.DataFrame({
    "排名": [1, 2, 3, 4],
    "關鍵字": ["CoWoS", "HBM", "電動車", "除權息"],
    "階段": ["🔥 爆發", "⚡ 成長", "🌱 萌芽", "💤 沉寂"],
    "今日篇數": [12, 8, 3, 0],
    "近3日均": [10.0, 6.0, 2.0, 0.0],
    "近7日均": [5.0, 5.0, 2.0, 0.0],
    "成長率%": [100.0, 20.0, 0.0, 0.0],
    "峰值篇數": [12, 8, 4, 2],
    "累計篇數": [30, 25, 10, 5],
    "趨勢": ["↑", "↑", "→", "→"],
})

trends_signal_df = pd.DataFrame({
    "排名": [1, 2, 3, 4],
    "主題": ["CoWoS", "HBM", "電動車", "除權息"],
    "散戶關注度": ["💤 散戶淡漠", "⚡ 散戶追進", "💤 散戶淡漠", "🔥 散戶爆買"],
    "進場訊號": ["最佳布局期", "注意，散戶陸續進場", "最佳布局期", "危險，散戶已大量湧入"],
    "當前搜尋量": [10, 40, 5, 90],
    "相對峰值%": [15.0, 50.0, 10.0, 95.0],
})

result = cross_news_and_trends(news_trend_df, trends_signal_df)
assert not result.empty, "正常輸入不應該回傳空"
for col in ["排名", "主題", "題材位置", "新聞篇數", "當前搜尋量"]:
    assert col in result.columns, f"缺少app.py需要顯示的欄位: {col}"
print(f"✅ 輸出欄位齊全: {[c for c in ['排名','主題','題材位置','新聞篇數','當前搜尋量'] if c in result.columns]}")

positions = dict(zip(result["主題"], result["題材位置"]))
assert positions["CoWoS"] == "🎯 法人期", f"CoWoS應為法人期，實際：{positions}"
assert positions["HBM"] == "⚠️ 過熱期", f"HBM應為過熱期，實際：{positions}"
assert positions["電動車"] == "💤 未發酵", f"電動車應為未發酵，實際：{positions}"
assert positions["除權息"] == "📉 退燒中", f"除權息應為退燒中，實際：{positions}"
print(f"✅ 四種題材位置分類全部正確: {positions}")

# 排序：法人期應該排在最前面
assert result.iloc[0]["主題"] == "CoWoS", f"法人期應該排第一，實際第一筆是：{result.iloc[0]['主題']}"
assert list(result["排名"]) == list(range(1, len(result) + 1)), "排名欄位應該是重新連續編號"
print(f"✅ 排序正確（法人期優先），排名重新連續編號: {list(result['排名'])}")

# 空輸入
assert cross_news_and_trends(pd.DataFrame(), trends_signal_df).empty
assert cross_news_and_trends(news_trend_df, pd.DataFrame()).empty
print("✅ 任一輸入為空 -> 正確回傳空DataFrame")

print("\n🎉 全部測試通過！")