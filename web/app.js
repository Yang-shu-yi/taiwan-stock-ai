const config = window.TSAI_CONFIG || {};
const snapshotUrl = config.snapshotUrl || "/data/daily_candidates.json";
const snapshotFallbackUrl = config.snapshotFallbackUrl || "/data/daily_candidates.json";
const stockIndexUrl = config.stockIndexUrl || "/data/tw_stock_index.json";
const stockAnalysisUrl = config.stockAnalysisUrl || "/api/stock-analysis";

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
  candidateFilter: document.querySelector("#candidate-filter"),
  actionableList: document.querySelector("#actionable-list"),
  earlyWatchList: document.querySelector("#early-watch-list"),
  smallMidList: document.querySelector("#small-mid-list"),
  dataStatus: document.querySelector("#data-status"),
  performanceSummary: document.querySelector("#performance-summary"),
  reportText: document.querySelector("#report-text"),
  stockQuery: document.querySelector("#stock-query"),
  stockClear: document.querySelector("#stock-clear"),
  stockResults: document.querySelector("#stock-search-results"),
  stockAnalysisReport: document.querySelector("#stock-analysis-report"),
  stockIndexCount: document.querySelector("#stock-index-count"),
};

let activeCandidateFilter = "all";

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

function parseTaipeiDate(value) {
  if (!value) return null;
  let normalized = String(value).trim().replace(" ", "T");
  if (!/[zZ]$|[+-]\d{2}:?\d{2}$/.test(normalized)) normalized += "+08:00";
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function snapshotAgeHours(snapshot) {
  const parsed = parseTaipeiDate(snapshot.generated_at || snapshot.updated_at);
  return parsed ? Math.max(0, (Date.now() - parsed.getTime()) / 3600000) : null;
}

function freshnessText(snapshot) {
  const hours = snapshotAgeHours(snapshot);
  if (hours === null) return "時間未知";
  if (hours < 1) return `${Math.max(0, Math.floor(hours * 60))} 分鐘前`;
  if (hours < 24) return `${Math.floor(hours)} 小時前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function shortDate(value) {
  const text = String(value || "");
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text.slice(5).replace("-", "/") : text;
}

function marketDataDate(snapshot) {
  return snapshot.market_data_date || snapshot.market?.tw_index?.trading_date || "";
}

function marketReference(snapshot) {
  const asOf = parseTaipeiDate(snapshot.market?.tw_index?.as_of);
  if (asOf) {
    return new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(asOf);
  }
  const date = marketDataDate(snapshot);
  return date ? `${shortDate(date)} 收盤` : "日期未知";
}

function candidateTitle(item) {
  const code = safe(item.code);
  const name = safe(item.name || item.stock_name || "未命名");
  return `${code} ${name}`;
}

function entryStatusLabel(item) {
  return item.entry_status_label || {
    early_watch: "提前觀察",
    scale_in: "可分批布局",
    wait_pullback: "等待回測",
    overextended: "過度延伸、不追",
  }[item.entry_status] || "等待確認";
}

function entryStatusClass(item) {
  return `status-${String(item.entry_status || "unknown").replaceAll("_", "-")}`;
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

async function loadSnapshot() {
  const primary = await loadJson(snapshotUrl, null);
  if (primary && Object.keys(primary).length) {
    primary.__source = "live";
    return primary;
  }
  const fallback = await loadJson(snapshotFallbackUrl, {});
  fallback.__source = "deployment-fallback";
  return fallback;
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

  setText(
    els.updatedAt,
    `資料產生：${fmt(snapshot.updated_at, "未知")}（${freshnessText(snapshot)}）`,
  );
  const modeText = snapshot.mode === "PRE" ? "盤前" : snapshot.mode === "POST" ? "盤後" : fmt(snapshot.mode, "N/A");
  setText(els.modeLabel, `報告：${modeText}｜行情 ${marketReference(snapshot)}`);
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
  if (snapshot.__source === "deployment-fallback") issues.push("即時快照讀取失敗，目前顯示部署備援資料");
  if (snapshot.candidate_provenance?.mode === "last_valid_snapshot") {
    issues.push(`候選名單沿用 ${shortDate(snapshot.candidate_provenance.as_of)} 最近有效快照`);
  }
  const ageHours = snapshotAgeHours(snapshot);
  if (ageHours !== null && ageHours > 72) issues.push(`快照已 ${Math.floor(ageHours / 24)} 天未更新`);
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
  const entryReasons = Array.isArray(item.entry_reasons) ? item.entry_reasons.slice(0, 2).join("、") : "";
  const plan = item.entry_plan || {};
  const status = entryStatusLabel(item);
  const light = scoreLight(item.score);
  return `
    <article class="card candidate-card ${entryStatusClass(item)}">
      <div class="card-title">
        <span>${index + 1}. ${candidateTitle(item)}</span>
        <span class="tag">${safe(status)}</span>
      </div>
      <div class="card-meta">
        <span class="score-light score-light-${light.key}">${light.icon} ${light.label}｜綜合 ${fmt(item.score, "N/A")}</span><br />
        主題：${safe(item.theme || "未分類")}<br />
        趨勢強度：${fmt(item.score, "N/A")} / 進場可行性：${fmt(item.entry_score, "N/A")}<br />
        價格：${fmt(item.price)} / 1日：${pct(item.pct_1d)} / 5日：${pct(item.pct_5d)}<br />
        判讀：${safe(item.entry_action || status)}<br />
        依據：${safe(entryReasons || reasons || "無")}<br />
        風險：${safe(risks || "無")}<br />
        ${plan.stop_price ? `規劃停損：${fmt(plan.stop_price)} / 風險報酬：${fmt(plan.reward_risk_ratio, "N/A")}<br />` : ""}
        資料：${safe(item.data_quality || item.price_date || "本次快照")}
      </div>
    </article>
  `;
}

function scoreLight(score) {
  const value = Number(score);
  if (Number.isFinite(value) && value >= 75) return { key: "green", icon: "🟢", label: "綠燈" };
  if (Number.isFinite(value) && value >= 55) return { key: "yellow", icon: "🟡", label: "黃燈" };
  return { key: "red", icon: "🔴", label: "紅燈" };
}

function setupCandidateFilter(snapshot) {
  if (!els.candidateFilter) return;
  const buttons = [...els.candidateFilter.querySelectorAll("[data-score-filter]")];
  for (const button of buttons) {
    const selected = button.dataset.scoreFilter === activeCandidateFilter;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.onclick = () => {
      activeCandidateFilter = button.dataset.scoreFilter || "all";
      renderCandidates(snapshot);
    };
  }
}

function renderCandidates(snapshot) {
  const candidates = snapshot.tw_candidates || [];
  const filteredCandidates = activeCandidateFilter === "all"
    ? candidates
    : candidates.filter((item) => scoreLight(item.score).key === activeCandidateFilter);
  els.candidateList.innerHTML = filteredCandidates.length
    ? filteredCandidates.slice(0, 8).map(renderCandidateCard).join("")
    : `<div class="card">目前沒有符合此燈號的候選股。</div>`;
  setupCandidateFilter(snapshot);

  const actionable = snapshot.actionable_candidates || [];
  els.actionableList.innerHTML = actionable.length
    ? actionable.slice(0, 5).map(renderCandidateCard).join("")
    : `<div class="card">今日沒有同時通過趨勢、停損距離與風險報酬門檻的股票；空手等待也是有效決策。</div>`;

  const earlyWatch = snapshot.early_watch_candidates || [];
  els.earlyWatchList.innerHTML = earlyWatch.length
    ? earlyWatch.slice(0, 5).map(renderCandidateCard).join("")
    : `<div class="card">目前沒有新的轉強型態進入提前雷達。</div>`;

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
  const earlyPerf = snapshot.early_watch_performance_summary || {};
  const strategy = snapshot.strategy_optimization || {};
  const cards = [];

  cards.push(`
    <article class="card">
      <div class="card-title"><span>正式績效樣本</span><span class="tag">${fmt(perf.count, 0)}</span></div>
      <div class="card-meta">
        訊號日：${fmt(perf.signal_dates, 0)}<br />
        扣成本超額期望：${pct(perf.net_excess_expectancy_pct)}<br />
        扣成本平均報酬：${pct(perf.net_avg_return_pct)}<br />
        勝率（次要）：${perf.win_rate === undefined || perf.win_rate === null ? "N/A" : `${(Number(perf.win_rate) * 100).toFixed(1)}%`}
      </div>
    </article>
  `);

  cards.push(`
    <article class="card">
      <div class="card-title"><span>提前雷達獨立樣本</span><span class="tag">${fmt(earlyPerf.count, 0)}</span></div>
      <div class="card-meta">
        訊號日：${fmt(earlyPerf.signal_dates, 0)}<br />
        扣成本超額期望：${pct(earlyPerf.net_excess_expectancy_pct)}<br />
        扣成本平均報酬：${pct(earlyPerf.net_avg_return_pct)}<br />
        狀態：${safe(earlyPerf.status || "collecting")}
      </div>
    </article>
  `);

  if (strategy.headline || strategy.primary_action) {
    cards.push(`
      <article class="card">
        <div class="card-title"><span>策略狀態</span><span class="tag">${safe(strategy.posture || "normal")}</span></div>
        <div class="card-meta">${safe(strategy.headline || "無摘要")}<br />${safe(strategy.primary_action || "")}</div>
      </article>
    `);
  }

  els.performanceSummary.innerHTML = cards.join("");
}

function buildReportText(snapshot) {
  const market = snapshot.market || {};
  const twIndex = market.tw_index || {};
  const candidates = (snapshot.actionable_candidates || []).length
    ? snapshot.actionable_candidates
    : (snapshot.tw_candidates || []);
  const names = candidates.slice(0, 3).map((item) => {
    return `${item.code} ${item.name}｜趨勢 ${fmt(item.score, "N/A")}｜進場 ${fmt(item.entry_score, "N/A")}｜${entryStatusLabel(item)}`;
  });
  const reportLabel = snapshot.mode === "PRE" ? "盤前觀察" : "盤後觀察";
  return [
    `${reportLabel}｜${shortDate(snapshot.report_date || String(snapshot.updated_at || "").slice(0, 10))}`,
    `行情基準：${marketReference(snapshot)}`,
    `台股：${fmt(twIndex.price)}（${pct(twIndex.pct)}）`,
    "行動分層：",
    ...(names.length ? names.map((name) => `• ${name}`) : ["• 無"]),
    `資料產生：${fmt(snapshot.updated_at, "未知")}（${freshnessText(snapshot)}）`,
    "",
    "提醒：本頁為研究與觀察工具，不是保證獲利或下單建議。"
  ].join("\n");
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function formatNumber(value, digits = 2, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return number.toLocaleString("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function scoreClass(score) {
  const value = Number(score);
  if (value >= 75) return "score-good";
  if (value >= 55) return "score-watch";
  return "score-risk";
}

function compactVolume(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (number >= 100000000) return `${formatNumber(number / 100000000, 2)} 億股`;
  if (number >= 10000) return `${formatNumber(number / 10000, 1)} 萬股`;
  return formatNumber(number, 0);
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
      actionable: null,
      earlyWatch: null,
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

  for (const item of snapshot.actionable_candidates || []) {
    const code = String(item.code || "");
    if (!code) continue;
    const existing = pool.get(code) || { code, aliases: [] };
    existing.name = existing.name || item.name;
    existing.actionable = item;
    existing.candidate = existing.candidate || item;
    existing.aliases = [existing.code, existing.name, existing.market, existing.group].map(normalizeText);
    pool.set(code, existing);
  }

  for (const item of snapshot.early_watch_candidates || []) {
    const code = String(item.code || "");
    if (!code) continue;
    const existing = pool.get(code) || { code, aliases: [] };
    existing.name = existing.name || item.name;
    existing.earlyWatch = item;
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
      .filter((item) => item.actionable || item.candidate || item.earlyWatch || item.smallMid)
      .sort((a, b) => {
        const scoreA = Number(a.actionable?.entry_score || a.candidate?.entry_score || a.earlyWatch?.early_watch_score || a.smallMid?.score || 0);
        const scoreB = Number(b.actionable?.entry_score || b.candidate?.entry_score || b.earlyWatch?.early_watch_score || b.smallMid?.score || 0);
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

function buildSvgChart(points) {
  const data = Array.isArray(points) ? points.filter((point) => Number.isFinite(Number(point.close))) : [];
  if (data.length < 2) return `<div class="chart-empty">價格資料不足，無法繪製走勢。</div>`;
  const width = 720;
  const height = 220;
  const padding = 18;
  const closes = data.map((point) => Number(point.close));
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const step = (width - padding * 2) / (data.length - 1);
  const coords = data.map((point, index) => {
    const x = padding + index * step;
    const y = height - padding - ((Number(point.close) - min) / range) * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = data.at(-1);
  const first = data[0];
  return `
    <svg class="price-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="近 120 日價格走勢">
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" />
      <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" />
      <polyline points="${coords.join(" ")}" />
      <circle cx="${coords.at(-1).split(",")[0]}" cy="${coords.at(-1).split(",")[1]}" r="4" />
      <text x="${padding}" y="16">${safe(first.date)} ${formatNumber(first.close)}</text>
      <text x="${width - padding}" y="16" text-anchor="end">${safe(last.date)} ${formatNumber(last.close)}</text>
      <text x="${padding}" y="${height - 4}">低 ${formatNumber(min)}</text>
      <text x="${width - padding}" y="${height - 4}" text-anchor="end">高 ${formatNumber(max)}</text>
    </svg>
  `;
}

function scoreBar(label, score, detail = "") {
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  return `
    <div class="score-row">
      <div class="score-row-head">
        <span>${safe(label)}</span>
        <strong>${formatNumber(value, 1)}</strong>
      </div>
      <div class="score-track"><span class="${scoreClass(value)}" style="width: ${value}%"></span></div>
      ${detail ? `<div class="score-detail">${safe(detail)}</div>` : ""}
    </div>
  `;
}

function optionalScoreBar(label, score, detail = "") {
  if (score === null || score === undefined || score === "") {
    return `
      <div class="score-row">
        <div class="score-row-head"><span>${safe(label)}</span><strong>N/A</strong></div>
        ${detail ? `<div class="score-detail">${safe(detail)}</div>` : ""}
      </div>
    `;
  }
  return scoreBar(label, score, detail);
}

function companyAssessment(signal, analysis = {}) {
  return signal?.company_assessment || analysis.company_assessment || {
    company_quality_score: signal?.company_quality_score ?? signal?.quality_score,
    valuation_attractiveness_score: signal?.valuation_attractiveness_score ?? signal?.valuation_score,
    entry_timing_score: signal?.entry_timing_score ?? signal?.entry_score,
    event_risk_level: signal?.event_risk_level,
    opportunity_label: signal?.opportunity_label,
    plain_language_advice: signal?.plain_language_advice,
    fundamental_summary: signal?.fundamental_summary,
    valuation_summary: signal?.valuation_summary,
  };
}

function metricTile(label, value, hint = "") {
  return `
    <article class="metric-tile">
      <span>${safe(label)}</span>
      <strong>${safe(value)}</strong>
      ${hint ? `<small>${safe(hint)}</small>` : ""}
    </article>
  `;
}

async function fetchStockAnalysis(code) {
  const response = await fetch(`${stockAnalysisUrl}?code=${encodeURIComponent(code)}`, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `${response.status} ${response.statusText}`);
  }
  return payload.analysis;
}

function renderSnapshotOnlyAnalysis(stock) {
  const signal = stock.actionable || stock.candidate || stock.earlyWatch || stock.smallMid;
  const title = `${stock.code} ${stock.name || "未命名"}`;
  if (!signal) {
    els.stockAnalysisReport.innerHTML = `
      <div class="analysis-empty">
        <strong>${safe(title)}</strong><br />
        目前只有股票索引資料，尚未進入今日候選或中小型雷達。若要判斷好壞，需要等待即時價格 API 或下一次 Pi 快照補齊技術資料。
      </div>
    `;
    return;
  }

  const reasons = Array.isArray(signal.reasons) ? signal.reasons : [];
  const risks = Array.isArray(signal.risk_flags) ? signal.risk_flags : [];
  const invalidations = Array.isArray(signal.invalidations) ? signal.invalidations : [];
  const assessment = companyAssessment(signal);
  els.stockAnalysisReport.innerHTML = `
    <article class="analysis-report">
      <div class="analysis-hero">
        <div>
          <p class="eyebrow">Snapshot Analysis</p>
          <h2>${safe(title)}</h2>
          <p class="hint">即時 API 暫不可用，以下使用每日快照中的候選股資料。</p>
        </div>
        <div class="verdict ${scoreClass(signal.score)}">
          <strong>${fmt(signal.score, "N/A")}</strong>
          <span>${safe(assessment.opportunity_label || entryStatusLabel(signal))}</span>
        </div>
      </div>
      <div class="analysis-grid">
        ${metricTile("價格", fmt(signal.price), "快照價")}
        ${metricTile("1 日", pct(signal.pct_1d), "短線變化")}
        ${metricTile("5 日", pct(signal.pct_5d), "一週動能")}
        ${metricTile("量比", fmt(signal.vol_ratio), "成交熱度")}
        ${metricTile("綜合分數", fmt(signal.score), "保留原燈號")}
        ${metricTile("進場可行性", fmt(signal.entry_score), entryStatusLabel(signal))}
        ${metricTile("公司品質", fmt(assessment.company_quality_score, "N/A"), "月營收品質基線")}
        ${metricTile("估值吸引力", fmt(assessment.valuation_attractiveness_score, "N/A"), "同業／市場相對排名")}
        ${metricTile("進場時機", fmt(assessment.entry_timing_score, "N/A"), "價格與風險報酬")}
        ${metricTile("事件風險", assessment.event_risk_level || "待確認", "新聞事件初篩")}
      </div>
      <div class="analysis-columns">
        <div>
          ${scoreBar("綜合分數", signal.score, "原有燈號與排名")}
          ${optionalScoreBar("公司品質", assessment.company_quality_score, "目前以月營收資料為基線")}
          ${optionalScoreBar("估值吸引力", assessment.valuation_attractiveness_score, "本益比、股價淨值比與殖利率相對排名")}
          ${optionalScoreBar("進場時機", assessment.entry_timing_score ?? signal.entry_score, "乖離、停損與風險報酬")}
        </div>
        <div class="analysis-note">
          <strong>${safe(assessment.opportunity_label || "持續觀察")}</strong>
          <p>${safe(assessment.plain_language_advice || "等待資料補齊後再判讀。")}</p>
          <strong>基本面白話判讀</strong>
          <p>${safe(assessment.fundamental_summary || "基本面資料不足。")}</p>
          <p>${safe(assessment.valuation_summary || "估值資料不足。")}</p>
          <strong>觀察理由</strong>
          <ul>${(reasons.length ? reasons : ["尚無理由"]).map((item) => `<li>${safe(item)}</li>`).join("")}</ul>
          <strong>風險與失效</strong>
          <ul>${[...risks, ...invalidations].slice(0, 5).map((item) => `<li>${safe(item)}</li>`).join("") || "<li>尚無風險提示</li>"}</ul>
        </div>
      </div>
    </article>
  `;
}

function renderStockAnalysis(stock, analysis) {
  const signal = stock.actionable || stock.candidate || stock.earlyWatch || stock.smallMid;
  const entry = signal || analysis.entry_opportunity || {};
  const metrics = analysis.metrics || {};
  const scores = analysis.scores || {};
  const title = `${stock.code} ${stock.name || "未命名"}`;
  const verdictLabel = entry.entry_status_label || (signal ? entryStatusLabel(signal) : (analysis.verdict?.label || "觀察"));
  const reasons = [...(analysis.reasons || []), ...(Array.isArray(signal?.reasons) ? signal.reasons.slice(0, 2) : [])];
  const risks = [...(analysis.risks || []), ...(Array.isArray(signal?.risk_flags) ? signal.risk_flags.slice(0, 2) : [])];
  const invalidations = Array.isArray(signal?.invalidations) ? signal.invalidations.slice(0, 3) : [];
  const assessment = companyAssessment(signal, analysis);

  els.stockAnalysisReport.innerHTML = `
    <article class="analysis-report">
      <div class="analysis-hero">
        <div>
          <p class="eyebrow">Stock Report</p>
          <h2>${safe(title)}</h2>
          <p class="hint">
            ${safe(stock.market || "台股")} / ${safe(stock.group || "未分類")} /
            來源：${safe(analysis.source || "Yahoo Finance")}
          </p>
        </div>
        <div class="verdict ${scoreClass(scores.overall)}">
          <strong>${formatNumber(scores.overall, 1)}</strong>
          <span>${safe(assessment.opportunity_label || verdictLabel)}</span>
        </div>
      </div>

      <div class="analysis-grid">
        ${metricTile("最新價", formatNumber(metrics.price), `1日 ${pct(metrics.return1d)}`)}
        ${metricTile("20 日", pct(metrics.return20d), `5日 ${pct(metrics.return5d)}`)}
        ${metricTile("RSI", formatNumber(metrics.rsi, 1), "14 日")}
        ${metricTile("量比", formatNumber(metrics.volumeRatio, 2), `量 ${compactVolume(metrics.volume)}`)}
        ${metricTile("MA20", formatNumber(metrics.sma20), metrics.price > metrics.sma20 ? "站上" : "跌破")}
        ${metricTile("MA60", formatNumber(metrics.sma60), metrics.price > metrics.sma60 ? "站上" : "跌破")}
        ${metricTile("52週區間", `${formatNumber(metrics.low52w)} - ${formatNumber(metrics.high52w)}`, "價格位置")}
        ${metricTile("最大回撤", pct(metrics.maxDrawdown), `波動 ${formatNumber(metrics.volatility, 1)}%`)}
        ${metricTile("公司品質", formatNumber(assessment.company_quality_score, 1), "月營收品質基線")}
        ${metricTile("估值吸引力", formatNumber(assessment.valuation_attractiveness_score, 1), "同業／市場相對排名")}
        ${metricTile("進場時機", formatNumber(assessment.entry_timing_score ?? entry.entry_score, 1), verdictLabel)}
        ${metricTile("事件風險", assessment.event_risk_level || "待確認", "新聞事件初篩")}
      </div>

      <div class="analysis-chart-card">
        <div class="card-title">
          <span>近 120 日價格走勢</span>
          <span class="tag">${safe(analysis.symbol || stock.code)}</span>
        </div>
        ${buildSvgChart(analysis.chart)}
      </div>

      <div class="analysis-columns">
        <div class="score-board">
          ${scoreBar("趨勢結構", scores.trend, "MA20、MA60 與 20 日報酬")}
          ${scoreBar("動能品質", scores.momentum, "RSI 與中短期漲幅")}
          ${scoreBar("量能熱度", scores.volume, "成交量相對近 20 日均量")}
          ${scoreBar("風險控管", scores.risk, "回撤、波動與過熱風險")}
          ${scoreBar("綜合品質", scores.quality, "四項分數平均")}
          ${entry.entry_score !== undefined ? scoreBar("進場可行性", entry.entry_score, "乖離、停損與風險報酬") : ""}
          ${optionalScoreBar("公司品質", assessment.company_quality_score, "目前以月營收資料為基線")}
          ${optionalScoreBar("估值吸引力", assessment.valuation_attractiveness_score, "官方估值相對排名")}
          ${optionalScoreBar("進場時機", assessment.entry_timing_score ?? entry.entry_score, "價格、乖離與風險報酬")}
        </div>
        <div class="analysis-note">
          <strong>${safe(assessment.opportunity_label || "持續觀察")}</strong>
          <p>${safe(assessment.plain_language_advice || "等待資料補齊後再判讀。")}</p>
          <strong>基本面白話判讀</strong>
          <p>${safe(assessment.fundamental_summary || "基本面資料不足。")}</p>
          <p>${safe(assessment.valuation_summary || "估值資料不足。")}</p>
          <strong>判讀重點</strong>
          <ul>${(reasons.length ? reasons.slice(0, 6) : ["尚無明確偏多理由"]).map((item) => `<li>${safe(item)}</li>`).join("")}</ul>
          <strong>風險與失效條件</strong>
          <ul>${[...risks, ...invalidations].slice(0, 7).map((item) => `<li>${safe(item)}</li>`).join("") || "<li>尚無明確失效條件，仍需留意大盤與成交量變化。</li>"}</ul>
        </div>
      </div>

      <p class="analysis-disclaimer">
        更新：${safe(analysis.updated_at || "N/A")}。此報告為研究與觀察工具，不是保證獲利或下單建議。
      </p>
    </article>
  `;
}

async function selectStockForAnalysis(stock) {
  const title = `${stock.code} ${stock.name || ""}`.trim();
  els.stockAnalysisReport.innerHTML = `<div class="analysis-empty">正在產生 ${safe(title)} 的個股分析報告...</div>`;
  try {
    const analysis = await fetchStockAnalysis(stock.code);
    renderStockAnalysis(stock, analysis);
  } catch (error) {
    console.warn("Stock analysis API failed", error);
    renderSnapshotOnlyAnalysis(stock);
  }
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
      const signal = item.actionable || item.candidate || item.earlyWatch || item.smallMid;
      const status = signal
        ? `今日有納入觀察，趨勢 ${fmt(signal.score, "N/A")}，進場 ${fmt(signal.entry_score, "N/A")}，${entryStatusLabel(signal)}`
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
          <button class="analysis-button" type="button" data-code="${safe(item.code)}">查看視覺分析</button>
        </article>
      `;
    })
    .join("");
}

