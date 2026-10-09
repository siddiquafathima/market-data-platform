"""Explain flagged anomalies. Rules first (always available); an LLM may rewrite the summary.

The LLM only ever sees facts we computed and can only produce text. It cannot change data.
"""
from __future__ import annotations

import json
import math

import duckdb

from . import llm
from .config import Config

SYSTEM_PROMPT = (
    "You are a data-quality analyst for a market data platform. Use ONLY the facts provided. "
    "In at most 60 words, say the most likely cause and name ONE verification step. "
    "Never suggest changing or deleting data automatically."
)


def _clean(value):
    """pandas turns missing values into NaN; treat NaN/empty as None."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
        return None
    return value


def build_context(conn: duckdb.DuckDBPyConnection, anomaly: dict) -> dict:
    row = conn.execute(
        """SELECT daily_return, volume, avg_volume_20d, pageviews, attention_z
           FROM gold_daily_metrics WHERE ticker = ? AND trade_date = ?""",
        [anomaly["ticker"], anomaly["trade_date"]],
    ).fetchone()
    ctx = {
        "ticker": anomaly["ticker"], "date": str(anomaly["trade_date"])[:10],
        "daily_return": anomaly["value"], "explained_by": _clean(anomaly.get("explained_by")),
        "volume_ratio": None, "attention_z": None,
    }
    if row:
        _, vol, avg_vol, _, att_z = row
        if vol is not None and avg_vol:
            ctx["volume_ratio"] = float(vol) / float(avg_vol)
        ctx["attention_z"] = None if att_z is None else float(att_z)
    return ctx


def rule_explanation(ctx: dict, cfg: Config) -> str:
    head = f"{ctx['ticker']} moved {ctx['daily_return']:+.1%} on {ctx['date']}."
    if ctx["explained_by"]:
        return f"{head} Consistent with {ctx['explained_by']}; no action needed."
    signals = []
    vr, az = ctx["volume_ratio"], ctx["attention_z"]
    if vr is not None and vr >= cfg.volume_spike_ratio:
        signals.append(f"volume was {vr:.1f}x its 20-day average")
    if az is not None and az >= cfg.attention_spike_z:
        signals.append(f"web attention spiked (z={az:.1f})")
    if signals:
        return (f"{head} No split or dividend found, but " + " and ".join(signals) +
                ". Pattern fits a real news-driven move; confirm against a second price source.")
    return (f"{head} No corporate action and no volume or attention signal. More likely a data error "
            "than a real move; verify against a second price source before using this series.")


def explain(conn: duckdb.DuckDBPyConnection, anomaly: dict, cfg: Config) -> tuple[str, str]:
    """Return (text, source) where source is 'rules' or 'llm'."""
    ctx = build_context(conn, anomaly)
    base = rule_explanation(ctx, cfg)
    if _clean(anomaly.get("explained_by")) or not llm.llm_configured():
        return base, "rules"
    reply = llm.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"facts": ctx, "rule_based_summary": base}, default=str)},
    ])
    return (reply, "llm") if reply else (base, "rules")