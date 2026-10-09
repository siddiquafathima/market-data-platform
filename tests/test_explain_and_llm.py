import duckdb

from mdp import explain, llm
from mdp.config import Config


def ctx(**kw):
    base = {"ticker": "ZZZ", "date": "2026-01-02", "daily_return": 0.4, "explained_by": None,
            "volume_ratio": None, "attention_z": None}
    return {**base, **kw}


def test_rules_explanation_branches():
    cfg = Config()
    assert "split 4:1" in explain.rule_explanation(ctx(explained_by="split 4:1"), cfg)
    assert "news-driven" in explain.rule_explanation(ctx(volume_ratio=3.0, attention_z=5.0), cfg)
    assert "data error" in explain.rule_explanation(ctx(), cfg)


def test_nan_explained_by_is_treated_as_missing():
    assert explain._clean(float("nan")) is None


def test_llm_unconfigured_returns_none(monkeypatch):
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert llm.chat([{"role": "user", "content": "hi"}]) is None


def test_llm_text_is_used_when_available_and_rules_when_it_fails(demo_db, monkeypatch):
    db, *_ = demo_db
    conn = duckdb.connect(db, read_only=True)
    anomaly = {"ticker": "GOOGL", "trade_date": "2026-06-22", "value": 0.38, "explained_by": None}
    monkeypatch.setattr(llm, "llm_configured", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda messages, timeout=30: "LLM says: verify with a second source.")
    assert explain.explain(conn, anomaly, Config()) == ("LLM says: verify with a second source.", "llm")
    monkeypatch.setattr(llm, "chat", lambda messages, timeout=30: None)
    text, source = explain.explain(conn, anomaly, Config())
    assert source == "rules" and "GOOGL" in text
    conn.close()