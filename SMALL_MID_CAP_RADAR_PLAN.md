# 中小型優質股雷達計畫

建立日期：2026-06-04

## 目標

新增一條專門尋找「價格與市值不過熱、但體質與量價結構轉強」的中小型台股候選來源。這個功能不是直接買進建議，而是把潛在超額報酬標的放進優先觀察與回測流程。

## 可行性判斷

可行性：高。  
原因：
- 台股上市櫃行情、成交值、估值、法人、融資券與月營收多數有公開資料可取。
- 現有專案已經有 snapshot、報告、Dashboard、signal history 與 performance tracker。
- 中小型股可以用獨立分數進入候選池，不需要重寫原本權值股主軸判斷。

主要風險：
- 中小型股流動性差，容易出現滑價與假突破。
- 估值便宜可能是價值陷阱，需要搭配營收、量價與主題確認。
- Yahoo / TWSE / TPEx 資料欄位不穩時，要明確標示資料品質。

## v2 現行定義（shadow mode）

「不貴」不只看股價，v1 同時看：
- 股價：理想低於 200 元，硬上限 500 元。
- 市值：理想 50 億到 800 億台幣，超過 2500 億排除。
- 流動性：20 日均成交值至少 3000 萬，低於此值排除。
- 估值：PER、PBR、殖利率若合理則加分。
- 技術面：站上 MA20 / MA60、MA20 > MA60、RSI 不過熱、量比放大。
- 題材面：新聞命中只作研究欄位，不直接加進總分。

## 分數模型

總分 100：
- 品質分數 30%：20 日動能、成交值、市值、PE 合理、波動不過高；低股價不再視為品質。
- 估值分數 25%：市值區間、PER、PBR、殖利率。
- 流動性分數 20%：20 日均成交值。
- 技術分數 25%：MA20、MA60、趨勢、RSI、量比、波動。

分層：
- 78 分以上：高信心觀察。
- 65 到 77 分：中信心追蹤。
- 65 分以下：只列備選或不推進主候選。

## 已實作 v2

- 新增 `small_mid_cap_radar.py`。
- snapshot 新增 `small_mid_candidates`。
- `small_mid_candidates` 固定為 `candidate_channel=shadow`，不推進 `tw_candidates`。
- 手機盤前/盤後摘要不顯示雷達，避免被誤解為主推名單。
- Dashboard 新增「中小雷達」頁籤。
- 單元測試覆蓋評分、流動性排除、shadow 隔離與報告精簡。

## 環境變數

- `ENABLE_SMALL_MID_RADAR=true`
- `SMALL_MID_SCAN_LIMIT=24`
- `SMALL_MID_LIMIT=8`
- `SMALL_MID_SHADOW_MODE=true`
- `SMALL_MID_PROMOTE_LIMIT=0`
- `SMALL_MID_CODES=...` 可覆蓋預設雷達股票池。
- `SMALL_MID_EXTRA_CODES=...` 可追加觀察名單。
- `SMALL_MID_MIN_TURNOVER_MILLION=30`
- `SMALL_MID_IDEAL_MAX_PRICE=200`
- `SMALL_MID_MAX_PRICE=500`
- `SMALL_MID_MARKET_CAP_MIN_BILLION=5`
- `SMALL_MID_MARKET_CAP_MAX_BILLION=80`
- `SMALL_MID_HARD_MARKET_CAP_MAX_BILLION=250`

## 回測計畫

雷達績效獨立追蹤，包含與正式帳本一致的進場規則與交易成本，但不混入 primary KPI。

評估：
- Top 3 / Top 5 / Top 8 中小雷達候選。
- 1 / 3 / 5 / 10 / 20 交易日後報酬。
- 相對加權指數與櫃買指數的超額報酬。
- 高信心 vs 中信心。
- 不同市值區間、成交值區間、PE 區間。
- 有新聞命中 vs 無新聞命中。
- 被推進主候選 vs 只在中小雷達頁籤。

保留條件：
- 10 個交易日平均超額報酬為正。
- Top 5 勝率高於原始候選股或回撤較小。
- 成交值不足組若表現差，應提高流動性門檻。

淘汰條件：
- 高分股大量來自低成交值股票。
- 高分股常在 RSI 過熱後隔日回落。
- 資料缺漏股命中率明顯較差。

## 下一步

1. 將 `small_mid_candidates` 寫入 `signal_history.jsonl`，讓績效可分來源統計。
2. 回測加入 `source=small_mid_radar` 分層。
3. 補 TPEx / TWSE 估值資料 fallback，降低 Yahoo fundamental 缺漏。
4. 加入月營收 YoY 與累計 YoY 作為品質分數。
5. 樣本達研究門檻後，另行輸出 shadow 雷達復盤；未通過前不 promotion。
