# Raspberry Pi 部署說明

## 目標

Pi 端主要執行兩個流程：

- `rpi_main.py`：每天產生候選股快照與摘要
- `rpi_intraday.py`：盤中警示

報告類訊息要走專屬 report Telegram bot，並可同步 LINE；Codex 任務完成提醒仍使用 skill bot，不要混用。


## 安裝

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
git clone https://github.com/Yang-shu-yi/taiwan-stock-ai.git
cd taiwan-stock-ai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```


## 環境設定

```bash
cp .env.example .env
nano .env
```

至少建議設定：

- `ENABLE_REPORT_TELEGRAM=true`
- `ENABLE_LINE=true`
- `REPORT_DASHBOARD_URL=https://taiwan-stock-ai-cmignppyqbx3qyslpthtnz.streamlit.app/`
- `REPORT_TELEGRAM_BOT_TOKEN`
- `REPORT_TELEGRAM_CHAT_ID`
- `LINE_CHANNEL_TOKEN`
- `LINE_TARGET_ID`

注意：

- 報告類訊息只讀 `REPORT_TELEGRAM_*`
- 不再 fallback 到 `TELEGRAM_*`

可選設定：

- `SPREADSHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `MODE`
- `TW_SCAN_LIMIT`
- `TW_CANDIDATE_LIMIT`
- `ACTIONABLE_CANDIDATE_LIMIT`
- `EARLY_WATCH_LIMIT`
- `INTRADAY_FOCUS_LIMIT`
- `DRY_RUN=true`：本地驗證用，不改正式資料也不發送 Telegram / LINE
- `STRATEGY_VERSION=tw-entry-v1`
- `EXECUTION_ENVIRONMENT=live`
- `RUN_TYPE=scheduled`
- `BROKER_COMMISSION_RATE`：以實際券商費率覆寫
- `STOCK_SELL_TAX_RATE=0.003`
- `SMALL_MID_SHADOW_MODE=true`
- `ENABLE_DASHBOARD_PUBLISH=true`
- `BLOB_READ_WRITE_TOKEN`（Vercel Blob 寫入權杖，只放在 Pi `.env`）
- `DASHBOARD_BLOB_PATH=dashboard/latest.json`
- `LAST_VALID_SNAPSHOT_FILE=runtime/last_valid_daily_candidates.json`


## 執行

### 每日候選股流程

```bash
python3 rpi_main.py
```

先驗證不發送通知：

```bash
DRY_RUN=true python3 rpi_main.py
```

Dry run 只會寫 `runtime/research_daily_candidates.json`；正式快照、訊號歷史、績效、Google Sheets、Vercel Dashboard 與通知都不會改動。

盤後若 Yahoo 歷史日線尚未納入當日 K 棒，流程會用 TWSE／TPEX 官方日收盤行情覆蓋最新 OHLCV，再進行進場可行性與提前雷達評分。

正式盤前與盤後流程會在發送通知前，把同一份快照發布至 Vercel Blob。發布失敗會寫入 cron log，但不會阻止 Telegram／LINE 通知。

若本次行情來源無法產出至少 5 檔完整候選，報告會沿用 `LAST_VALID_SNAPSHOT_FILE` 的最近有效 Top 5，並清楚標示資料日期。這些 fallback 候選只供當日閱讀，不會寫入正式訊號績效。

### 盤中警示流程

```bash
python3 rpi_intraday.py
```


## systemd

### 盤中警示

```bash
sudo cp pi_intraday.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi_intraday
sudo systemctl status pi_intraday
```

Pi 狀態確認：

```bash
systemctl is-active pi_intraday
crontab -l
```

### 每日流程

每日流程目前可用 `cron` 或 GitHub Actions 觸發；如果要在 Pi 上本機排程，也可以直接加進 crontab。


## crontab 範例

```cron
# 平日開盤前
35 8 * * 1-5 cd /home/pi/taiwan-stock-ai && /home/pi/taiwan-stock-ai/venv/bin/python rpi_main.py >> /home/pi/taiwan-stock-ai/cron_log.log 2>&1

# 平日收盤後
45 13 * * 1-5 cd /home/pi/taiwan-stock-ai && /home/pi/taiwan-stock-ai/venv/bin/python rpi_main.py >> /home/pi/taiwan-stock-ai/cron_log.log 2>&1
```


## 注意事項

- 請先確認 Pi 的 timezone 正確
- 如果要同步 Google Sheets，`service_account.json` 不要提交到 repo
- `daily_candidates.json` 會包含 `data_status`，Dashboard 可直接看資料是否過期或降級
- 正式快照預設輸出到 `runtime/daily_candidates.json`，不再提交到 GitHub
- `signal_history.jsonl` 與 `signal_performance.jsonl` 是本機追蹤檔，不要提交到 repo
- v2 正式績效只讀 live / primary / 當前 strategy version；舊資料與 shadow 雷達不混算
- 完整成本、walk-forward 與風控口徑見 `PERFORMANCE_SYSTEM_V2.md`
- 重構後主流程已不再依賴手動 watchlist
