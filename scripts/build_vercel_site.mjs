import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const sourceDir = path.join(root, "web");
const distDir = path.join(sourceDir, "dist");
const snapshotCandidates = [
  path.join(root, "runtime", "daily_candidates.json"),
  path.join(root, "tests", "fixtures", "sample_daily_candidates.json"),
];
const stockIndexPath = path.join(root, "web", "data", "tw_stock_index.json");
const defaultSnapshotUrl =
  "https://imqu8cpubada2jad.public.blob.vercel-storage.com/dashboard/latest.json";

function copyFile(from, to) {
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
}

function copyStatic() {
  fs.rmSync(distDir, { recursive: true, force: true });
  fs.mkdirSync(distDir, { recursive: true });
  for (const file of ["index.html", "styles.css", "app.js"]) {
    copyFile(path.join(sourceDir, file), path.join(distDir, file));
  }
}

function copySnapshot() {
  const snapshotPath = snapshotCandidates.find((candidate) => fs.existsSync(candidate));
  if (!snapshotPath) {
    throw new Error("No snapshot source found for Vercel dashboard build.");
  }
  copyFile(snapshotPath, path.join(distDir, "data", "daily_candidates.json"));
}

function copyStockIndex() {
  if (!fs.existsSync(stockIndexPath)) {
    throw new Error("Missing web/data/tw_stock_index.json. Run python scripts/export_tw_stock_index.py.");
  }
  copyFile(stockIndexPath, path.join(distDir, "data", "tw_stock_index.json"));
}

function writeConfig() {
  const snapshotUrl = process.env.VERCEL_SNAPSHOT_URL || defaultSnapshotUrl;
  const snapshotFallbackUrl =
    process.env.VERCEL_SNAPSHOT_FALLBACK_URL || "/data/daily_candidates.json";
  const stockIndexUrl = process.env.VERCEL_STOCK_INDEX_URL || "/data/tw_stock_index.json";
  const content = `window.TSAI_CONFIG = ${JSON.stringify(
    { snapshotUrl, snapshotFallbackUrl, stockIndexUrl },
    null,
    2,
  )};\n`;
  fs.writeFileSync(path.join(distDir, "config.js"), content, "utf-8");
}

copyStatic();
copySnapshot();
copyStockIndex();
writeConfig();

if (process.argv.includes("--check")) {
  const required = ["index.html", "styles.css", "app.js", "config.js", "data/daily_candidates.json", "data/tw_stock_index.json"];
  for (const file of required) {
    const target = path.join(distDir, file);
    if (!fs.existsSync(target)) {
      throw new Error(`Missing build output: ${file}`);
    }
  }
}

console.log(`Built Vercel dashboard at ${path.relative(root, distDir)}`);
