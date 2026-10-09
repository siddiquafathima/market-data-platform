"""Orchestrates one pipeline run: ingest -> silver -> gold -> quality checks -> explain.

Every run is logged in `pipeline_runs`. Raw tables are append-only; silver and gold are rebuilt,
so rerunning with the same inputs gives identical curated tables.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

import pandas as pd

from . import checks, explain, transform
from .config import Config
from .schemas import ACTION_COLS, ATTENTION_COLS, PRICE_COLS, validate_frame
from .storage import insert_df

log = logging.getLogger("mdp")


def _stamp(df: pd.DataFrame, run_id: str) -> pd.DataFrame:
    df = df.copy()
    df["run_id"] = run_id
    if "ingested_at" not in df.columns:
        df["ingested_at"] = pd.Timestamp.now().floor("s")
    return df


def ingest(conn, run_id, prices, actions, attention) -> dict:
    validate_frame(prices, PRICE_COLS, "prices")
    validate_frame(actions, ACTION_COLS, "corporate_actions")
    validate_frame(attention, ATTENTION_COLS, "attention")
    return {
        "raw_prices": insert_df(conn, "raw_prices", _stamp(prices, run_id)),
        "raw_corporate_actions": insert_df(conn, "raw_corporate_actions", _stamp(actions, run_id)),
        "raw_attention": insert_df(conn, "raw_attention", _stamp(attention, run_id)),
    }


def run_pipeline(conn, prices, actions, attention, cfg: Config, as_of: dt.date, mode: str = "run") -> dict:
    run_id = uuid.uuid4().hex[:12]
    started = pd.Timestamp.now().floor("s")
    conn.execute("INSERT INTO pipeline_runs VALUES (?, ?, ?, NULL, 'running', NULL)", [run_id, mode, started])
    try:
        counts = ingest(conn, run_id, prices, actions, attention)
        transform.build_silver(conn)
        transform.build_gold(conn)

        raw_all = conn.execute("SELECT * FROM raw_prices").df()
        raw_latest = conn.execute("SELECT * FROM raw_prices_latest").df()
        quarantine = conn.execute("SELECT * FROM quarantine_prices").df()
        silver = conn.execute("SELECT * FROM silver_prices").df()
        actions_df = conn.execute("SELECT * FROM silver_corporate_actions").df()

        results, anomalies = checks.run_all_checks(raw_all, raw_latest, quarantine, silver, actions_df, as_of, cfg)
        results["run_id"], results["checked_at"] = run_id, started
        insert_df(conn, "dq_results", results)

        n_anom = 0
        if not anomalies.empty:
            rows = []
            anomalies = anomalies.astype(object).where(anomalies.notna(), None)
            for a in anomalies.to_dict("records"):
                text, source = explain.explain(conn, a, cfg)
                rows.append({**a, "run_id": run_id, "explanation": text, "explanation_source": source})
            insert_df(conn, "dq_anomalies", pd.DataFrame(rows))
            n_anom = len(rows)

        summary = {
            "run_id": run_id, "rows": counts, "quarantined": len(quarantine), "anomalies": n_anom,
            "checks": results["status"].value_counts().to_dict(),
        }
        conn.execute("UPDATE pipeline_runs SET finished_at=?, status='success', details=? WHERE run_id=?",
                     [pd.Timestamp.now().floor("s"), str(summary), run_id])
        return summary
    except Exception as exc:
        conn.execute("UPDATE pipeline_runs SET finished_at=?, status='failed', details=? WHERE run_id=?",
                     [pd.Timestamp.now().floor("s"), repr(exc), run_id])
        log.exception("pipeline run %s failed", run_id)
        raise


def latest_run_id(conn) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM pipeline_runs WHERE status='success' ORDER BY started_at DESC, finished_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None