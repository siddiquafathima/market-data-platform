import datetime as dt

import pytest

from mdp.config import Config
from mdp.pipeline import run_pipeline
from mdp.sources import synthetic
from mdp.storage import connect


@pytest.fixture
def cfg():
    return Config()


@pytest.fixture
def demo_db(tmp_path, cfg):
    """A warehouse populated by the synthetic demo run."""
    db = tmp_path / "wh.duckdb"
    prices, actions, attention, as_of = synthetic.generate()
    conn = connect(db)
    summary = run_pipeline(conn, prices, actions, attention, cfg, as_of, mode="test")
    conn.close()
    return str(db), summary, (prices, actions, attention, as_of)