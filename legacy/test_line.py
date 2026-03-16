import os
import requests
import json

print("="*30)
print("🚀 LINE 通訊測試程式啟動")
print("="*30)

# 1. 讀取環境變數
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID") # 這裡填的是你的 Group ID

# 2. 檢查變數是否讀取成功
print(f"檢查 ID 設定: {USER_ID}")
if not TOKEN:
    print("❌ 錯誤: 抓不到 Token！請檢查 Secrets 名稱是否為 LINE_CHANNEL_ACCESS_TOKEN")
    exit(1)
if not USER_ID:
    print("❌ 錯誤: 抓不到 ID！請檢查 Secrets 名稱是否為 LINE_USER_ID")
    exit(1)

# 3. 準備發送內容
url = "https://api.line.me/v2/bot/message/push"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}
payload = {
    "to": USER_ID,
    "messages": [
        {
            "type": "text",
            "text": "🎉 Python 連線測試成功！\n這是一條來自 GitHub Actions 的測試訊息。"
        }
    ]
}

# 4. 發送請求並印出詳細診斷
print("📨 正在發送請求給 LINE 伺服器...")
try:
    response = requests.post(url, headers=headers, json=payload)
    
    print("-" * 20)
    print(f"📡 HTTP 狀態碼: {response.status_code}")
    print(f"📄 回應內容: {response.text}")
    print("-" * 20)

    if response.status_code == 200:
        print("✅ 測試成功！你的群組應該要收到訊息了。")
    elif response.status_code == 400:
        print("❌ 格式錯誤 (400)：通常是 Group ID 填錯，或是 Token 無效。")
    elif response.status_code == 401:
        print("❌ 權限錯誤 (401)：Token 錯誤或過期。請確認 GitHub Secrets 的 Token 跟 GAS 用的是同一個。")
    elif response.status_code == 404:
        print("❌ 找不到對象 (404)：機器人可能被踢出群組，或是 ID 填錯。")
    else:
        print("❌ 未知錯誤：請檢查回應內容。")

except Exception as e:
    print(f"❌ 連線發生例外錯誤: {e}")