# Vercel Dashboard 遷移說明

本專案已新增 Vercel 靜態版 Dashboard，用來取代 Streamlit 介面。

## 架構

- Pi 繼續負責盤前/盤後/盤中資料產生與通知。
- Vercel 只負責顯示 JSON snapshot，不負責跑台股掃描。
- 前端來源：`web/index.html`、`web/styles.css`、`web/app.js`
- Build script：`scripts/build_vercel_site.mjs`
- Vercel output：`web/dist`

## 部署

Vercel 專案設定：

- Framework Preset：Other
- Build Command：`npm run build`
- Output Directory：`web/dist`

本地測試：

```bash
npm run build
```

## 資料來源

預設會讀：

```text
/data/daily_candidates.json
```

Build 時會優先複製：

1. `runtime/daily_candidates.json`
2. `tests/fixtures/sample_daily_candidates.json`

正式即時更新建議：

- 短期：Pi 產出 snapshot 後，上傳到 Vercel Blob 或其他公開 JSON URL。
- Vercel 設定 `VERCEL_SNAPSHOT_URL=https://.../daily_candidates.json`
- Build script 會把這個 URL 寫入 `config.js`，前端會讀該 URL。

Pi 上傳 Vercel Blob 範例：

```bash
npx vercel blob put runtime/daily_candidates.json \
  --pathname daily_candidates.json \
  --access public \
  --allow-overwrite \
  --rw-token "$BLOB_READ_WRITE_TOKEN"
```

取得 blob URL 後，將它填到 Vercel 專案環境變數：

```text
VERCEL_SNAPSHOT_URL=https://...public.blob.vercel-storage.com/daily_candidates.json
```

## 為什麼不把資料掃描搬到 Vercel

台股掃描依賴 yfinance、TWSE、新聞 RSS、技術指標與 Pi 排程。直接放進 Vercel Serverless 會遇到：

- 執行時間不可控。
- Python 套件與 cold start 成本較高。
- 盤中長輪詢不適合 Serverless。
- 通知分流仍應由 Pi 控制。

因此目前最佳分工是：

- Pi：資料、策略、通知。
- Vercel：Dashboard 顯示與分享。
