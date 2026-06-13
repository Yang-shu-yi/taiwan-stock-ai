const config = window.TSAI_CONFIG || { snapshotUrl: "/data/daily_candidates.json" };

const $ = (selector) => document.querySelector(selector);

function fmt(value, fallback = "N/A") {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  return `${Number(value).toFixed(2)}%`;
}

function joinReasons(items, limit = 2) {
  return (items || []).slice(0, limit).join("、") || "訊號整體偏強";
}

function card(title, meta, tag) {
  return `
    <article class="card">
      <div class="card-title">
        <span>${title}</span>
        ${tag ? `<span class="tag">${tag}</span>` : ""}
      </div>
      <div class="card-meta">${meta}</div>
    </article>
  `;
}

async function loadSnapshot() {
  const response = await fetch(config.snapshotUrl, { cache: "no-store" });
  if (!response.ok) throw new Error(`Snapshot fetch failed: ${response.status}`);
  return response.json();
}

function renderHeader(snapshot) {
  $("#mode-pill").textContent = `模式 ${fmt(snapshot.mode)}`;
  $("#updated-pill").textContent = `更新時間 ${fmt(snapshot.updated_at)}`;
}

function renderStatus(snapshot) {
  const status = snapshot.data_status || {};
  const issues = Object.entries(status)
    .filter(([key]) => !key.startsWith("yahoo_") && !key.startsWith("twse_institutional_bfi82u_"))
    .filter(([, item]) => item && (!item.ok || item.cached || item.fallback_used || item.stale_reason))
    .slice(0, 4)
    .map(([key, item]) => `${key}: ${item.stale_reason || item.error || "降級"}`);

  const banner = $("#status-banner");
  if (issues.length) {
    banner.classList.add("warn");
    banner.textContent = `資料提醒：${issues.join(" / ")}`;
  } else {
    banner.classList.remove("warn");
    banner.textContent = "資料狀態正常。";
  }
}

function renderMarket(snapshot) {
  const market = snapshot.market || {};
  const tw = market.tw_index || {};
  const forex = market.forex || {};
  const institutional = market.institutional || {};
  const performance = snapshot.performance_summary || {};
  const metrics = [
    ["台股加權", fmt(tw.price), `${fmt(tw.chg)} / ${fmt(tw.pct)}%`],
    ["成交值", fmt(tw.turnover), "市場熱度"],
    ["USD/TWD", fmt(forex.rate), fmt(forex.chg)],
    ["近期勝率", performance.win_rate == null ? "N/A" : `${Math.round(performance.win_rate * 100)}%`, `法人 ${fmt(institutional.total)}`],
  ];
  $("#market-metrics").innerHTML = metrics
    .map(([label, value, delta]) => `
      <div class="metric">
        <div class="metric-label">${label}</div>
        <div class="metric-value">${value}</div>
        <div class="metric-delta">${delta}</div>
      </div>
    `)
    .join("");
}

function renderThemes(snapshot) {
  const themes = snapshot.theme_summary || [];
  $("#themes").innerHTML = themes.length
    ? themes.map((item) => card(item.theme, `強度 ${item.score} / 代表股 ${(item.leaders || []).join("、")}`, "主軸")).join("")
    : card("尚無主軸", "等待下一次資料更新", "N/A");
}

function renderCandidates(snapshot) {
  const candidates = (snapshot.tw_candidates || []).slice(0, 8);
  $("#candidates").innerHTML = candidates.length
    ? candidates.map((item) => {
        const source = item.source === "small_mid_radar" ? "中小雷達" : item.theme || "核心";
        return card(
          `${item.code} ${item.name}`,
          `分數 ${item.score} / ${pct(item.pct_1d)} / ${joinReasons(item.reasons)}<br>失效：${joinReasons(item.invalidations, 1)}`,
          source,
        );
      }).join("")
    : card("尚無候選股", "等待下一次資料更新", "N/A");
}

