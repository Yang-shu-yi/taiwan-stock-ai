# Taiwan Stock AI 迭代優化與回測計畫

建立日期：2026-06-03  
目標：把每次錯誤、修正、回測結果、實盤觀察都留下可追蹤紀錄，透過反覆測試找出最適合台股盤前/盤後報告與候選股篩選的做法。

## 核心原則

1. 先記錄，再修改：任何策略、資料源、通知流程、Dashboard 改動，都要先寫下問題、假設與驗證方式。
2. 回測與正式執行分開：本地與 GitHub Actions 只做測試/dry-run，Pi 才是正式盤前/盤後/盤中通知來源。
3. 策略與報告同源：盤前報告、盤後復盤、Dashboard、訊號成效必須使用同一份 runtime snapshot，避免不同模組各講各的。
4. 只採用可驗證改善：不能只看單日表現，至少用 1/3/5/10 交易日、相對大盤報酬、命中率、失效條件一起評估。
5. 不照抄大型框架：參考優秀 GitHub 專案的架構思想，但保留本專案輕量、台股導向、Pi 可穩定執行的特性。

## 目前已知問題紀錄

| ID | 類型 | 問題 | 影響 | 優先級 | 初步處理方向 |
| --- | --- | --- | --- | --- | --- |
| I-001 | 發布 | 本機與 Pi 已有修復 commit，但 GitHub push 仍受權限阻擋 | GitHub Actions、Streamlit Cloud 可能不是最新版本 | P0 | 先修 GitHub 認證或改用正確帳號/SSH key，再 push |
| I-002 | 資料品質 | 三大法人 fallback 可能拿到前一交易日資料 | 盤後報告容易把舊資料看成當日資料 | P0 | 報告明確標示 `前一交易日`、`fallback_used`、`as_of` |
| I-003 | 資料品質 | 融資券仍可能顯示 `N/A` | 少掉籌碼風險判斷 | P0 | 修 TWSE 中文欄位 parser，補測試 fixture |
| I-004 | 資料來源 | TWSE market snapshot 來源失敗時動態股票池會退化 | 候選股可能過度依賴固定清單 | P0 | 找可穩定替代來源或加入多來源 fallback |
| I-005 | 通知 | LINE 429 曾讓每日流程失敗 | Telegram 可能已成功但整體仍被判失敗 | P1 | 通知通道獨立回報，LINE 加 retry/backoff，不讓單一通道拖垮流程 |
| I-006 | 報告品質 | data status 在報告中不夠明確 | 使用者不知道資料是否過期、fallback 或 N/A | P1 | 盤前/盤後報告加「資料狀態」短段落 |
| I-007 | 測試資料 | 本機 runtime 舊快照仍有亂碼風險 | 容易誤判報告格式已正常 | P1 | runtime 不提交，但 fixture 必須 UTF-8 且固定快照測試 |
| I-008 | 訊號評估 | 現有 signal performance 有統計，但還不足以解釋為何有效/失效 | 很難迭代策略權重 | P1 | 每次策略改動新增 experiment id，回測輸出按主題/市況/排名分層 |
| I-009 | 盤前決策 | 開高/開低/平盤劇本已有概念，但還缺歷史驗證 | 劇本可能看起來合理但未必有效 | P2 | 建立 premarket scenario backtest，比對隔日開盤與收盤表現 |
| I-010 | 監控 | Google Sheets 在 Pi 上目前停用 | 缺少長期外部觀察表 | P2 | 若要保留，補 Pi service account；否則正式標示停用 |

## GitHub 優秀專案參考方向

| 參考專案 | 可學的地方 | 不直接照抄的原因 | 本專案落地方式 |
| --- | --- | --- | --- |
| OpenBB | 資料整合後可供 CLI、Python、Dashboard 多端使用，重視資料供應商與介面分離 | 架構太大，不適合直接搬進 Pi 輕量專案 | 建立統一 data layer，所有報告與 Dashboard 都讀同一份資料狀態 |
| Microsoft Qlib | 研究、資料處理、模型、回測、紀錄流程完整 | 偏大型量化研究平台，部署成本高 | 學它的 experiment recorder：每次策略改動都留下參數與結果 |
| QuantConnect Lean | 回測與 live execution 共享策略邏輯，事件驅動清楚 | C#/Python 大型交易引擎，不適合本專案目前規模 | 策略函式與正式報告共用同一套 scoring code，避免回測/實盤不同 |
| Backtrader | 策略、指標、analyzer 可重用，適合快速驗證交易邏輯 | 本專案目前不是下單系統，不需要完整 broker/order 模型 | 可借用 analyzer 思路，先做訊號成效分析，不做交易撮合 |
| vectorbt | 大量參數與股票的向量化回測速度快 | 容易變成只追求參數最佳化，增加過擬合風險 | 用於快速掃描策略權重，但必須搭配 out-of-sample 與 walk-forward |
| FinRL-X | 資料、策略、回測、風控、執行一致化，強調 production consistency | AI/RL 投組系統太重，且本專案先不做自動交易 | 參考「同一權重/訊號介面」概念，讓候選股、主題、風險都可量化 |

參考連結：
- OpenBB: https://github.com/OpenBB-finance/OpenBB
- Qlib: https://github.com/microsoft/qlib
- QuantConnect Lean: https://github.com/QuantConnect/Lean
- Backtrader: https://www.backtrader.com/
- vectorbt: https://github.com/polakowo/vectorbt
- FinRL-X: https://github.com/AI4Finance-Foundation/FinRL-Trading

