# Taiwan Stock AI 專案說明

## 專案定位

這個專案已重構為：

- 台股優先的候選股情報系統
- 美股作為市場脈絡補充
- Telegram-first 通知流程
- 盤前 / 盤中 / 盤後的自動化資訊推送

目前不再以 Streamlit dashboard 為主，也不再把手動 watchlist 當作主要使用方式。


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
- 推送簡潔版 Telegram 摘要

輸出檔案：

- `daily_candidates.json`

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
- `ENABLE_LINE=false`

規則如下：

- 盤前 / 盤後 / 盤中報告：使用專屬 report Telegram bot
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
- `news_scraper.py`：新聞抓取與整理
- `alert_store.py`：盤中警示紀錄


## 快速開始

1. 建立 `.env`

```bash
cp .env.example .env
```

2. 至少設定：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ENABLE_TELEGRAM=true`
- `ENABLE_LINE=false`

3. 安裝依賴：

```bash
pip install -r requirements.txt
```

4. 執行每日流程：

```bash
python rpi_main.py
```

5. 執行盤中警示：

```bash
python rpi_intraday.py
```


## 目前產品方向

- 台股為主，美股為輔
- 不再涵蓋 crypto
- 不再以手動新增觀察股為主
- 不再依賴 Streamlit 做日常使用


## 舊功能處理

Streamlit、Android client、手動 watchlist API、舊版批次掃描腳本等已移入 `legacy/` 封存資料夾。
