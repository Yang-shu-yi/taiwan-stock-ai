# Vercel Dashboard 部署指南

這個專案的網站已從 Streamlit 移到 Vercel 靜態站。Pi 負責產生盤前、盤後、盤中資料快照，Vercel 負責呈現 Dashboard 與台灣股票查詢。

## 架構

- 前端檔案：`web/index.html`、`web/styles.css`、`web/app.js`
- Build script：`scripts/build_vercel_site.mjs`
- Build 輸出：`web/dist`
- 每日快照：`runtime/daily_candidates.json`，若不存在則使用 `tests/fixtures/sample_daily_candidates.json`
- 台股查詢索引：`web/data/tw_stock_index.json`

## 本地建置

```bash
npm run build
```

檢查必要輸出：

```bash
npm run test:web
```

## 台灣股票查詢

網站查詢功能使用靜態股票索引搭配 Vercel API：

- `web/data/tw_stock_index.json`：代號與中文名稱查詢。
- `/api/stock-analysis?code=2330`：即時抓 Yahoo Finance chart，計算近一年技術分析。
- 前端個股報告：總評分、趨勢/動能/量能/風險分數、近 120 日價格圖、關鍵指標、風險與失效條件。

更新股票索引：

```bash
python scripts/export_tw_stock_index.py
```

索引只保留 `twstock` 標記為「股票」的上市櫃台股，不把 ETF 混入主要查詢。查詢結果會再對照每日快照中的候選股與中小型雷達資料。若 Vercel API 或 Yahoo chart 暫時失敗，前端會退回每日快照中的候選股分析。

## Vercel 設定

- Framework Preset：Other
- Build Command：`npm run build`
- Output Directory：`web/dist`

正式部署：

```bash
npx vercel deploy --prod --yes
```

## 快照資料

預設讀取：

```text
/data/daily_candidates.json
```

如果未來要改成外部 snapshot URL，可設定：

```text
VERCEL_SNAPSHOT_URL=https://example.com/daily_candidates.json
```

股票索引也可外部化：

```text
VERCEL_STOCK_INDEX_URL=https://example.com/tw_stock_index.json
```

## 分工原則

- Pi：抓資料、跑策略、產生報告、發 Telegram/LINE。
- Vercel：展示資料、股票查詢、視覺化。
- GitHub Actions：測試與 dry-run，不作為正式通知來源。
