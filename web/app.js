const config = window.TSAI_CONFIG || {};
const snapshotUrl = config.snapshotUrl || "/data/daily_candidates.json";
const stockIndexUrl = config.stockIndexUrl || "/data/tw_stock_index.json";

const els = {
  updatedAt: document.querySelector("#updated-at"),
  modeLabel: document.querySelector("#mode-label"),
  statusBanner: document.querySelector("#status-banner"),
  twPrice: document.querySelector("#tw-price"),
  twDelta: document.querySelector("#tw-delta"),
  fxRate: document.querySelector("#fx-rate"),
  fxDelta: document.querySelector("#fx-delta"),
  vixPrice: document.querySelector("#vix-price"),
  vixDelta: document.querySelector("#vix-delta"),
  instTotal: document.querySelector("#inst-total"),
  themeList: document.querySelector("#theme-list"),
  candidateList: document.querySelector("#candidate-list"),
  smallMidList: document.querySelector("#small-mid-list"),
  dataStatus: document.querySelector("#data-status"),
  performanceSummary: document.querySelector("#performance-summary"),
  reportText: document.querySelector("#report-text"),
  stockQuery: document.querySelector("#stock-query"),
  stockClear: document.querySelector("#stock-clear"),
  stockResults: document.querySelector("#stock-search-results"),
  stockIndexCount: document.querySelector("#stock-index-count"),
};

function fmt(value, fallback = "--") {
  return value === undefined || value === null || value === "" ? fallback : value;
}