function renderSmallMid(snapshot) {
  const rows = snapshot.small_mid_candidates || [];
  $("#small-mid-table").innerHTML = rows.length
    ? rows.map((item) => `
      <tr>
        <td>${fmt(item.small_mid_rank)}</td>
        <td><strong>${item.code} ${item.name}</strong><br>${fmt(item.theme)}</td>
        <td>${fmt(item.small_mid_score, item.score)}</td>
        <td>${item.market_cap_billion == null ? "N/A" : `${Number(item.market_cap_billion).toFixed(1)}B`}</td>
        <td>${item.avg_turnover_million == null ? "N/A" : `${Number(item.avg_turnover_million).toFixed(0)} 百萬`}</td>
        <td>${joinReasons(item.reasons, 3)}<br><span class="hint">${joinReasons(item.risk_flags, 1)}</span></td>
      </tr>
    `).join("")
    : `<tr><td colspan="6">尚未篩出符合條件的中小型股。</td></tr>`;
}

function renderStrategy(snapshot) {
  const opt = snapshot.strategy_optimization || {};
  const groups = opt.groups || {};
  const overall = groups.overall || {};
  const hints = opt.parameter_hints || {};
  const recommendations = opt.recommendations || [];
  $("#strategy").innerHTML = [
    card(
      opt.headline || "尚無策略自檢",
      `狀態：${opt.posture || "normal"} / 平均報酬 ${fmt(overall.avg_return_pct)}% / 勝率 ${overall.win_rate == null ? "N/A" : Math.round(overall.win_rate * 100) + "%"}`,
      "自檢",
    ),
    ...recommendations.slice(0, 3).map((item) => card(item, "策略建議，不會自動改權重", "建議")),
    Object.keys(hints).length ? card("參數提示", Object.entries(hints).map(([key, value]) => `${key}: ${value}`).join("<br>"), "Hints") : "",
  ].join("");
}

function renderDataStatus(snapshot) {
  const status = snapshot.data_status || {};
  const rows = Object.entries(status)
    .filter(([key]) => ["news", "twse_institutional", "twse_market_snapshot", "twse_margin", "twse_turnover"].includes(key))
    .map(([key, item]) => card(key, `狀態：${item.ok ? "正常" : "失敗"} / 交易日：${fmt(item.trading_date)}<br>${fmt(item.stale_reason || item.error, "")}`, item.fallback_used ? "備援" : ""));
  $("#data-status").innerHTML = rows.length ? rows.join("") : card("無資料狀態", "snapshot 未提供 data_status", "N/A");
}

function renderReportPreview(snapshot) {
  const candidates = (snapshot.tw_candidates || []).slice(0, 5).map((item, index) => `${index + 1}. ${item.code} ${item.name} / ${pct(item.pct_1d)} / 分數 ${item.score}`).join("\n");
  const small = (snapshot.small_mid_candidates || []).slice(0, 3).map((item, index) => `${index + 1}. ${item.code} ${item.name} / 分數 ${item.small_mid_score}`).join("\n");
  $("#report-preview").textContent = [
    `[${snapshot.mode === "PRE" ? "盤前可執行摘要" : "盤後可復盤報告"}]`,
    `台股: ${fmt(snapshot.market?.tw_index?.price)} (${fmt(snapshot.market?.tw_index?.pct)}%)`,
    "重點股:",
    candidates || "N/A",
    "中小雷達:",
    small || "N/A",
    `策略自檢: ${fmt(snapshot.strategy_optimization?.headline, "尚無")}`,
  ].join("\n");
}

function render(snapshot) {
  renderHeader(snapshot);
  renderStatus(snapshot);
  renderMarket(snapshot);
  renderThemes(snapshot);
  renderCandidates(snapshot);
  renderSmallMid(snapshot);
  renderStrategy(snapshot);
  renderDataStatus(snapshot);
  renderReportPreview(snapshot);
}

loadSnapshot()
  .then(render)
  .catch((error) => {
    const banner = $("#status-banner");
    banner.classList.add("warn");
    banner.textContent = `讀取資料失敗：${error.message}`;
  });
