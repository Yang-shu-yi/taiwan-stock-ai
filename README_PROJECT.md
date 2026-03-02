# 台股 AI 專案功能說明

這個專案提供完整的台股監控流程：

1. Web 儀表板（Streamlit）：盤後檢討與個股分析
2. 批次掃描：更新 stock_database.json
3. 樹莓派自動化：每日報告推送
4. 盤中偵察：即時訊號通知

## 模組與功能

### 1) Streamlit Web 儀表板
檔案：`app.py`

- 個股技術分析（RSI、MACD、KD、MA20/MA60）
- AI 個股分析（Groq）
- 主畫面保持精簡，聚焦個股分析

執行：
```bash
streamlit run app.py
```

### 2) 批次掃描（每日）
檔案：`batch_scan.py`

- 使用 Yahoo 資料掃描台股
- 計算 RSI + 漲跌幅
- 分類 RED / GREEN / YELLOW
- 更新 `stock_database.json`
- 推送 LINE + Telegram 統計

執行：
```bash
python batch_scan.py
```

限制掃描數量：
```bash
BATCH_SCAN_MAX=100 python batch_scan.py
```

### 3) 每日報告 (v8.0 模組化架構)
檔案：`rpi_main.py` (orchestrator) + 三大模組

**架構：**
```
rpi_main.py          ← 主流程 (排程/通知/存檔)
  ├─ news_scraper.py      ← 多來源新聞抓取 + 內文摘要 + 去重
  ├─ market_data.py       ← 台股/美股/VIX/匯率/法人/融資融券
  └─ report_generator.py  ← 兩步 AI pipeline (篩選→生成)
```

**新聞抓取 (`news_scraper.py`)：**
- 台股：鉅亨、MoneyDJ、Yahoo財經、工商時報、經濟日報
- 美股：CNBC
- 自動抓取新聞內文前 500 字（不再只有標題）
- 標題相似度去重（避免重複報導浪費 token）

**市場數據 (`market_data.py`)：**
- 台股加權指數 + 證交所成交值
- 美股四大指數（S&P500、道瓊、那斯達克、費半）+ VIX
- USD/TWD 匯率
- 盤後：三大法人買賣超、融資融券餘額

**AI 報告 (`report_generator.py`)：**
- Step 1：AI 從大量新聞中篩選 8-12 則最重要的，標註影響分數與 watchlist 關聯
- Step 2：根據篩選結果 + 市場數據生成最終報告
- 盤前/盤後使用不同模板（盤前看開盤策略、盤後看回顧與明日展望）
- Groq 優先，Gemini 備援

**通知 + 存檔：**
- 推送 LINE + Telegram
- 寫入 Google Sheets

執行：
```bash
python rpi_main.py
```

### 4) 盤中偵察
檔案：`rpi_intraday.py`

- 盤中監控股票清單
- 當價格/量能/RSI 觸發條件即通知
- LINE + Telegram 即時推送
- Telegram 指令動態調整清單

Telegram 指令：
- `/add 2330,2317`
- `/del 2330`
- `/list`
- `/help`

執行：
```bash
python rpi_intraday.py
```

systemd 常駐：
```bash
sudo cp pi_intraday.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi_intraday
```

### 5) 手機 App (Option 1: 後端常駐 + App 控制)
檔案：`api_server.py`

- App 不直接跑 Python；Python 繼續跑在樹莓派/主機上
- App 透過 HTTP API 管理 watchlist / 讀取盤中訊號紀錄

環境變數：
- `APP_API_KEY`：App 呼叫 API 用的金鑰 (請勿放進公開 repo)

啟動 API：
```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

主要 API：
- `GET /health`
- `GET /watchlist` (Header: `X-API-Key`)
- `PUT /watchlist` (Body: `{ "codes": ["2330"] }`)
- `POST /watchlist/add`
- `POST /watchlist/del`
- `GET /alerts?limit=100`
- `POST /notify/test` (測試 Telegram)

## 資料檔案

- `stock_database.json`：每日掃描結果
- `watchlist.json`：盤中監控清單（自動建立）
- Google Sheets `watchlist` 工作表：盤中監控清單（雲端同步）

## 環境變數

請先建立 `.env`：
```bash
cp .env.example .env
```

主要項目：
- `GROQ_API_KEY`, `GEMINI_API_KEY`
- `LINE_CHANNEL_TOKEN`, `LINE_TARGET_ID`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `SPREADSHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE`
- `APP_API_KEY` (Option 1: 手機 App API)

Streamlit Cloud 需要在 Secrets 設定：
- `WATCHLIST_SPREADSHEET_ID`
- `gcp_service_account` (JSON 內容)

盤中參數：
- `WATCHLIST_CODES`
- `WATCHLIST_SHEET_NAME`
- `WATCHLIST_SPREADSHEET_ID`
- `INTRADAY_CHECK_INTERVAL_SEC`
- `INTRADAY_PRICE_UP_PCT` / `INTRADAY_PRICE_DOWN_PCT`
- `INTRADAY_RSI_OVERBOUGHT` / `INTRADAY_RSI_OVERSOLD`
- `INTRADAY_VOLUME_SPIKE_MULT`
- `INTRADAY_ALERT_COOLDOWN_MIN`
- `INTRADAY_TG_POLL_SEC`

## 通知機制

- LINE + Telegram 皆支援
- LINE 額度用完時，Telegram 仍可正常接收

## 補充說明

- Yahoo 報價為延遲資料，適合 MVP 監控
- 要即時行情可再接券商或付費 API
