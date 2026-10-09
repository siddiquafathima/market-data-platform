import datetime as dt

import pandas as pd

from mdp import checks
from mdp.config import Config


def frame(ticker, dates, close=100.0):
    return pd.DataFrame({"ticker": ticker, "trade_date": pd.to_datetime(dates), "close": close,
                         "open": close, "high": close, "low": close, "volume": 1000.0})


def test_completeness_ignores_market_holidays_but_flags_single_ticker_gap():
    days = list(pd.bdate_range("2026-03-02", "2026-03-27"))
    holiday = days[5]
    gap = days[10]
    parts = []
    for t in ("AAA", "BBB", "CCC"):
        d = [x for x in days if x != holiday]
        if t == "BBB":
            d = [x for x in d if x != gap]
        parts.append(frame(t, d))
    res = {r["ticker"]: r for r in checks.check_completeness(pd.concat(parts), Config())}
    assert res["AAA"]["status"] == "pass"
    assert res["CCC"]["status"] == "pass"
    assert res["BBB"]["status"] in ("warn", "fail")
    assert str(gap.date()) in res["BBB"]["details"]
    assert str(holiday.date()) not in res["BBB"]["details"]


def test_jump_explained_by_split_is_not_a_failure():
    prices = pd.concat([frame("NVDA", ["2026-05-21", "2026-05-22"], 100.0),
                        frame("NVDA", ["2026-05-26"], 25.0)])
    actions = pd.DataFrame({"ticker": ["NVDA"], "action_date": [pd.Timestamp("2026-05-26")],
                            "action_type": ["split"], "value": [4.0]})
    rows, anomalies = checks.detect_price_jumps(prices, actions, Config())
    assert rows[0]["status"] == "pass"
    assert anomalies[0]["explained_by"] == "split 4:1"


def test_unexplained_jump_fails():
    prices = pd.concat([frame("XYZ", ["2026-05-21"], 100.0), frame("XYZ", ["2026-05-22"], 140.0)])
    empty = pd.DataFrame(columns=["ticker", "action_date", "action_type", "value"])
    rows, anomalies = checks.detect_price_jumps(prices, empty, Config())
    assert rows[0]["status"] == "fail" and anomalies[0]["explained_by"] is None


def test_freshness_lag_and_sla():
    cfg = Config()
    fresh = frame("OK", ["2026-09-04"])      # Friday
    stale = frame("OLD", ["2026-08-26"])
    res = {r["ticker"]: r for r in checks.check_freshness(pd.concat([fresh, stale]), dt.date(2026, 9, 7), cfg)}
    assert res["OK"]["status"] == "pass" and res["OK"]["observed"] == 0
    assert res["OLD"]["status"] == "fail" and res["OLD"]["observed"] > cfg.freshness_sla_days


def test_conflicting_duplicates_flagged_identical_ones_not():
    base = frame("AAA", ["2026-01-05", "2026-01-06"])
    conflicting = pd.concat([base, frame("AAA", ["2026-01-06"], close=105.0)])
    identical = pd.concat([base, frame("AAA", ["2026-01-06"], close=100.0)])
    assert checks.check_duplicates(conflicting)[0]["status"] == "warn"
    assert checks.check_duplicates(identical)[0]["status"] == "pass"