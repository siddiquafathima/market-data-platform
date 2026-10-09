"""Read-only REST API over the curated datasets and quality results."""
from __future__ import annotations

import os
from typing import Optional

import duckdb
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from . import ask as ask_mod
from .pipeline import latest_run_id
from .sql_guard import UnsafeSQL, run_safe_query


def db_path() -> str:
    return os.getenv("MDP_DB", "data/warehouse.duckdb")


def require_key(x_api_key: Optional[str] = Header(default=None)):
    """If MDP_API_KEY is set, every request must send a matching X-API-Key header."""
    expected = os.getenv("MDP_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def _conn():
    try:
        return duckdb.connect(db_path(), read_only=True)
    except duckdb.Error as exc:
        raise HTTPException(status_code=503, detail=f"warehouse unavailable: {exc}")


class SQLBody(BaseModel):
    sql: str


class QuestionBody(BaseModel):
    question: str


app = FastAPI(title="Market Data Quality Platform", version="0.1.0", dependencies=[Depends(require_key)])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/datasets")
def datasets():
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(trade_date), MAX(trade_date) FROM gold_daily_metrics").fetchone()
        return {"gold_daily_metrics": {"rows": row[0], "tickers": row[1], "from": str(row[2]), "to": str(row[3])}}
    finally:
        conn.close()


@app.get("/prices/{ticker}")
def prices(ticker: str, start: Optional[str] = None, end: Optional[str] = None, limit: int = Query(100, ge=1, le=1000)):
    conn = _conn()
    try:
        df = conn.execute(
            """SELECT * FROM gold_daily_metrics WHERE ticker = upper(?)
               AND trade_date >= COALESCE(CAST(? AS DATE), DATE '1900-01-01')
               AND trade_date <= COALESCE(CAST(? AS DATE), DATE '2999-12-31')
               ORDER BY trade_date DESC LIMIT ?""", [ticker, start, end, limit]).df()
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail=f"no data for {ticker}")
    return df.astype(object).where(df.notna(), None).to_dict("records")


@app.get("/quality/summary")
def quality_summary():
    conn = _conn()
    try:
        run_id = latest_run_id(conn)
        if run_id is None:
            raise HTTPException(status_code=404, detail="no successful run yet")
        rows = conn.execute(
            "SELECT dimension, status, COUNT(*) FROM dq_results WHERE run_id=? GROUP BY ALL ORDER BY 1, 2", [run_id]).fetchall()
        out: dict = {}
        for dim, status, n in rows:
            out.setdefault(dim, {})[status] = n
        return {"run_id": run_id, "by_dimension": out}
    finally:
        conn.close()


@app.get("/quality/results")
def quality_results(status: Optional[str] = Query(None, pattern="^(pass|warn|fail)$")):
    conn = _conn()
    try:
        run_id = latest_run_id(conn)
        df = conn.execute(
            "SELECT dimension, check_name, ticker, status, observed, threshold, details FROM dq_results "
            "WHERE run_id=? AND (? IS NULL OR status=?) ORDER BY dimension, ticker", [run_id, status, status]).df()
        return df.astype(object).where(df.notna(), None).to_dict("records")
    finally:
        conn.close()


@app.get("/quality/anomalies")
def quality_anomalies():
    conn = _conn()
    try:
        run_id = latest_run_id(conn)
        df = conn.execute(
            "SELECT ticker, CAST(trade_date AS VARCHAR) AS trade_date, value, explained_by, explanation, explanation_source "
            "FROM dq_anomalies WHERE run_id=? ORDER BY ticker, trade_date", [run_id]).df()
        return df.astype(object).where(df.notna(), None).to_dict("records")
    finally:
        conn.close()


@app.post("/query")
def query(body: SQLBody):
    try:
        df = run_safe_query(db_path(), body.sql)
    except UnsafeSQL as exc:
        raise HTTPException(status_code=400, detail=f"query refused: {exc}")
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=f"query error: {exc}")
    return {"rows": len(df), "data": df.astype(object).where(df.notna(), None).to_dict("records")}


@app.post("/ask")
def ask(body: QuestionBody):
    try:
        sql, df = ask_mod.ask(db_path(), body.question)
    except ask_mod.LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"AI query unavailable: {exc}")
    except UnsafeSQL as exc:
        raise HTTPException(status_code=400, detail=f"generated query refused: {exc}")
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=f"query error: {exc}")
    return {"sql": sql, "rows": len(df), "data": df.astype(object).where(df.notna(), None).to_dict("records")}