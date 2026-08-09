-- DuckDB-compatible source queries for the report snapshot.
-- The executed notebook uses equivalent pandas transformations because DuckDB
-- is not a project dependency.

CREATE OR REPLACE TEMP VIEW history AS
SELECT
    *,
    COALESCE(source, 'core') AS source_norm,
    ROW_NUMBER() OVER () AS ingest_order
FROM read_json_auto('signal_history.jsonl', format = 'newline_delimited', union_by_name = true);

CREATE OR REPLACE TEMP VIEW performance AS
SELECT
    *,
    COALESCE(source, 'core') AS source_norm,
    ROW_NUMBER() OVER () AS ingest_order
FROM read_json_auto('signal_performance.jsonl', format = 'newline_delimited', union_by_name = true);

CREATE OR REPLACE TEMP VIEW date_dedup AS
SELECT * EXCLUDE (duplicate_rank)
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY date, code, source_norm, horizon
            ORDER BY evaluated_at DESC
        ) AS duplicate_rank
    FROM performance
)
WHERE duplicate_rank = 1;

-- Headline sample size.
SELECT
    COUNT(DISTINCT date) AS distinct_signal_dates,
    COUNT(*) AS unique_date_signals
FROM (
    SELECT DISTINCT date, code, source_norm
    FROM history
);

-- Performance by holding horizon at the recommended analysis grain.
SELECT
    horizon,
    COUNT(*) AS rows,
    COUNT(DISTINCT date) AS signal_dates,
    AVG(return_pct) / 100.0 AS mean_return_rate,
    MEDIAN(return_pct) / 100.0 AS median_return_rate,
    AVG(CASE WHEN return_pct > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
    AVG(excess_return_pct) / 100.0 AS mean_excess_rate,
    AVG(CASE WHEN excess_return_pct > 0 THEN 1.0 ELSE 0.0 END) AS excess_win_rate
FROM date_dedup
GROUP BY horizon
ORDER BY horizon;

-- Performance by candidate source across the four recorded horizons.
SELECT
    source_norm AS source,
    COUNT(*) AS rows,
    COUNT(DISTINCT (date, code, source_norm)) AS unique_signals,
    COUNT(DISTINCT date) AS signal_dates,
    AVG(return_pct) / 100.0 AS mean_return_rate,
    MEDIAN(return_pct) / 100.0 AS median_return_rate,
    AVG(CASE WHEN return_pct > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
    AVG(excess_return_pct) / 100.0 AS mean_excess_rate,
    AVG(CASE WHEN excess_return_pct > 0 THEN 1.0 ELSE 0.0 END) AS excess_win_rate,
    SUM(CASE WHEN return_pct > 0 THEN return_pct ELSE 0 END)
        / NULLIF(-SUM(CASE WHEN return_pct <= 0 THEN return_pct ELSE 0 END), 0) AS profit_factor
FROM date_dedup
GROUP BY source_norm
ORDER BY mean_return_rate DESC;

-- The roadmap is a reviewed decision table, embedded in the report snapshot.
SELECT *
FROM (VALUES
    (1, 'P0', 'Make performance trustworthy'),
    (2, 'P1', 'Separate products and features'),
    (3, 'P2', 'Build a validated model'),
    (4, 'P3', 'Add portfolio risk controls')
) AS roadmap(order_id, phase, goal)
ORDER BY order_id;
