# 部署指南 — 3 小時完成全部建置

## 前置需求（10 分鐘）
- Google 帳號（已有）
- GCP 帳號（信用卡綁定，但不會收費）
- GitHub 帳號
- Python 3.11+ 本機安裝
- Docker Desktop（部署時需要）

---

## STEP 1：建立 Google Cloud 專案（10 分鐘）

```bash
# 安裝 gcloud CLI：https://cloud.google.com/sdk/docs/install

# 登入並建立專案
gcloud auth login
gcloud projects create etf-sniper-2024 --name="ETF Sniper"
gcloud config set project etf-sniper-2024

# 啟用必要 API
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com
```

---

## STEP 2：建立 Service Account（5 分鐘）

```bash
# 建立 Service Account
gcloud iam service-accounts create etf-sniper-sa \
  --display-name="ETF Sniper Service Account"

# 授予權限
gcloud projects add-iam-policy-binding etf-sniper-2024 \
  --member="serviceAccount:etf-sniper-sa@etf-sniper-2024.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# 下載金鑰 JSON（本機測試用）
gcloud iam service-accounts keys create secrets/gcp-sa.json \
  --iam-account=etf-sniper-sa@etf-sniper-2024.iam.gserviceaccount.com

# 上傳金鑰到 Secret Manager（Cloud Run 用）
gcloud secrets create gcp-sa-json --data-file=secrets/gcp-sa.json
```

---

## STEP 3：建立 Google Sheets（5 分鐘）

1. 開啟 https://sheets.google.com 新增試算表
2. 命名為「ETF 狙擊系統」
3. 從網址取得 Spreadsheet ID：
   `https://docs.google.com/spreadsheets/d/【這段就是ID】/edit`
4. 點右上角「共用」→ 把 Service Account Email 加入（編輯者權限）：
   `etf-sniper-sa@etf-sniper-2024.iam.gserviceaccount.com`

```bash
# 設定環境變數
export SPREADSHEET_ID="你的試算表ID"
export GOOGLE_APPLICATION_CREDENTIALS="secrets/gcp-sa.json"
```

---

## STEP 4：本機測試（20 分鐘）

```bash
# 安裝依賴
pip install -r requirements.txt

# 測試採集（先用最新交易日）
cd src
python fetcher.py

# 測試分析
python analyzer.py /tmp/etf_raw_$(date +%Y%m%d).csv

# 測試寫入 Sheets
SPREADSHEET_ID="你的ID" python sheets_writer.py

# 測試完整流程
SPREADSHEET_ID="你的ID" python main.py
```

---

## STEP 5：啟動 Streamlit 看板（10 分鐘）

```bash
# 建立 secrets（複製模板）
cp .streamlit/secrets.toml.template .streamlit/secrets.toml
# 編輯 secrets.toml，填入真實值

# 本機執行
streamlit run app.py
# 瀏覽器開啟 http://localhost:8501
```

### 部署到 Streamlit Cloud（免費）：
1. 把程式碼推到 GitHub（secrets.toml 不要上傳！）
2. 登入 https://streamlit.io/cloud
3. New app → 選你的 GitHub repo → 選 `app.py`
4. Advanced settings → Secrets → 貼入 secrets.toml 內容
5. Deploy → 完成，取得公開 URL

---

## STEP 6：部署 Cloud Run Job（15 分鐘）

```bash
# 建立 Artifact Registry
gcloud artifacts repositories create etf-sniper \
  --repository-format=docker \
  --location=asia-east1

# Build & Push
gcloud builds submit --tag asia-east1-docker.pkg.dev/etf-sniper-2024/etf-sniper/sniper-job:latest

# 建立 Cloud Run Job
gcloud run jobs create etf-sniper-daily \
  --image asia-east1-docker.pkg.dev/etf-sniper-2024/etf-sniper/sniper-job:latest \
  --region asia-east1 \
  --set-env-vars "SPREADSHEET_ID=你的試算表ID" \
  --set-secrets "GOOGLE_APPLICATION_CREDENTIALS=gcp-sa-json:latest" \
  --max-retries 1 \
  --task-timeout 1800

# 手動測試執行一次
gcloud run jobs execute etf-sniper-daily --region asia-east1 --wait
```

---

## STEP 7：設定 Cloud Scheduler（5 分鐘）

```bash
# 建立排程：每週一到五 15:30 台灣時間
gcloud scheduler jobs create http etf-sniper-trigger \
  --location asia-east1 \
  --schedule "30 7 * * 1-5" \
  --uri "https://asia-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/etf-sniper-2024/jobs/etf-sniper-daily:run" \
  --http-method POST \
  --oauth-service-account-email etf-sniper-sa@etf-sniper-2024.iam.gserviceaccount.com \
  --time-zone "UTC"

# 驗證
gcloud scheduler jobs describe etf-sniper-trigger --location asia-east1
```

---

## STEP 8：設定 GitHub Actions 自動部署（10 分鐘）

在 GitHub repo → Settings → Secrets and variables → Actions，新增：

| Secret 名稱 | 值 |
|---|---|
| `GCP_PROJECT_ID` | `etf-sniper-2024` |
| `GCP_SA_KEY` | gcp-sa.json 的完整 JSON 內容 |
| `SPREADSHEET_ID` | Google Sheets ID |
| `LINE_NOTIFY_TOKEN` | LINE Notify Token（可選） |

之後每次 push 到 main branch，GitHub Actions 自動重新部署。

---

## 完成後的日常作業

| 事項 | 操作 |
|---|---|
| 查看今日狙擊名單 | 開啟 Streamlit URL |
| 手動觸發分析 | `gcloud run jobs execute etf-sniper-daily --region asia-east1` |
| 查看執行 Log | GCP Console → Cloud Run → Jobs → etf-sniper-daily |
| 修改 8 點閾值 | 編輯 `src/analyzer.py` 的 `THRESHOLDS` → push → 自動部署 |
| 查看費用 | GCP Console → Billing（預期 < NT$10/月）|

---

## 常見問題

**Q: TWSE API 回傳無資料？**
A: 確認今日是交易日，非假日非颱風停市。API 在盤後約 16:00 後才有當日資料。

**Q: Streamlit Cloud 休眠怎麼辦？**
A: 點開 URL 後等 10–15 秒自動喚醒，每天用幾次完全正常。

**Q: 想加 LINE 通知怎麼做？**
A: 前往 https://notify-bot.line.me/ 申請 Token，設定到環境變數 `LINE_NOTIFY_TOKEN`。
