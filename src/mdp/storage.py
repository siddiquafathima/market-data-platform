from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS raw_prices(
        run_id VARCHAR, ingested_at TIMESTAMP, source VARCHAR, ticker VARCHAR, trade_date DATE,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE)""",
    """CREATE TABLE IF NOT EXISTS raw_corporate_actions(
        run_id VARCHAR, ingested_at TIMESTAMP, source VARCHAR, ticker VARCHAR, action_date DATE,
        action_type VARCHAR, value DOUBLE)""",
    """CREATE TABLE IF NOT EXISTS raw_attention(
        run_id VARCHAR, ingested_at TIMESTAMP, source VARCHAR, ticker VARCHAR, obs_date DATE,
        pageviews DOUBLE)""",
    """CREATE TABLE IF NOT EXISTS pipeline_runs(
        run_id VARCHAR, mode VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP,
        status VARCHAR, details VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS dq_results(
        run_id VARCHAR, checked_at TIMESTAMP, dimension VARCHAR, check_name VARCHAR, ticker VARCHAR,
        status VARCHAR, observed DOUBLE, threshold DOUBLE, details VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS dq_anomalies(
        run_id VARCHAR, ticker VARCHAR, trade_date DATE, kind VARCHAR, value DOUBLE,
        explained_by VARCHAR, explanation VARCHAR, explanation_source VARCHAR)""",
]


def connect(path: str | Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = Path(path)
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
    return conn


def insert_df(conn: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Insert a DataFrame into a table by column name (order independent)."""
    if df.empty:
        return 0
    cols = ", ".join(df.columns)
    conn.register("_incoming", df)
    try:
        conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
    finally:
        conn.unregister("_incoming")
    return len(df)