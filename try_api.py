import os
os.environ["MDP_DB"] = "data/warehouse.duckdb"
from fastapi.testclient import TestClient
from mdp.api import app

c = TestClient(app)
print(c.get("/health").json())
print(c.get("/datasets").json())
print(len(c.get("/prices/googl?limit=5").json()), "price rows")
print(c.get("/quality/summary").json())
print([(r["ticker"], r["check_name"]) for r in c.get("/quality/results?status=fail").json()])
print(c.post("/query", json={"sql": "SELECT ticker, COUNT(*) AS n FROM gold_daily_metrics GROUP BY ticker"}).json()["rows"], "rows from /query")
bad = c.post("/query", json={"sql": "DROP TABLE gold_daily_metrics"})
print(bad.status_code, bad.json())
print(c.post("/ask", json={"question": "which tickers failed?"}).status_code)