## 迭代流程

每一次優化都依照以下流程執行：

1. 新增錯誤/改善項目：記錄問題、影響範圍、資料證據、優先級。
2. 提出假設：說明預期改善什麼，例如勝率、超額報酬、資料完整率、通知成功率。
3. 參考範例：列出參考專案或策略文章，只吸收架構與驗證方法。
4. 小步實作：一次只改一個主題，例如資料 fallback、候選股權重、新聞清理或通知重試。
5. 本地測試：`python -m py_compile`、`python -m pytest`、dry-run。
6. 回測驗證：用固定歷史區間產生 1/3/5/10D 表現、相對大盤、Top3/Top5、主題命中率。
7. Pi dry-run：確認 Pi 環境、runtime artifact、crontab、service 狀態。
8. 正式觀察：至少觀察 5 個交易日，將結果寫入實驗紀錄。
9. 決策：保留、調整、回退或延長觀察。

## 回測設計 v1

第一版只做「訊號回測」，不做真實持倉、手續費、滑價、資金曲線。

### 輸入資料

- 每日候選股：`signal_history.jsonl`
- 後續價格：Yahoo Finance / TWSE fallback
- 大盤基準：加權指數 `^TWII`
- 主題與理由：候選股產生時的 `theme`、`reasons`、`confidence`、`invalidations`

### 評估指標

- 1/3/5/10 交易日報酬
- 相對大盤超額報酬
- 勝率與超額勝率
- Top 3 / Top 5 命中率
- 主題命中率
- 高信心 vs 中信心分層
- 失效條件是否被觸發
- 資料品質差時的表現差異

### 防止自欺的規則

- 不用未來資料產生當日候選股。
- 每次改權重都要有 experiment id。
- 不只看總平均，要看不同市況：開高、開低、平盤、強勢盤、弱勢盤。
- 不能用單日爆漲個股掩蓋整體表現。
- 若資料來源 stale 或 fallback，要分開統計。

## 實驗紀錄格式

每次策略改動新增一筆：

```text
Experiment ID:
日期:
改動範圍:
問題 ID:
假設:
參考來源:
回測區間:
主要結果:
失敗案例:
是否部署到 Pi:
正式觀察結果:
決策:
```

## 第一輪執行清單

### Round 1：先修資料可信度與報告透明度

- [ ] 修 GitHub push 權限，讓 origin/main 與 Pi、本機一致。
- [x] 報告中顯示資料狀態：fallback、前一交易日、N/A、來源失敗。
- [ ] 修三大法人日期標示，不把前一交易日資料寫成今日。
- [x] 修融資券 TWSE 中文欄位解析。
- [ ] 修 TWSE market snapshot fallback，恢復動態股票池品質。
- [ ] 新增 fixture：法人 fallback、融資券中文欄位、market snapshot 失敗降級。

### Round 2：通知與排程穩定性

- [x] LINE 429 加 retry/backoff。
- [x] Telegram 與 LINE 發送結果分開紀錄，單一通道失敗不讓整個流程失敗。
- [ ] Pi cron log 解析成簡單健康檢查摘要。
- [ ] Dashboard 顯示最近一次盤前/盤後與盤中 service 狀態。

### Round 3：策略回測與實驗紀錄

- [ ] 新增 `experiment_id` 到 signal history / performance。
- [ ] 新增策略參數快照，紀錄每次權重版本。
- [ ] 建立回測報告 markdown，自動列出改善與退步項目。
- [ ] 將開高/開低/平盤劇本納入回測分層。
- [ ] 每 5 個交易日產出一次策略復盤。

### Round 4：Dashboard 決策視覺化

- [ ] 新增資料品質頁籤。
- [ ] 新增訊號成效頁籤強化版：主題、排名、信心、資料狀態分層。
- [ ] 新增策略實驗頁籤，顯示各 experiment 表現。
- [ ] 股票查詢頁補上「同族群比較」與「風險失效條件」。

## 已開始執行

2026-06-03：
- 建立本計畫文件。
- 初步盤點本機 repo 狀態：本機 `main` 仍 ahead `origin/main` 1 commit，GitHub 尚未同步最新修復。
- 初步盤點 runtime 風險：本機 `runtime/daily_candidates.json` 仍可能是舊亂碼快照，正式資料應以 Pi runtime 為準。
- 初步確認後續第一優先：資料可信度、報告資料狀態、GitHub 發布權限、通知通道降級。
- 已實作報告資料狀態顯示：可標示來源失敗、快取、備援、交易日不一致。
- 已修融資券 parser：支援 TWSE 中文欄位如 `融資今日餘額`、`融券今日餘額`。
- 已調整通知分流：LINE 429 會 retry/backoff，Telegram 成功時不會被 LINE 失敗拖垮。
- 已新增測試：報告資料狀態、融資券中文欄位、通知分通道失敗處理。
- 驗證：`python -m py_compile` 通過，`python -m pytest` 15 tests passed，`DRY_RUN=true MODE=POST python rpi_main.py` 完成。
- dry-run 仍顯示 `twse_market_snapshot` 來源失敗，下一步優先修 fallback。

## 下一個最小可執行步驟

1. 修正並 push GitHub 權限問題。
2. 實作報告資料狀態顯示，讓使用者看到資料是否為 fallback 或前一交易日。
3. 修融資券 parser，補測試。
4. 修 LINE 429 不應拖垮 Telegram 與每日流程。
5. 跑本地測試、Pi dry-run，再進入 5 個交易日觀察期。
