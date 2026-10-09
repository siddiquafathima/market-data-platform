import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(demo_db, monkeypatch):
    db, *_ = demo_db
    monkeypatch.setenv("MDP_DB", db)
    monkeypatch.delenv("MDP_API_KEY", raising=False)
    from mdp.api import app
    return TestClient(app)


def test_health_and_datasets(client):
    assert client.get("/health").json() == {"status": "ok"}
    d = client.get("/datasets").json()["gold_daily_metrics"]
    assert d["tickers"] == 5 and d["rows"] > 800


def test_prices_endpoint_and_404(client):
    rows = client.get("/prices/googl?limit=5").json()
    assert len(rows) == 5 and rows[0]["ticker"] == "GOOGL"
    assert client.get("/prices/NOPE").status_code == 404


def test_quality_endpoints(client):
    s = client.get("/quality/summary").json()
    assert s["by_dimension"]["timeliness"]["fail"] == 1
    fails = client.get("/quality/results?status=fail").json()
    assert {r["ticker"] for r in fails} == {"MSFT", "AMZN", "GOOGL"}
    assert client.get("/quality/results?status=bogus").status_code == 422
    an = client.get("/quality/anomalies").json()
    assert any(a["ticker"] == "GOOGL" and a["explained_by"] is None for a in an)


def test_query_endpoint_allows_select_blocks_writes(client):
    ok = client.post("/query", json={"sql": "SELECT ticker, COUNT(*) AS n FROM gold_daily_metrics GROUP BY ticker"})
    assert ok.status_code == 200 and ok.json()["rows"] == 5
    bad = client.post("/query", json={"sql": "DROP TABLE gold_daily_metrics"})
    assert bad.status_code == 400 and "refused" in bad.json()["detail"]
    file_read = client.post("/query", json={"sql": "SELECT * FROM read_csv('/etc/passwd')"})
    assert file_read.status_code == 400


def test_ask_without_llm_is_a_clean_503(client, monkeypatch):
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    r = client.post("/ask", json={"question": "which tickers failed?"})
    assert r.status_code == 503


def test_api_key_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("MDP_API_KEY", "secret")
    assert client.get("/datasets").status_code == 401
    assert client.get("/datasets", headers={"X-API-Key": "secret"}).status_code == 200