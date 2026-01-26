# 樹莓派 (Raspberry Pi) 部署指南

本指南將幫助您將「台股操盤筆記機器人」部署到樹莓派上。

## 1. 準備工作

### 1.1 安裝 Python 環境
確保您的樹莓派已安裝 Python 3。
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

### 1.2 獲取程式碼
```bash
git clone https://github.com/Yang-shu-yi/taiwan-stock-ai.git
cd taiwan-stock-ai
```

### 1.3 建立虛擬環境並安裝依賴
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. 設定環境變數

### 2.1 建立 .env 檔案
參考 `.env.example` 建立 `.env`：
```bash
cp .env.example .env
nano .env
```
填入您的 API Key、LINE Token、Telegram ID 等資訊。

### 2.2 設定 Google Sheets (選填)
如果您需要存檔到 Google Sheets：
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。
2. 建立新專案，啟用 **Google Sheets API** 和 **Google Drive API**。
3. 建立 **服務帳戶 (Service Account)**，下載 JSON 金鑰檔案。
4. 將 JSON 檔案重新命名為 `service_account.json` 並放入專案目錄。
5. 打開您的 Google 試算表，點擊「共用」，將服務帳戶的 Email 加入，權限設為「編輯者」。

## 3. 測試執行
```bash
python3 rpi_main.py
```
檢查您的 LINE 和 Telegram 是否收到訊息。

### 3.1 盤中偵察 (選填)
盤中監控會持續運行，建議使用 tmux 或 systemd 常駐。
```bash
python3 rpi_intraday.py
```
可在 `.env` 設定：`WATCHLIST_CODES`、`INTRADAY_*` 相關參數。

### 3.2 Telegram 動態清單
在 Telegram 直接管理監控清單：
- `/add 2330,2317`
- `/del 2330`
- `/list`

清單會寫入 `watchlist.json`，立即生效。

## 4. 設定自動化排程 (Crontab)

我們可以使用 `cron` 來設定每天自動執行。

### 4.1 開啟 crontab 編輯器
```bash
crontab -e
```

### 4.2 加入排程
在檔案末尾加入以下內容 (請將路徑替換為你的使用者資料夾)：

```cron
# 每天早上 08:35 執行盤前快訊
35 8 * * 1-5 cd /home/pi/taiwan-stock-ai && /home/pi/taiwan-stock-ai/venv/bin/python rpi_main.py >> /home/pi/taiwan-stock-ai/cron_log.log 2>&1

# 每天下午 13:45 執行盤後法人筆記
45 13 * * 1-5 cd /home/pi/taiwan-stock-ai && /home/pi/taiwan-stock-ai/venv/bin/python rpi_main.py >> /home/pi/taiwan-stock-ai/cron_log.log 2>&1
```

*注意：`1-5` 表示週一至週五執行。*

## 5. systemd 常駐 (建議)
若要讓盤中偵察在開機後自動啟動，請使用 systemd：

```bash
sudo cp ~/taiwan-stock-ai/pi_intraday.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi-intraday
```

檢查狀態：
```bash
sudo systemctl status pi-intraday
```

停止/重新啟動：
```bash
sudo systemctl stop pi-intraday
sudo systemctl restart pi-intraday
```

## 6. 疑難排解
- **時區問題**：如果執行時間不對，請檢查樹莓派時區 (`sudo raspi-config` -> Localisation Options -> Timezone)。
- **日誌檢查**：查看 `cron_log.log` 了解報錯資訊。
