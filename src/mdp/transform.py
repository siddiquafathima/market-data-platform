"""Raw -> silver (clean, deduplicated, quarantined) -> gold (curated data products).

All layers are rebuilt from the append-only raw tables with CREATE OR REPLACE, so a rerun of
the same inputs produces identical silver and gold tables (idempotent).
"""
from __future__ import annotations

import duckdb

SILVER_SQL = [
    # Flag every delivered row with a validity reason (NULL reason = valid).
    """CREATE OR REPLACE TABLE raw_prices_flagged AS
       SELECT *, CASE
           WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL
                THEN 'null_value'
           WHEN open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 THEN 'non_positive_price'
           WHEN volume < 0 THEN 'negative_volume'
           WHEN low > high OR open > high OR close > high OR open < low OR close < low
                THEN 'ohlc_inconsistent'
         END AS reason
       FROM raw_prices""",
    # One row per (ticker, day): prefer a valid row, then the most recently ingested one.
    # A bad later load therefore cannot overwrite a good earlier row.
    """CREATE OR REPLACE TABLE raw_prices_latest AS
       SELECT * EXCLUDE (rn) FROM (
         SELECT *, ROW_NUMBER() OVER (
           PARTITION BY ticker, trade_date
           ORDER BY (reason IS NULL) DESC, ingested_at DESC, run_id DESC) AS rn
         FROM raw_prices_flagged) WHERE rn = 1""",
    # Invalid rows are quarantined with a reason, never silently dropped. Identical rejected rows
    # delivered by repeated runs are collapsed so reruns do not inflate the count.
    """CREATE OR REPLACE TABLE quarantine_prices AS
       SELECT * EXCLUDE (rn) FROM (
         SELECT *, ROW_NUMBER() OVER (
           PARTITION BY ticker, trade_date, reason, open, high, low, close, volume
           ORDER BY ingested_at DESC, run_id DESC) AS rn
         FROM raw_prices_flagged WHERE reason IS NOT NULL) WHERE rn = 1""",
    """CREATE OR REPLACE TABLE silver_prices AS
       SELECT source, ticker, trade_date, open, high, low, close, volume
       FROM raw_prices_latest WHERE reason IS NULL""",
    """CREATE OR REPLACE TABLE silver_corporate_actions AS
       SELECT * EXCLUDE (rn) FROM (
         SELECT *, ROW_NUMBER() OVER (
           PARTITION BY ticker, action_date, action_type ORDER BY ingested_at DESC, run_id DESC) AS rn
         FROM raw_corporate_actions) WHERE rn = 1""",
    """CREATE OR REPLACE TABLE silver_attention AS
       SELECT * EXCLUDE (rn) FROM (
         SELECT *, ROW_NUMBER() OVER (
           PARTITION BY ticker, obs_date ORDER BY ingested_at DESC, run_id DESC) AS rn
         FROM raw_attention WHERE pageviews >= 0) WHERE rn = 1""",
]

GOLD_SQL = [
    """CREATE OR REPLACE TABLE gold_daily_metrics AS
       WITH base AS (
         SELECT ticker, trade_date, open, high, low, close, volume,
                close / LAG(close) OVER (PARTITION BY ticker ORDER BY trade_date) - 1 AS daily_return
         FROM silver_prices
       ), m AS (
         SELECT *,
                STDDEV_SAMP(daily_return) OVER w AS volatility_20d,
                AVG(volume) OVER w AS avg_volume_20d
         FROM base
         WINDOW w AS (PARTITION BY ticker ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
       ), att AS (
         SELECT ticker, obs_date, pageviews,
                (pageviews - AVG(pageviews) OVER w2) / NULLIF(STDDEV_SAMP(pageviews) OVER w2, 0) AS attention_z
         FROM silver_attention
         WINDOW w2 AS (PARTITION BY ticker ORDER BY obs_date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING)
       )
       SELECT m.ticker, m.trade_date, m.open, m.high, m.low, m.close, m.volume,
              m.daily_return, m.volatility_20d, m.avg_volume_20d,
              a.pageviews, a.attention_z
       FROM m LEFT JOIN att a ON a.ticker = m.ticker AND a.obs_date = m.trade_date
       ORDER BY m.ticker, m.trade_date""",
]


def build_silver(conn: duckdb.DuckDBPyConnection) -> None:
    for stmt in SILVER_SQL:
        conn.execute(stmt)


def build_gold(conn: duckdb.DuckDBPyConnection) -> None:
    for stmt in GOLD_SQL:
        conn.execute(stmt)