function pct(value) {
  if (value === undefined || value === null || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function safe(value) {
  return String(fmt(value, ""))
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function candidateTitle(item) {
  const code = safe(item.code);
  const name = safe(item.name || item.stock_name || "未命名");
  return `${code} ${name}`;
}

async function loadJson(url, fallback) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch (error) {
    console.warn(`Failed to load ${url}`, error);
    return fallback;
  }
}

function setText(element, value) {
  if (element) element.textContent = value;
}

function renderMetric(snapshot) {
  const market = snapshot.market || {};
  const twIndex = market.tw_index || {};
  const forex = market.forex || {};
  const us = market.us_indices || {};
  const vix = us.VIX || {};
  const inst = market.institutional || {};

  setText(els.updatedAt, `上次更新：${fmt(snapshot.updated_at, "未知")}`);
  setText(els.modeLabel, `模式：${fmt(snapshot.mode, "N/A")}`);
  setText(els.twPrice, fmt(twIndex.price));
  setText(els.twDelta, `${fmt(twIndex.chg)} / ${fmt(twIndex.pct)}%`);
  setText(els.fxRate, fmt(forex.rate));
  setText(els.fxDelta, fmt(forex.chg));
  setText(els.vixPrice, fmt(vix.price));
  setText(els.vixDelta, `${fmt(vix.chg)} / ${fmt(vix.pct)}%`);
  setText(els.instTotal, fmt(inst.total));
}

function showStatusBanner(snapshot, stockIndex) {
  const issues = [];
  if (!snapshot || Object.keys(snapshot).length === 0) issues.push("每日快照讀取失敗");
  if (!stockIndex.length) issues.push("台股查詢索引讀取失敗");
  const stale = Object.values(snapshot.data_status || {}).filter((item) => item && item.stale_reason);
  if (stale.length) issues.push(`有 ${stale.length} 個資料源過期或使用快取`);
  if (!issues.length) {
    els.statusBanner.hidden = true;
    return;
  }
  els.statusBanner.hidden = false;
  els.statusBanner.textContent = `資料提醒：${issues.join("；")}`;
}

function renderThemes(snapshot) {
  const themes = snapshot.theme_summary || [];
  if (!themes.length) {
    els.themeList.innerHTML = `<div class="card">目前沒有主軸資料。</div>`;
    return;
  }
  els.themeList.innerHTML = themes
    .slice(0, 6)
    .map((theme) => {
      const leaders = Array.isArray(theme.leaders) ? theme.leaders.join("、") : fmt(theme.leaders, "");
      return `
        <article class="card">
          <div class="card-title">
            <span>${safe(theme.theme || "未分類")}</span>
            <span class="tag">${fmt(theme.score, "N/A")}</span>
          </div>
          <div class="card-meta">代表股：${safe(leaders || "無")}</div>
        </article>
      `;
    })
    .join("");
}

function renderCandidateCard(item, index) {
  const reasons = Array.isArray(item.reasons) ? item.reasons.slice(0, 3).join("、") : fmt(item.reasons, "");
  const risks = Array.isArray(item.risk_flags) ? item.risk_flags.slice(0, 2).join("、") : fmt(item.risk_flags, "");
  return `
    <article class="card">
      <div class="card-title">
        <span>${index + 1}. ${candidateTitle(item)}</span>
        <span class="tag">分數 ${fmt(item.score, "N/A")}</span>
      </div>
      <div class="card-meta">
        主題：${safe(item.theme || "未分類")}<br />
        價格：${fmt(item.price)} / 1日：${pct(item.pct_1d)} / 5日：${pct(item.pct_5d)}<br />
        理由：${safe(reasons || "無")}<br />
        風險：${safe(risks || "無")}
      </div>
    </article>
  `;
}

function renderCandidates(snapshot) {
  const candidates = snapshot.tw_candidates || [];
  els.candidateList.innerHTML = candidates.length
    ? candidates.slice(0, 8).map(renderCandidateCard).join("")
    : `<div class="card">目前沒有候選股資料。</div>`;

  const smallMid = snapshot.small_mid_candidates || [];
  els.smallMidList.innerHTML = smallMid.length
    ? smallMid.slice(0, 8).map(renderCandidateCard).join("")
    : `<div class="card">目前沒有中小型雷達資料。</div>`;
}

function renderDataStatus(snapshot) {
  const status = snapshot.data_status || {};
  const rows = Object.entries(status);
  if (!rows.length) {
    els.dataStatus.innerHTML = `<div class="card">尚無資料狀態。</div>`;
    return;
  }
  els.dataStatus.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>資料源</th>
          <th>狀態</th>
          <th>更新時間</th>
          <th>備註</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(([name, item]) => {
            const state = item.ok ? "正常" : "異常";
            const fallback = item.fallback_used ? "使用 fallback" : "";
            const stale = item.stale_reason ? `過期：${item.stale_reason}` : "";
            const error = item.error ? `錯誤：${item.error}` : "";
            return `
              <tr>
                <td>${safe(name)}</td>
                <td>${state}</td>
                <td>${safe(item.updated_at || item.as_of || "N/A")}</td>
                <td>${safe([fallback, stale, error].filter(Boolean).join("；") || "無")}</td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function renderPerformance(snapshot) {
  const perf = snapshot.performance_summary || {};
  const strategy = snapshot.strategy_optimization || {};
  const cards = [];

  cards.push(`
    <article class="card">
      <div class="card-title"><span>近期訊號數</span><span class="tag">${fmt(perf.count, 0)}</span></div>
      <div class="card-meta">
        平均報酬：${fmt(perf.avg_return, "N/A")}<br />
        勝率：${fmt(perf.win_rate, "N/A")}<br />
        相對大盤：${fmt(perf.avg_excess_return, "N/A")}
      </div>
    </article>
  `);

  if (strategy.summary || strategy.action) {
    cards.push(`
      <article class="card">
        <div class="card-title"><span>策略自我檢查</span><span class="tag">${safe(strategy.action || "review")}</span></div>
        <div class="card-meta">${safe(strategy.summary || "無摘要")}</div>
      </article>
    `);
  }

  els.performanceSummary.innerHTML = cards.join("");
}

function buildReportText(snapshot) {
  const market = snapshot.market || {};
  const twIndex = market.tw_index || {};
  const candidates = snapshot.tw_candidates || [];
  const names = candidates.slice(0, 5).map((item) => `${item.code} ${item.name}`).join("、");
  return [
    `模式：${fmt(snapshot.mode, "N/A")}`,
    `台股：${fmt(twIndex.price)} (${fmt(twIndex.pct)}%)`,
    `焦點候選：${names || "無"}`,
    `資料更新：${fmt(snapshot.updated_at, "未知")}`,
    "",
    "提醒：本頁為研究與觀察工具，不是保證獲利或下單建議。"
  ].join("\n");
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function buildStockPool(snapshot, stockIndex) {
  const pool = new Map();
  for (const stock of stockIndex) {
    if (!stock.code) continue;
    pool.set(stock.code, {
      code: stock.code,
      name: stock.name,
      market: stock.market,
      group: stock.group,
      type: stock.type,
      aliases: [stock.code, stock.name, stock.market, stock.group].map(normalizeText),
      candidate: null,
      smallMid: null,
    });
  }

  for (const item of snapshot.tw_candidates || []) {
    const code = String(item.code || "");
    if (!code) continue;
    const existing = pool.get(code) || { code, aliases: [] };
    existing.name = existing.name || item.name;
    existing.candidate = item;
    existing.aliases = [existing.code, existing.name, existing.market, existing.group].map(normalizeText);
    pool.set(code, existing);
  }

  for (const item of snapshot.small_mid_candidates || []) {
    const code = String(item.code || "");
    if (!code) continue;
    const existing = pool.get(code) || { code, aliases: [] };
    existing.name = existing.name || item.name;
    existing.smallMid = item;
    existing.aliases = [existing.code, existing.name, existing.market, existing.group].map(normalizeText);
    pool.set(code, existing);
  }

  return Array.from(pool.values()).sort((a, b) => a.code.localeCompare(b.code));
}

function matchStocks(pool, query) {
  const q = normalizeText(query);
  if (!q) {
    return pool
      .filter((item) => item.candidate || item.smallMid)
      .sort((a, b) => {
        const scoreA = Number(a.candidate?.score || a.smallMid?.score || 0);
        const scoreB = Number(b.candidate?.score || b.smallMid?.score || 0);
        return scoreB - scoreA;
      })
      .slice(0, 8);
  }
  return pool
    .filter((item) => item.aliases.some((alias) => alias.includes(q)))
    .sort((a, b) => {
      const aExact = a.code === q || normalizeText(a.name) === q ? 0 : 1;
      const bExact = b.code === q || normalizeText(b.name) === q ? 0 : 1;
      return aExact - bExact || a.code.localeCompare(b.code);
    })
    .slice(0, 12);
}

function renderStockSearchResults(results, query) {
  if (!results.length) {
    els.stockResults.innerHTML = `
      <div class="card">
        查無「${safe(query)}」。可確認代號或中文名稱；若是新上市櫃股票，需等股票索引更新。
      </div>
    `;
    return;
  }

  els.stockResults.innerHTML = results
    .map((item) => {
      const signal = item.candidate || item.smallMid;
      const status = signal
        ? `今日有納入觀察，分數 ${fmt(signal.score, "N/A")}，信心 ${fmt(signal.confidence, "N/A")}`
        : "目前未在今日候選名單，先列為一般查詢結果。";
      const reasons = Array.isArray(signal?.reasons) ? signal.reasons.slice(0, 3).join("、") : "";
      const invalidations = Array.isArray(signal?.invalidations) ? signal.invalidations.slice(0, 2).join("、") : "";
      return `
        <article class="card search-card">
          <div class="card-title">
            <span>${safe(item.code)} ${safe(item.name || "未命名")}</span>
            <span class="tag">${safe(item.group || item.market || "台股")}</span>
          </div>
          <div class="card-meta">
            市場：${safe(item.market || "N/A")} / 類型：${safe(item.type || "股票")}<br />
            狀態：${safe(status)}<br />
            ${signal ? `價格：${fmt(signal.price)} / 1日：${pct(signal.pct_1d)} / 5日：${pct(signal.pct_5d)}<br />` : ""}
            ${reasons ? `理由：${safe(reasons)}<br />` : ""}
            ${invalidations ? `失效條件：${safe(invalidations)}<br />` : ""}
            ${signal?.data_quality ? `資料品質：${safe(signal.data_quality)}` : "資料品質：僅股票索引，未納入今日快照分析"}
          </div>
        </article>
      `;
    })
    .join("");
}

function setupStockSearch(snapshot, stockIndex) {
  const pool = buildStockPool(snapshot, stockIndex);
  setText(els.stockIndexCount, `股票索引 ${stockIndex.length} 檔`);

  const update = () => {
    const query = els.stockQuery.value;
    renderStockSearchResults(matchStocks(pool, query), query || "今日候選");
  };

  els.stockQuery.addEventListener("input", update);
  els.stockClear.addEventListener("click", () => {
    els.stockQuery.value = "";
    update();
    els.stockQuery.focus();
  });
  update();
}

function render(snapshot, stockIndex) {
  renderMetric(snapshot);
  showStatusBanner(snapshot, stockIndex);
  renderThemes(snapshot);
  renderCandidates(snapshot);
  renderDataStatus(snapshot);
  renderPerformance(snapshot);
  setText(els.reportText, buildReportText(snapshot));
  setupStockSearch(snapshot, stockIndex);
}

async function main() {
  const [snapshot, stockIndex] = await Promise.all([
    loadJson(snapshotUrl, {}),
    loadJson(stockIndexUrl, []),
  ]);
  render(snapshot, Array.isArray(stockIndex) ? stockIndex : []);
}

main();
