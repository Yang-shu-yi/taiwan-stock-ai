# Legacy Archive

這個資料夾存放的是第一波重構後，不再屬於主產品流程的舊檔案。

目前封存的內容包含：

- Streamlit 介面相關檔案
- 舊版批次掃描腳本
- Android client
- 手動 watchlist / App API 相關檔案
- 舊版長篇 AI 報告流程
- 舊版資料快照檔案

封存原則：

- 保留歷史參考
- 避免舊入口繼續干擾目前主流程
- 不作為目前部署與日常使用的依據

目前主流程請以專案根目錄下的下列檔案為準：

- `rpi_main.py`
- `rpi_intraday.py`
- `candidate_selector.py`
- `universe.py`
- `message_formatter.py`
- `notifier.py`