function setupStockSearch(snapshot, stockIndex) {
  const pool = buildStockPool(snapshot, stockIndex);
  setText(els.stockIndexCount, `股票索引 ${stockIndex.length} 檔`);
  let currentResults = [];

  const update = () => {
    const query = els.stockQuery.value;
    currentResults = matchStocks(pool, query);
    renderStockSearchResults(currentResults, query || "今日候選");
  };

  els.stockQuery.addEventListener("input", update);
  els.stockQuery.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !currentResults.length) return;
    event.preventDefault();
    selectStockForAnalysis(currentResults[0]);
  });
  els.stockResults.addEventListener("click", (event) => {
    const button = event.target.closest("[data-code]");
    if (!button) return;
    const stock = pool.find((item) => item.code === button.dataset.code);
    if (stock) selectStockForAnalysis(stock);
  });
  els.stockClear.addEventListener("click", () => {
    els.stockQuery.value = "";
    update();
    els.stockQuery.focus();
    els.stockAnalysisReport.innerHTML = `<div class="analysis-empty">選擇一檔股票後，這裡會顯示個股視覺分析報告。</div>`;
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
    loadSnapshot(),
    loadJson(stockIndexUrl, []),
  ]);
  render(snapshot, Array.isArray(stockIndex) ? stockIndex : []);
}

main();
