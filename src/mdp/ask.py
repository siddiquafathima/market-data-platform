"""Natural-language questions over the curated tables. Requires an LLM; SQL is always guarded."""
from __future__ import annotations

import re

from . import llm
from .sql_guard import run_safe_query, validate_sql

SCHEMA_TEXT = """Tables (DuckDB SQL, read-only):
gold_daily_metrics(ticker, trade_date, open, high, low, close, volume, daily_return, volatility_20d,
                   avg_volume_20d, pageviews, attention_z)
dq_results(run_id, checked_at, dimension, check_name, ticker, status, observed, threshold, details)
dq_anomalies(run_id, ticker, trade_date, kind, value, explained_by, explanation, explanation_source)
status is one of pass, warn, fail. dimension is completeness, accuracy, timeliness or reliability."""

SYSTEM = (
    "Translate the user's question into ONE DuckDB SELECT statement over the tables below. "
    "Return only the SQL, no explanation, no markdown fences.\n" + SCHEMA_TEXT
)


class LLMUnavailable(RuntimeError):
    pass


def question_to_sql(question: str) -> str:
    if not llm.llm_configured():
        raise LLMUnavailable("LLM_API_KEY, LLM_BASE_URL and LLM_MODEL are not set")
    reply = llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}])
    if not reply:
        raise LLMUnavailable("the model returned no answer")
    sql = re.sub(r"^```(?:sql)?|```$", "", reply.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    validate_sql(sql)  # fail early so the caller can show why it was refused
    return sql


def ask(db_path: str, question: str):
    sql = question_to_sql(question)
    return sql, run_safe_query(db_path, sql)