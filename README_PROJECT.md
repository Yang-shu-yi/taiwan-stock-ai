# Taiwan Stock AI 專案說明

## 專案定位

這個專案已重構為：

- 台股優先的候選股情報系統
- 美股作為市場脈絡補充
- Telegram / LINE 分流通知流程
- 盤前 / 盤中 / 盤後的自動化資訊推送
- 資料來源狀態、快取 freshness 與訊號成效追蹤
- 版本化 live/research 訊號、成本後績效與投組風控
- 趨勢強度與進場可行性分離，提供提前觀察、可分批布局、等待回測、過度延伸不追四段狀態

Streamlit 保留為唯讀戰情室，不再把手動 watchlist 當作主要使用方式。


## 目前主流程

### 1. 每日候選股快照

主入口：

```bash
python rpi_main.py
```

流程：

- 抓取台股 / 美股新聞
- 抓取市場資料
- 掃描台股核心股票池
- 建立 `daily_candidates.json`
- 寫入資料狀態與訊號紀錄
- 推送手機友善版 Telegram / LINE 摘要

輸出檔案：

- `runtime/daily_candidates.json`
- `signal_history.jsonl`
- `signal_performance.jsonl`
- `early_watch_history.jsonl`
- `early_watch_performance.jsonl`

正式 primary 績效只記錄「可分批布局」名單；提前雷達容許較多誤報，使用獨立帳本，不混入正式 KPI。

### 2. 盤中警示

主入口：

```bash
python rpi_intraday.py
```

流程：

- 讀取 `daily_candidates.json`
- 只監控台股候選清單中的重點股票
- 依價格、RSI、量比條件觸發 Telegram 警示
- 寫入 `alerts.jsonl`

### 3. 通知管道

目前建議設定：

- `ENABLE_REPORT_TELEGRAM=true`
- `ENABLE_LINE=true`
- `REPORT_DASHBOARD_URL=https://taiwan-stock-ai-cmignppyqbx3qyslpthtnz.streamlit.app/`

規則如下：

- 盤前 / 盤後 / 盤中報告：使用專屬 report Telegram bot，並可同步 LINE
- 任務完成提醒：使用 Codex skill 的提醒 bot

不要混用這兩個 bot。


## 核心模組

- `rpi_main.py`：每日候選股快照與摘要推送
- `rpi_intraday.py`：盤中警示主流程
- `candidate_selector.py`：候選股評分與快照產生
- `universe.py`：台股核心股票池與美股脈絡名單
- `message_formatter.py`：手機友善的訊息格式
- `notifier.py`：Telegram / LINE 通知封裝
- `market_data.py`：市場資料來源
- `daily_quote_overlay.py`：以 TWSE／TPEX 官方日收盤行情補齊當日 OHLCV，避免 Yahoo 日線尚未結算時誤判為舊資料
- `news_scraper.py`：新聞抓取與整理
- `alert_store.py`：盤中警示紀錄
- `data_layer.py`：資料快取、freshness 與來源狀態
- `signal_tracker.py`：候選股訊號紀錄與後續績效評估
- `strategy_contract.py`：訊號版本、執行環境、進場規則與交易成本契約
- `strategy_features.py`：候選選股與個股解析共用特徵/分數
- `company_assessment.py`：公司品質、官方相對估值、事件風險與白話行動判讀
- `entry_opportunity.py`：進場可行性、四段狀態、提前轉折與停損/風險報酬評估
- `strategy_model.py`：walk-forward logistic 與機率校準的 shadow baseline
- `portfolio_risk.py`：集中度、換手、流動性與回撤限制
- `config_check.py`：啟動前設定檢查


## 快速開始

1. 建立 `.env`

```bash
cp .env.example .env
```

2. 至少設定：

- `REPORT_TELEGRAM_BOT_TOKEN`
- `REPORT_TELEGRAM_CHAT_ID`
- `ENABLE_REPORT_TELEGRAM=true`
- `ENABLE_LINE=true`
- `LINE_CHANNEL_TOKEN`
- `LINE_TARGET_ID`
- `REPORT_DASHBOARD_URL`

3. 安裝依賴：

```bash
pip install -r requirements.txt
```

4. 執行每日流程：

```bash
python rpi_main.py
```

不發送通知、且不污染正式快照/績效的 dry-run：

```bash
DRY_RUN=true python rpi_main.py
```

績效 v2 的完整資料口徑、成本假設與研究門檻見 `PERFORMANCE_SYSTEM_V2.md`。

5. 執行盤中警示：

```bash
python rpi_intraday.py
```


## 目前產品方向

- 台股為主，美股為輔
- 不再涵蓋 crypto
- 不再以手動新增觀察股為主
- Streamlit 作為唯讀 Dashboard，顯示市場總覽、個股解析、資料狀態、訊號成效與報告預覽
- Pi 是正式盤前/盤後通知與 Dashboard Blob 快照來源；GitHub Actions 只跑測試與 dry-run，不發正式通知、不發布每日快照
- 正式報告固定提供 Top 5；即時評分不足 5 檔時沿用最近有效快照，fallback 名單不計入正式績效


## 舊功能處理

Streamlit、Android client、手動 watchlist API、舊版批次掃描腳本等已移入 `legacy/` 封存資料夾。
