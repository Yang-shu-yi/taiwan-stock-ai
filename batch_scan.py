import os
import sys

print("="*30)
print("🚀 系統診斷模式啟動 (Debug Mode)")
print("="*30)

# ---------------------------------------
# 1. 檢查 Python 環境與套件
# ---------------------------------------
print("\n[Step 1] 檢查套件安裝狀態...")

packages = {
    "yfinance": "yfinance",
    "pandas": "pandas",
    "twstock": "twstock",
    "requests": "requests",  # 👈 重點檢查
    "ta": "ta",
    "groq": "groq"           # 👈 重點檢查
}

all_pass = True
for name, import_name in packages.items():
    try:
        __import__(import_name)
        print(f"✅ {name} ... 安裝成功")
    except ImportError as e:
        print(f"❌ {name} ... 失敗！找不到此套件 ({e})")
        all_pass = False

if not all_pass:
    print("\n⚠️ 結論：環境有缺漏，請檢查 requirements.txt 或 YAML 安裝步驟。")
    # 這裡不讓程式當機，繼續往下檢查其他項目
else:
    print("\n✅ 結論：所有套件安裝正確！")

# ---------------------------------------
# 2. 檢查 GitHub Secrets (環境變數)
# ---------------------------------------
print("\n[Step 2] 檢查金鑰設定 (Secrets)...")

keys = [
    "GROQ_API_KEY",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_USER_ID",
    "WEB_APP_URL"
]

secrets_pass = True
for k in keys:
    val = os.environ.get(k)
    if val:
        # 為了安全，只印出前3碼，後面打碼
        masked = val[:3] + "****" + val[-2:] if len(val) > 5 else "****"
        print(f"✅ {k} ... 讀取成功 ({masked})")
    else:
        print(f"❌ {k} ... 讀取失敗！(是 None)")
        secrets_pass = False

if not secrets_pass:
    print("\n⚠️ 結論：GitHub Secrets 沒抓到。可能是 YAML 的 env: 縮排寫錯了。")
else:
    print("\n✅ 結論：金鑰設定看起來很完美！")

# ---------------------------------------
# 3. 測試網路連線 (Google)
# ---------------------------------------
print("\n[Step 3] 測試外部網路連線...")
try:
    import requests
    r = requests.get("https://www.google.com", timeout=5)
    print(f"✅ Google 連線成功 (Status: {r.status_code})")
except Exception as e:
    print(f"❌ 網路連線失敗: {e}")

print("\n" + "="*30)
print("🏁 診斷結束")
print("="*30)

# 故意讓程式正常結束，這樣你會看到綠色勾勾，但重點是看 Log
sys.exit(0)