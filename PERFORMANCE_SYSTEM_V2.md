# 績效、研究與風控系統 v2

## 核心口徑

正式績效只接受同時符合以下條件的資料：

- `schema_version=2`
- `execution_environment=live`
- `candidate_channel=primary`
- `strategy_version=tw-entry-v1`（或當前環境變數指定版本）
- `run_type=scheduled|manual`

舊版無版本資料、`research`、`dry_run`、`backfill` 與中小雷達 `shadow` 資料都不會混入主 KPI。

每筆訊號包含穩定的 `signal_id`、`run_id`、`strategy_version`、`feature_version`、`entry_rule` 與特徵快照，績效資料以 `(signal_id, horizon)` 去重。

## 進出場與成本

- PRE：使用決策日第一個可交易開盤價。
- POST：嚴格使用下一個交易日開盤價；開盤價缺漏才標記並退回收盤價。
- 出場：進場後第 1 / 3 / 5 / 10 個交易日收盤價。

淨報酬使用現金流計算：買進金額加買進手續費與滑價，賣出金額扣賣出手續費、證交稅與滑價。預設假設為：

- 買賣手續費各 `0.1425%`（可依券商實際折扣覆寫）
- 股票賣出證交稅 `0.3%`
- 買賣滑價各 `0.05%`

證交所說明股票賣出稅率一般為 0.3%，券商手續費則由券商依成交金額自行訂定：[臺灣證券交易所手續費與交易稅表](https://www.twse.com.tw/zh/about/company/guide.html)。

環境變數：`BROKER_COMMISSION_RATE`、`BUY_COMMISSION_RATE`、`SELL_COMMISSION_RATE`、`STOCK_SELL_TAX_RATE`、`SLIPPAGE_RATE`、`BUY_SLIPPAGE_RATE`、`SELL_SLIPPAGE_RATE`。

## KPI

主要 KPI：指定持有天期的「扣成本後超額期望報酬」。

次要 KPI：淨平均報酬、超額勝率、勝率、profit factor、訊號日數。勝率不再單獨決定策略好壞。

最大回撤由「非重疊、等權 cohort」資金曲線計算：同一持有區間只投入一次資本，再按時間複利；不再用單筆最差報酬充當最大回撤。Dashboard 會顯示計算方法與資金曲線。

## 核心名單與雷達

- `tw_candidates`：`candidate_channel=primary`，可進正式績效。
- `small_mid_candidates`：`candidate_channel=shadow`，只記錄與評估。
- `SMALL_MID_SHADOW_MODE=true`，雷達不進主推名單、不進手機每日摘要、不影響主 KPI。

中小雷達的價格上限只作 universe / 風險篩選，不再被當成「品質」加分；新聞命中只保留為研究欄位，不直接增加雷達總分。

## 統一特徵與評分

`candidate_selector.py` 與 `stock_analyzer.py` 共用 `strategy_features.py`：

- MA20 / MA60 / MA120 距離與趨勢
- 5 / 20 / 60 日動能
- RSI、MACD、ATR、波動
- 相對大盤強弱
- 量比與 20 日均成交值
- 月營收（有資料時）

所有分數使用 `FEATURE_VERSION=tw-unified-features-v2`。動態市場清單以成交值與漲跌幅的 percentile rank 組合，不再相加不同量綱；主題分數採 Top 3 平均與標準化動能，`breadth` 只顯示、不加分。正式 primary 訊號只記錄「可分批布局」名單；提前雷達使用獨立的 `early_watch_history.jsonl` 與 `early_watch_performance.jsonl`，不混入正式 KPI。

## Logistic / ranking 研究基線

`strategy_model.py` 使用固定特徵、L2 logistic regression 與純 NumPy 實作，避免 Pi 新增大型依賴。驗證遵循時間順序：訓練集只含測試期之前且已完成出場的訊號，並保留 gap；做法對應 [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) 的時序原則。

機率校準只使用 out-of-fold 預測，避免拿模型訓練資料校準造成過度自信；原則參考 [scikit-learn 機率校準](https://scikit-learn.org/stable/modules/calibration.html)。

預設門檻：至少 120 筆、50 個訊號日、3 個有效 folds。達標後也只輸出 `shadow_rank` 與校準機率，`ready_for_selection` 固定為 false；正式採用必須建立新的 `strategy_version` 並人工審核。

系統固定單一 baseline、不做自動參數搜尋。多策略試驗尚未登錄前不宣稱已估計 PBO；過度調參風險依 [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) 管理。

## 投組風控

正式候選以等權假設計算：

- 單股權重
- 主題與產業集中度
- 相對 20 日均成交值的預估參與率
- 與前一正式快照相比的單向換手率
- 正式資金曲線最大回撤

限制由 `RISK_*` 環境變數設定；違規只會明確標示，不會在未經版本化研究下偷偷改動選股參數。

## DRY RUN

`DRY_RUN=true` 或 `EXECUTION_ENVIRONMENT=research` 只寫 `runtime/research_daily_candidates.json`，且不會：

- 更新正式 `runtime/daily_candidates.json`
- 寫入 `signal_history.jsonl` 或 `signal_performance.jsonl`
- 同步 Google Sheets
- 發送 Telegram / LINE

這個隔離由主流程與 `append_signal_history` 兩層共同防守。
