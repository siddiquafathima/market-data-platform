import duckdb
import pytest

from mdp.pipeline import run_pipeline
from mdp.schemas import SchemaError
from mdp.storage import connect


def statuses(db, **where):
    c = duckdb.connect(db, read_only=True)
    rows = c.execute("SELECT check_name, ticker, status FROM dq_results WHERE run_id=(SELECT run_id FROM pipeline_runs "
                     "WHERE status='success' ORDER BY started_at DESC LIMIT 1)").fetchall()
    c.close()
    return {(n, t): s for n, t, s in rows}


def test_demo_catches_each_injected_defect_and_nothing_extra(demo_db):
    db, summary, _ = demo_db
    s = statuses(db)
    assert s[("missing_trading_days", "MSFT")] == "fail"
    assert s[("freshness_lag_business_days", "AMZN")] == "fail"
    assert s[("unexplained_price_jumps", "GOOGL")] == "fail"
    assert s[("unexplained_price_jumps", "NVDA")] == "pass"      # split is explained
    assert s[("ohlc_validity", "NVDA")] == "warn"
    assert s[("conflicting_duplicates", "AAPL")] == "warn"
    assert s[("null_values", "MSFT")] == "warn"
    # holidays missing for every ticker must not be flagged
    for t in ("AAPL", "NVDA", "AMZN", "GOOGL"):
        assert s[("missing_trading_days", t)] == "pass"
    assert summary["checks"].get("fail") == 3


def test_bad_rows_are_quarantined_not_dropped_silently(demo_db):
    db, *_ = demo_db
    c = duckdb.connect(db, read_only=True)
    reasons = set(c.execute("SELECT ticker, reason FROM quarantine_prices").fetchall())
    assert reasons == {("NVDA", "ohlc_inconsistent"), ("MSFT", "null_value"), ("AAPL", "ohlc_inconsistent")}
    silver_bad = c.execute("SELECT COUNT(*) FROM silver_prices WHERE low > high OR volume IS NULL").fetchone()[0]
    assert silver_bad == 0
    c.close()


def test_bad_later_load_does_not_overwrite_a_good_earlier_row(demo_db):
    db, _, (prices, *_) = demo_db
    dup = prices[prices.duplicated(["ticker", "trade_date"], keep=False)]
    day = dup["trade_date"].iloc[0]
    original_close = dup.sort_values("ingested_at")["close"].iloc[0]
    c = duckdb.connect(db, read_only=True)
    rows = c.execute("SELECT close FROM silver_prices WHERE ticker='AAPL' AND trade_date=?", [day]).fetchall()
    assert len(rows) == 1 and abs(rows[0][0] - original_close) < 1e-9   # the valid first load survives
    c.close()


def test_rerun_is_idempotent_for_curated_layers(tmp_path, cfg):
    from mdp.sources import synthetic
    prices, actions, attention, as_of = synthetic.generate()
    conn = connect(tmp_path / "w.duckdb")
    run_pipeline(conn, prices, actions, attention, cfg, as_of)
    first = conn.execute("SELECT * FROM gold_daily_metrics ORDER BY ticker, trade_date").df()
    run_pipeline(conn, prices, actions, attention, cfg, as_of)   # same inputs again
    second = conn.execute("SELECT * FROM gold_daily_metrics ORDER BY ticker, trade_date").df()
    assert first.equals(second)
    q1 = conn.execute("SELECT COUNT(*) FROM quarantine_prices").fetchone()[0]
    run_pipeline(conn, prices, actions, attention, cfg, as_of)
    assert conn.execute("SELECT COUNT(*) FROM quarantine_prices").fetchone()[0] == q1 == 3
    assert conn.execute("SELECT COUNT(*) FROM silver_prices").fetchone()[0] == len(first)
    conn.close()


def test_schema_violation_fails_the_run_and_is_logged(tmp_path, cfg):
    from mdp.sources import synthetic
    prices, actions, attention, as_of = synthetic.generate()
    conn = connect(tmp_path / "w.duckdb")
    with pytest.raises(SchemaError):
        run_pipeline(conn, prices.drop(columns=["close"]), actions, attention, cfg, as_of)
    assert conn.execute("SELECT status FROM pipeline_runs").fetchone()[0] == "failed"
    conn.close()