import pytest

from mdp.sql_guard import UnsafeSQL, validate_sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM gold_daily_metrics WHERE ticker='AAPL'",
    "select ticker, count(*) from dq_results group by ticker",
    "WITH x AS (SELECT * FROM dq_results) SELECT * FROM x",
])
def test_allowed_queries_pass_and_get_a_limit(sql):
    assert "limit" in validate_sql(sql).lower()


@pytest.mark.parametrize("sql", [
    "DROP TABLE gold_daily_metrics",
    "SELECT 1; DELETE FROM dq_results",
    "SELECT * FROM raw_prices",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM gold_daily_metrics -- sneaky",
    "INSERT INTO dq_results SELECT * FROM dq_results",
    "COPY dq_results TO '/tmp/x.csv'",
    "SELECT * FROM gold_daily_metrics JOIN silver_prices USING (ticker)",
    "",
])
def test_dangerous_or_out_of_scope_queries_are_refused(sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql)


def test_oversized_limit_is_capped():
    assert "LIMIT 500" in validate_sql("SELECT * FROM dq_results LIMIT 99999")


def test_semicolon_inside_string_literal_is_fine():
    validate_sql("SELECT * FROM dq_results WHERE details = 'a;b'")