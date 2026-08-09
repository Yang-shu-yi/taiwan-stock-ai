const YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart";
const OFFICIAL_DATA_URLS = {
  TW: {
    valuation: "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
    revenue: "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
  },
  TWO: {
    valuation: "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
    revenue: "https://openapi.twse.com.tw/v1/opendata/t187ap05_P",
  },
};

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "s-maxage=900, stale-while-revalidate=1800");
  res.end(JSON.stringify(body));
}

function sanitizeCode(value) {
  const code = String(value || "").trim().replace(/\D/g, "");
  return /^\d{4,5}$/.test(code) ? code : "";
}

function average(values) {
  const valid = values.filter((value) => Number.isFinite(value));
  if (!valid.length) return null;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function sma(values, period) {
  if (values.length < period) return null;
  return average(values.slice(-period));
}

function pctChange(current, previous) {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function round(value, digits = 2) {
  if (!Number.isFinite(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(String(value).replaceAll(",", "").replace("%", ""));
  return Number.isFinite(number) ? number : null;
}

function linearScore(value, low, high) {
  if (!Number.isFinite(value) || low === high) return null;
  return clamp(((value - low) / (high - low)) * 100);
}

async function fetchOfficialJson(url) {
  const response = await fetch(url, {
    headers: { "User-Agent": "taiwan-stock-ai/1.0", Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Official data ${response.status}`);
  return response.json();
}

function percentileScore(value, peers, lowerIsBetter) {
  if (!Number.isFinite(value) || peers.length < 2) return null;
  const below = peers.filter((peer) => peer < value).length;
  const equal = peers.filter((peer) => peer === value).length;
  const percentile = ((below + equal * 0.5) / peers.length) * 100;
  return lowerIsBetter ? 100 - percentile : percentile;
}

function weightedAvailable(items) {
  const valid = items.filter(([score]) => Number.isFinite(score));
  if (!valid.length) return null;
  const totalWeight = valid.reduce((sum, [, weight]) => sum + weight, 0);
  return valid.reduce((sum, [score, weight]) => sum + score * weight, 0) / totalWeight;
}

async function fetchCompanyAssessmentData(code, market) {
  const urls = OFFICIAL_DATA_URLS[market];
  if (!urls) return { revenue: {}, valuation: {} };
  const [valuationResult, revenueResult] = await Promise.allSettled([
    fetchOfficialJson(urls.valuation),
    fetchOfficialJson(urls.revenue),
  ]);

  let valuation = {};
  if (valuationResult.status === "fulfilled" && Array.isArray(valuationResult.value)) {
    const rows = valuationResult.value;
    const codeField = market === "TW" ? "Code" : "SecuritiesCompanyCode";
    const peField = market === "TW" ? "PEratio" : "PriceEarningRatio";
    const pbField = market === "TW" ? "PBratio" : "PriceBookRatio";
    const yieldField = market === "TW" ? "DividendYield" : "YieldRatio";
    const row = rows.find((item) => String(item?.[codeField] || "").trim() === code);
    if (row) {
      const pe = numberOrNull(row[peField]);
      const pb = numberOrNull(row[pbField]);
      const dividendYield = numberOrNull(row[yieldField]);
      const positiveValues = (field) => rows
        .map((item) => numberOrNull(item?.[field]))
        .filter((value) => Number.isFinite(value) && value > 0);
      const score = weightedAvailable([
        [Number.isFinite(pe) && pe > 0 ? percentileScore(pe, positiveValues(peField), true) : null, 0.45],
        [Number.isFinite(pb) && pb > 0 ? percentileScore(pb, positiveValues(pbField), true) : null, 0.35],
        [Number.isFinite(dividendYield) && dividendYield >= 0 ? percentileScore(dividendYield, positiveValues(yieldField), false) : null, 0.20],
      ]);
      valuation = {
        pe_ratio: Number.isFinite(pe) && pe > 0 ? pe : null,
        pb_ratio: Number.isFinite(pb) && pb > 0 ? pb : null,
        dividend_yield_pct: Number.isFinite(dividendYield) && dividendYield >= 0 ? dividendYield : null,
        score: round(score, 1),
        comparison_basis: "同市場",
        source: market === "TW" ? "TWSE" : "TPEx",
      };
    }
  }

  let revenue = {};
  if (revenueResult.status === "fulfilled" && Array.isArray(revenueResult.value)) {
    const row = revenueResult.value.find((item) => String(item?.["公司代號"] || "").trim() === code);
    if (row) {
      revenue = {
        period: row["資料年月"] || "",
        yoy_pct: numberOrNull(row["營業收入-去年同月增減(%)"]),
        cumulative_yoy_pct: numberOrNull(row["累計營業收入-前期比較增減(%)"]),
        mom_pct: numberOrNull(row["營業收入-上月比較增減(%)"]),
      };
    }
  }
  return { revenue, valuation };
}

function buildCompanyAssessment(metrics, entry, revenue, valuation) {
  const qualityScore = weightedAvailable([
    [linearScore(revenue.yoy_pct, -20, 30), 0.45],
    [linearScore(revenue.cumulative_yoy_pct, -15, 25), 0.40],
    [linearScore(revenue.mom_pct, -15, 15), 0.15],
  ]);
  const valuationScore = numberOrNull(valuation.score);
  const timingScore = numberOrNull(entry.entry_score);

  const revenueParts = [];
  if (Number.isFinite(revenue.yoy_pct)) revenueParts.push(`最新月營收年增 ${revenue.yoy_pct >= 0 ? "+" : ""}${revenue.yoy_pct.toFixed(1)}%`);
  if (Number.isFinite(revenue.cumulative_yoy_pct)) revenueParts.push(`累計年增 ${revenue.cumulative_yoy_pct >= 0 ? "+" : ""}${revenue.cumulative_yoy_pct.toFixed(1)}%`);
  let revenueConclusion = "月營收資料不足，暫時不能判斷基本面是否改善。";
  if (revenueParts.length) {
    if (revenue.yoy_pct > 0 && revenue.cumulative_yoy_pct > 0) revenueConclusion = `${revenueParts.join("、")}；營收成長仍有延續。`;
    else if (revenue.yoy_pct < 0) revenueConclusion = `${revenueParts.join("、")}；最新單月營收轉弱，先確認是否只是淡旺季。`;
    else revenueConclusion = `${revenueParts.join("、")}；營收方向尚未形成一致訊號。`;
  }

  const valuationParts = [];
  if (Number.isFinite(valuation.pe_ratio)) valuationParts.push(`本益比 ${valuation.pe_ratio.toFixed(1)} 倍`);
  if (Number.isFinite(valuation.pb_ratio)) valuationParts.push(`股價淨值比 ${valuation.pb_ratio.toFixed(2)} 倍`);
  if (Number.isFinite(valuation.dividend_yield_pct)) valuationParts.push(`殖利率 ${valuation.dividend_yield_pct.toFixed(1)}%`);
  const valuationSummary = valuationParts.length
    ? `${valuationParts.join("、")}；吸引力分數採同市場相對排名，不代表絕對便宜。`
    : "官方估值資料不足，暫不判定便宜或昂貴。";

  let opportunityLabel = "持續觀察";
  let advice = "條件尚未同時到位；等待基本面、估值或價格訊號至少再改善一項。";
  if (!Number.isFinite(qualityScore) || !Number.isFinite(valuationScore)) {
    opportunityLabel = "資料不足";
    advice = "公司品質或估值資料尚未補齊；先維持觀察，不因技術反彈直接視為買點。";
  } else if (qualityScore < 45) {
    opportunityLabel = "基本面先保守";
    advice = "即使股價反彈也先當短線訊號；等月營收年增與累計年增回到正數，再重新評估。";
  } else if (qualityScore >= 70 && valuationScore >= 60 && timingScore < 55) {
    opportunityLabel = "優質回檔觀察";
    advice = `公司與估值條件較佳，但價格尚未止跌；先等股價站回 MA20 約 ${metrics.sma20.toFixed(2)}，且下次月營收年增未轉負，再考慮小量分批。`;
  } else if (qualityScore >= 70 && valuationScore < 45) {
    opportunityLabel = "好公司但估值偏高";
    advice = "基本面較佳，但目前相對市場不便宜；等待估值回到中間區間或獲利上修，不追價。";
  } else if (timingScore >= 65 && qualityScore >= 60) {
    opportunityLabel = "條件較完整";
    advice = "基本面、估值與進場條件沒有明顯衝突；若要分批，務必小量並遵守規劃停損。";
  } else if (timingScore < 55) {
    opportunityLabel = "等待止跌";
    advice = `目前不是追價訊號；先等股價站回 MA20 約 ${metrics.sma20.toFixed(2)}並確認量能回升，再重新評估。`;
  }

  return {
    company_quality_score: round(qualityScore, 1),
    company_quality_confidence: revenueParts.length >= 2 ? "中" : revenueParts.length ? "初步" : "不足",
    company_quality_basis: "目前以月營收作為品質基線",
    valuation_attractiveness_score: round(valuationScore, 1),
    entry_timing_score: timingScore,
    event_risk_level: "待確認",
    event_risk_summary: "即時個股查詢尚未取得完整公司事件，不能據此判定低風險。",
    opportunity_label: opportunityLabel,
    plain_language_advice: advice,
    fundamental_summary: revenueConclusion,
    valuation_summary: valuationSummary,
    valuation,
  };
}

function rsi(values, period = 14) {
  if (values.length <= period) return null;
  const changes = values.slice(1).map((value, index) => value - values[index]);
  const recent = changes.slice(-period);
  const gains = recent.map((change) => Math.max(change, 0));
  const losses = recent.map((change) => Math.max(-change, 0));
  const avgGain = average(gains) || 0;
  const avgLoss = average(losses) || 0;
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

function maxDrawdown(values) {
  let peak = -Infinity;
  let worst = 0;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    peak = Math.max(peak, value);
    if (peak > 0) {
      worst = Math.min(worst, (value - peak) / peak);
    }
  }
  return worst * 100;
}

function volatility(values) {
  const returns = [];
  for (let index = 1; index < values.length; index += 1) {
    const change = pctChange(values[index], values[index - 1]);
    if (Number.isFinite(change)) returns.push(change / 100);
  }
  if (returns.length < 2) return null;
  const mean = average(returns);
  const variance = average(returns.map((value) => (value - mean) ** 2));
  return Math.sqrt(variance) * Math.sqrt(252) * 100;
}

function averageTrueRange(rows, period = 14) {
  if (rows.length <= period) return null;
  const ranges = [];
  for (let index = 1; index < rows.length; index += 1) {
    const row = rows[index];
    const previousClose = rows[index - 1].close;
    if (![row.high, row.low, previousClose].every(Number.isFinite)) continue;
    ranges.push(Math.max(
      row.high - row.low,
      Math.abs(row.high - previousClose),
      Math.abs(row.low - previousClose),
    ));
  }
  return average(ranges.slice(-period));
}

function scoreAnalysis(metrics) {
  const trend = clamp(
    (metrics.price > metrics.sma20 ? 30 : 0) +
      (metrics.price > metrics.sma60 ? 30 : 0) +
      (metrics.sma20 > metrics.sma60 ? 25 : 0) +
      (Number(metrics.return20d) > 0 ? 15 : 0),
  );

  const rsiScore =
    metrics.rsi === null
      ? 45
      : metrics.rsi >= 45 && metrics.rsi <= 68
        ? 85
        : metrics.rsi > 68 && metrics.rsi <= 78
          ? 62
          : metrics.rsi > 78
            ? 35
            : 42;

  const momentum = clamp((Number(metrics.return20d) || 0) * 2.2 + (Number(metrics.return60d) || 0) * 0.7 + rsiScore * 0.45);
  const volume = clamp((Number(metrics.volumeRatio) || 0) * 38 + (Number(metrics.return5d) > 0 ? 18 : 0));
  const risk = clamp(100 - Math.abs(Number(metrics.maxDrawdown) || 0) * 1.25 - Math.max(0, (Number(metrics.volatility) || 0) - 28));
  const quality = clamp((trend + momentum + volume + risk) / 4);
  const overall = clamp(trend * 0.32 + momentum * 0.28 + volume * 0.18 + risk * 0.22);

  return {
    overall: round(overall, 1),
    trend: round(trend, 1),
    momentum: round(momentum, 1),
    volume: round(volume, 1),
    risk: round(risk, 1),
    quality: round(quality, 1),
  };
}

function entryOpportunity(metrics, trendScore) {
  const distance = Number(metrics.distanceToSma20);
  const extensionAtr = Number(metrics.extensionAtr);
  const return5d = Number(metrics.return5d);
  const return20d = Number(metrics.return20d);
  const rsiValue = Number(metrics.rsi);
  const volumeRatio = Number(metrics.volumeRatio);

  const extension = clamp(
    100
      - Math.max(0, distance - 2.5) * 10
      - Math.max(0, extensionAtr - 1.5) * 18
      - Math.max(0, -distance) * 8,
  );
  const freshness = clamp(
    100
      - Math.max(0, return5d - 8) * 6
      - Math.max(0, return20d - 15) * 3
      - Math.max(0, rsiValue - 65) * 4
      - Math.max(0, 42 - rsiValue) * 3,
  );
  const volume = clamp(
    volumeRatio >= 0.8 && volumeRatio <= 1.8
      ? 100
      : 100 - Math.abs(volumeRatio - 1.3) * 35,
  );

  const supportCandidates = [metrics.sma20, metrics.sma60, metrics.recentLow20]
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0 && value < metrics.price);
  const support = supportCandidates.length ? Math.max(...supportCandidates) : null;
  const stopPrice = support === null
    ? null
    : support - (Number(metrics.atr14) || 0) * 0.35;
  const stopDistancePct = stopPrice && stopPrice < metrics.price
    ? ((metrics.price - stopPrice) / metrics.price) * 100
    : null;
  const targetCandidates = [metrics.recentHigh20, metrics.recentHigh60]
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > metrics.price + (Number(metrics.atr14) || 0) * 0.5)
    .sort((a, b) => a - b);
  const targetPrice = targetCandidates[0]
    || (Number.isFinite(Number(metrics.atr14)) ? metrics.price + Number(metrics.atr14) * 2 : null);
  const rewardRiskRatio = targetPrice && stopPrice && metrics.price > stopPrice
    ? (targetPrice - metrics.price) / (metrics.price - stopPrice)
    : null;
  const riskReward = clamp(
    (stopDistancePct === null ? 50 : stopDistancePct <= 4 ? 100 : stopDistancePct <= 8 ? 65 : stopDistancePct <= 10 ? 35 : 0) * 0.35
      + (rewardRiskRatio === null ? 50 : rewardRiskRatio >= 2.2 ? 100 : rewardRiskRatio >= 1.5 ? 75 : rewardRiskRatio >= 1 ? 45 : 15) * 0.65,
  );

  let entryScore = extension * 0.30 + freshness * 0.20 + riskReward * 0.30 + volume * 0.10 + clamp(trendScore) * 0.10;
  if (return20d >= 25) entryScore *= 0.55;
  else if (return20d >= 20) entryScore *= 0.75;
  if (return5d >= 18) entryScore *= 0.45;
  else if (return5d >= 12) entryScore *= 0.70;
  if (distance >= 12) entryScore *= 0.55;
  else if (distance > 6) entryScore *= 0.90;
  if (rewardRiskRatio !== null && rewardRiskRatio < 1) entryScore *= 0.80;
  entryScore = round(clamp(entryScore), 1);

  const overextended = distance >= 12 || extensionAtr >= 4 || return5d >= 18 || return20d >= 35 || rsiValue >= 80;
  const actionable =
    entryScore >= 65
    && trendScore >= 62
    && metrics.price >= metrics.sma20
    && distance <= 6
    && return5d <= 10
    && return20d <= 20
    && rsiValue <= 72
    && (stopDistancePct === null || stopDistancePct <= 8)
    && (rewardRiskRatio === null || rewardRiskRatio >= 1.5);

  const status = overextended ? "overextended" : actionable ? "scale_in" : "wait_pullback";
  const labels = {
    scale_in: "可分批布局",
    wait_pullback: "等待回測",
    overextended: "過度延伸、不追",
  };
  const actions = {
    scale_in: "風險報酬仍可控，可依規劃停損小量分批。",
    wait_pullback: "已發動或條件尚未完整，等待回測支撐，不宜追價。",
    overextended: "漲幅與均線乖離過大，不追價，等待風險重新收斂。",
  };
  return {
    entry_score: entryScore,
    entry_status: status,
    entry_status_label: labels[status],
    entry_action: actions[status],
    entry_plan: {
      support_price: round(support),
      stop_price: round(stopPrice),
      stop_distance_pct: round(stopDistancePct),
      target_price: round(targetPrice),
      reward_risk_ratio: round(rewardRiskRatio),
      extension_atr: round(extensionAtr),
      distance_to_ma20_pct: round(distance),
    },
  };
}

function verdict(score) {
  if (score >= 78) return { label: "強勢觀察", tone: "bullish" };
  if (score >= 62) return { label: "偏多續強", tone: "positive" };
  if (score >= 48) return { label: "中性等待", tone: "neutral" };
  return { label: "弱勢觀望", tone: "defensive" };
}

function buildReasons(metrics, scores) {
  const reasons = [];
  const risks = [];

  if (metrics.price > metrics.sma20 && metrics.price > metrics.sma60) reasons.push("股價站上 MA20 與 MA60，趨勢結構偏多");
  if (metrics.sma20 > metrics.sma60) reasons.push("MA20 高於 MA60，短中期均線排列較佳");
  if (Number(metrics.return20d) > 8) reasons.push("20 日漲幅明顯，資金動能較強");
  if (Number(metrics.volumeRatio) > 1.4) reasons.push("成交量高於近 20 日均量，市場關注升溫");
  if (scores.risk >= 70) reasons.push("波動與回撤壓力相對可控");

  if (metrics.rsi > 75) risks.push("RSI 偏高，短線有過熱或震盪風險");
  if (metrics.price < metrics.sma20) risks.push("股價跌破 MA20，短線趨勢尚未轉強");
  if (metrics.sma20 < metrics.sma60) risks.push("MA20 低於 MA60，中期結構仍需修復");
  if (metrics.maxDrawdown < -20) risks.push("近一年最大回撤偏深，需控管追高風險");
  if (Number(metrics.volumeRatio) < 0.7) risks.push("量能低於均量，若要轉強需要補量確認");

  return {
    reasons: reasons.slice(0, 5),
    risks: risks.slice(0, 5),
  };
}

async function fetchChart(symbol) {
  const url = `${YAHOO_CHART_URL}/${encodeURIComponent(symbol)}?range=1y&interval=1d`;
  const response = await fetch(url, {
    headers: {
      "User-Agent": "taiwan-stock-ai/1.0",
      Accept: "application/json",
    },
  });
  if (!response.ok) throw new Error(`Yahoo chart ${response.status}`);
  const payload = await response.json();
  const result = payload?.chart?.result?.[0];
  const quote = result?.indicators?.quote?.[0];
  const timestamps = result?.timestamp || [];
  if (!result || !quote || !timestamps.length) throw new Error("Yahoo chart empty");

  const rows = timestamps
    .map((timestamp, index) => ({
      date: new Date(timestamp * 1000).toISOString().slice(0, 10),
      open: quote.open?.[index],
      high: quote.high?.[index],
      low: quote.low?.[index],
      close: quote.close?.[index],
      volume: quote.volume?.[index],
    }))
    .filter((row) => Number.isFinite(row.close));

  if (rows.length < 30) throw new Error("Not enough price history");
  return rows;
}

async function analyze(code) {
  const symbols = [`${code}.TW`, `${code}.TWO`];
  let rows = null;
  let symbol = null;
  let lastError = null;

  for (const candidate of symbols) {
    try {
      rows = await fetchChart(candidate);
      symbol = candidate;
      break;
    } catch (error) {
      lastError = error;
    }
  }

  if (!rows) throw lastError || new Error("Unable to load stock chart");

  const closes = rows.map((row) => row.close);
  const volumes = rows.map((row) => row.volume || 0);
  const price = closes.at(-1);
  const avgVolume20 = average(volumes.slice(-20));
  const currentVolume = volumes.at(-1);
  const atr14 = averageTrueRange(rows, 14);
  const sma20Value = sma(closes, 20);
  const recentHigh20 = Math.max(...closes.slice(-21, -1));
  const recentHigh60 = Math.max(...closes.slice(-61, -1));
  const recentLow20 = Math.min(...closes.slice(-21, -1));

  const metrics = {
    price: round(price, 2),
    return1d: round(pctChange(price, closes.at(-2))),
    return5d: round(pctChange(price, closes.at(-6))),
    return20d: round(pctChange(price, closes.at(-21))),
    return60d: round(pctChange(price, closes.at(-61))),
    high52w: round(Math.max(...closes), 2),
    low52w: round(Math.min(...closes), 2),
    sma20: round(sma20Value, 2),
    sma60: round(sma(closes, 60), 2),
    sma120: round(sma(closes, 120), 2),
    rsi: round(rsi(closes)),
    atr14: round(atr14, 2),
    distanceToSma20: round(sma20Value ? ((price / sma20Value) - 1) * 100 : null),
    extensionAtr: round(atr14 ? (price - sma20Value) / atr14 : null),
    recentHigh20: round(recentHigh20, 2),
    recentHigh60: round(recentHigh60, 2),
    recentLow20: round(recentLow20, 2),
    volume: currentVolume || null,
    avgVolume20: round(avgVolume20, 0),
    volumeRatio: round(avgVolume20 ? currentVolume / avgVolume20 : null, 2),
    maxDrawdown: round(maxDrawdown(closes)),
    volatility: round(volatility(closes)),
  };

  const scores = scoreAnalysis(metrics);
  const entry = entryOpportunity(metrics, scores.overall);
  const market = symbol.endsWith(".TWO") ? "TWO" : "TW";
  const official = await fetchCompanyAssessmentData(code, market);
  const companyAssessment = buildCompanyAssessment(
    metrics,
    entry,
    official.revenue,
    official.valuation,
  );
  scores.entry = entry.entry_score;
  const view = { label: entry.entry_status_label, tone: entry.entry_status };
  const notes = buildReasons(metrics, scores);
  const chart = rows.slice(-120).map((row) => ({ date: row.date, close: round(row.close, 2), volume: row.volume || 0 }));

  return {
    code,
    symbol,
    updated_at: new Date().toISOString(),
    source: `Yahoo Finance chart ${symbol}`,
    verdict: view,
    entry_opportunity: entry,
    company_assessment: companyAssessment,
    revenue: official.revenue,
    metrics,
    scores,
    reasons: notes.reasons,
    risks: notes.risks,
    chart,
  };
}

module.exports = async function handler(req, res) {
  const code = sanitizeCode(req.query?.code);
  if (!code) {
    sendJson(res, 400, { ok: false, error: "Invalid Taiwan stock code." });
    return;
  }

  try {
    const result = await analyze(code);
    sendJson(res, 200, { ok: true, analysis: result });
  } catch (error) {
    sendJson(res, 502, { ok: false, error: error.message || "Stock analysis failed." });
  }
};
