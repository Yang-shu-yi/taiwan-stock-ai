# Android 用戶端 (Option 1)

本專案的交易/監控邏輯跑在樹莓派/伺服器上。
這個 Android App 只是一個用戶端，用來：
- 讀取 `GET /alerts`
- 透過 `/watchlist` 相關 API 管理 `watchlist.json`

## 先決條件
- Android Studio
- 後端 API 已在主機上啟動：`uvicorn api_server:app --host 0.0.0.0 --port 8000`
- 在主機的 `.env` 設定好 `APP_API_KEY`

## 建立專案
1) Android Studio -> New Project -> Empty Activity (Jetpack Compose)
2) Min SDK：建議 26+
3) Package name 範例：`com.taiwanstock.client`

## 加入權限
在 `AndroidManifest.xml` 加上：

```
<uses-permission android:name="android.permission.INTERNET" />
```

如果你在區網呼叫 `http://`（非 https）URL，也要加上：

```
<application
  android:usesCleartextTraffic="true"
  ...>
```

## Copy Files
把以下資料夾內的檔案全部複製到你的 Android 專案：
- `android-client/app/src/main/java/` -> your project's `app/src/main/java/`

## Gradle 相依套件
在你的 `app/build.gradle(.kts)` 增加：

```
implementation("com.squareup.okhttp3:okhttp:4.12.0")
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
```

程式使用 `org.json`（Android 內建可用）。

## 執行
開啟 App -> Settings：
- Base URL：`http://<YOUR_PI_IP>:8000`
- API key：你的 `APP_API_KEY`
