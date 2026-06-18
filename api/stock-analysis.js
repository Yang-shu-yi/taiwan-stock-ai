const YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart";

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

  const metrics = {
    price: round(price, 2),
    return1d: round(pctChange(price, closes.at(-2))),
    return5d: round(pctChange(price, closes.at(-6))),
    return20d: round(pctChange(price, closes.at(-21))),
    return60d: round(pctChange(price, closes.at(-61))),
    high52w: round(Math.max(...closes), 2),
    low52w: round(Math.min(...closes), 2),
    sma20: round(sma(closes, 20), 2),
    sma60: round(sma(closes, 60), 2),
    sma120: round(sma(closes, 120), 2),
    rsi: round(rsi(closes)),
    volume: currentVolume || null,
    avgVolume20: round(avgVolume20, 0),
    volumeRatio: round(avgVolume20 ? currentVolume / avgVolume20 : null, 2),
    maxDrawdown: round(maxDrawdown(closes)),
    volatility: round(volatility(closes)),
  };

  const scores = scoreAnalysis(metrics);
  const view = verdict(scores.overall);
  const notes = buildReasons(metrics, scores);
  const chart = rows.slice(-120).map((row) => ({ date: row.date, close: round(row.close, 2), volume: row.volume || 0 }));

  return {
    code,
    symbol,
    updated_at: new Date().toISOString(),
    source: `Yahoo Finance chart ${symbol}`,
    verdict: view,
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
