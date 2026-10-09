"""Safety layer for AI/user-supplied SQL. Defence in depth:

1. Only a single SELECT/WITH statement is allowed.
2. Forbidden keywords and functions are rejected (writes, DDL, file access, extensions).
3. Every table referenced must be on an allow-list.
4. A LIMIT is enforced.
5. Execution happens on a read-only connection with external file access disabled.
"""
from __future__ import annotations

import re

import duckdb

ALLOWED_TABLES = {"gold_daily_metrics", "dq_results", "dq_anomalies"}
MAX_ROWS = 500
FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "attach", "detach", "copy", "pragma",
    "export", "import", "install", "load", "call", "set", "truncate", "replace", "merge", "vacuum",
    "read_csv", "read_parquet", "read_json", "glob", "read_text", "read_blob", "httpfs",
}


class UnsafeSQL(ValueError):
    pass


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validate_sql(sql: str, allowed_tables: set[str] = ALLOWED_TABLES, max_rows: int = MAX_ROWS) -> str:
    """Return a safe version of `sql` (with LIMIT enforced) or raise UnsafeSQL."""
    if not sql or not sql.strip():
        raise UnsafeSQL("empty query")
    text = sql.strip().rstrip(";").strip()
    if ";" in _strip_literals(text):
        raise UnsafeSQL("multiple statements are not allowed")
    bare = _strip_literals(text)
    if "--" in bare or "/*" in bare:
        raise UnsafeSQL("comments are not allowed")
    lowered = bare.lower()
    if not re.match(r"^(select|with)\b", lowered):
        raise UnsafeSQL("only SELECT queries are allowed")
    words = set(re.findall(r"[a-z_]+", lowered))
    hit = words & FORBIDDEN
    if hit:
        raise UnsafeSQL(f"forbidden keyword(s): {', '.join(sorted(hit))}")
    ctes = set(re.findall(r"\b([a-z_][a-z0-9_]*)\s+as\s*\(", lowered))
    for name in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_\.]*)", lowered):
        if name not in allowed_tables and name not in ctes:
            raise UnsafeSQL(f"table not allowed: {name}")
    m = re.search(r"\blimit\s+(\d+)\s*$", lowered)
    if m:
        if int(m.group(1)) > max_rows:
            text = re.sub(r"(?i)\blimit\s+\d+\s*$", f"LIMIT {max_rows}", text)
    else:
        text = f"SELECT * FROM ({text}) AS _q LIMIT {max_rows}"
    return text


def run_safe_query(db_path: str, sql: str):
    """Validate then execute on a read-only connection. Returns a DataFrame."""
    safe = validate_sql(sql)
    conn = duckdb.connect(db_path, read_only=True, config={"enable_external_access": False})
    try:
        return conn.execute(safe).df()
    finally:
        conn.close()