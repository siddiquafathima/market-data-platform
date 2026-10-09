"""Data quality checks, grouped by the four dimensions in the job description:
completeness, accuracy, timeliness and reliability.

Every check returns plain dict rows so they are easy to test and to store in `dq_results`.
Status is one of: pass | warn | fail.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import Config


def _row(dimension, check, ticker, status, observed, threshold, details):
    return {
        "dimension": dimension, "check_name": check, "ticker": ticker, "status": status,
        "observed": None if observed is None else float(observed),
        "threshold": None if threshold is None else float(threshold), "details": details,
    }


# ---------------------------------------------------------------- completeness
def check_completeness(delivered: pd.DataFrame, cfg: Config) -> list[dict]:
    """Missing trading days per ticker (a day counts as present if a row was delivered for it,
    valid or not; row validity is checked separately).

    With 3+ tickers a day counts as a trading day if at least half of the tickers have data for
    it. That way market holidays (everyone missing) are not flagged, but a single ticker missing
    a normal day is. With fewer tickers it falls back to plain business days.
    """
    if delivered.empty:
        return [_row("completeness", "missing_trading_days", None, "fail", None, None, "no price data")]
    df = delivered.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    by_ticker = df.groupby("ticker")["trade_date"].apply(set)
    n = len(by_ticker)
    counts = df.groupby("trade_date")["ticker"].nunique()
    expected_all = set(counts[counts / n >= 0.5].index) if n >= 3 else None

    out = []
    for ticker, dates in by_ticker.items():
        lo, hi = min(dates), max(dates)
        if expected_all is None:
            expected = set(pd.bdate_range(lo, hi))
        else:
            expected = {d for d in expected_all if lo <= d <= hi}
        missing = sorted(expected - dates)
        ratio = len(missing) / len(expected) if expected else 0.0
        if not missing:
            status = "pass"
        else:
            status = "fail" if ratio > cfg.completeness_fail_ratio else "warn"
        detail = "no gaps" if not missing else "missing: " + ", ".join(d.strftime("%Y-%m-%d") for d in missing[:6])
        out.append(_row("completeness", "missing_trading_days", ticker, status, ratio,
                        cfg.completeness_fail_ratio, detail))
    return out


def check_nulls(raw_latest: pd.DataFrame) -> list[dict]:
    cols = ["open", "high", "low", "close", "volume"]
    out = []
    for ticker, g in raw_latest.groupby("ticker"):
        bad = int(g[cols].isna().any(axis=1).sum())
        rate = bad / len(g)
        out.append(_row("completeness", "null_values", ticker, "pass" if bad == 0 else "warn", rate, 0.0,
                        "no nulls" if bad == 0 else f"{bad} row(s) with nulls quarantined"))
    return out


# -------------------------------------------------------------------- accuracy
def check_row_validity(raw_latest: pd.DataFrame, quarantine: pd.DataFrame) -> list[dict]:
    """OHLC consistency and non-positive values. Offending rows are quarantined, not used."""
    out = []
    q = quarantine[quarantine["reason"] != "null_value"] if not quarantine.empty else quarantine
    for ticker in sorted(raw_latest["ticker"].unique()):
        sub = q[q["ticker"] == ticker] if not q.empty else q
        n = len(sub)
        reasons = ", ".join(sorted(sub["reason"].unique())) if n else ""
        out.append(_row("accuracy", "ohlc_validity", ticker, "pass" if n == 0 else "warn", n, 0,
                        "all rows valid" if n == 0 else f"{n} row(s) quarantined ({reasons})"))
    return out


def detect_price_jumps(silver: pd.DataFrame, actions: pd.DataFrame, cfg: Config):
    """Flag large daily moves; mark them explained if a matching stock split exists.

    Returns (check_rows, anomaly_rows).
    """
    checks, anomalies = [], []
    if silver.empty:
        return checks, anomalies
    df = silver.sort_values(["ticker", "trade_date"]).copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    df["ret"] = df.groupby("ticker")["close"].pct_change()
    splits = actions[actions["action_type"] == "split"].copy() if not actions.empty else actions
    if not splits.empty:
        splits["action_date"] = pd.to_datetime(splits["action_date"]).dt.normalize()

    for ticker, g in df.groupby("ticker"):
        big = g[g["ret"].abs() > cfg.jump_threshold]
        unexplained = 0
        for _, r in big.iterrows():
            explained_by = None
            if not splits.empty:
                near = splits[(splits["ticker"] == ticker) &
                              ((splits["action_date"] - r["trade_date"]).abs() <= pd.Timedelta(days=3))]
                for _, s in near.iterrows():
                    ratio = float(s["value"]) if s["value"] else 0.0
                    if ratio > 0 and abs(r["ret"] - (1 / ratio - 1)) < 0.15:
                        explained_by = f"split {ratio:g}:1"
            if explained_by is None:
                unexplained += 1
            anomalies.append({
                "ticker": ticker, "trade_date": r["trade_date"], "kind": "price_jump",
                "value": float(r["ret"]), "explained_by": explained_by,
            })
        checks.append(_row("accuracy", "unexplained_price_jumps", ticker, "pass" if unexplained == 0 else "fail",
                           unexplained, 0, "no unexplained jumps" if unexplained == 0
                           else f"{unexplained} jump(s) above {cfg.jump_threshold:.0%} with no matching corporate action"))
    return checks, anomalies


# ------------------------------------------------------------------ timeliness
def check_freshness(silver: pd.DataFrame, as_of: dt.date, cfg: Config) -> list[dict]:
    out = []
    if silver.empty:
        return out
    last = pd.to_datetime(silver["trade_date"]).dt.normalize().groupby(silver["ticker"]).max()
    for ticker, last_date in last.items():
        start = (last_date + pd.Timedelta(days=1)).date()
        lag = int(np.busday_count(start, as_of)) if start < as_of else 0
        out.append(_row("timeliness", "freshness_lag_business_days", ticker,
                        "pass" if lag <= cfg.freshness_sla_days else "fail", lag, cfg.freshness_sla_days,
                        f"latest data {last_date.date()}, lag {lag} business day(s)"))
    return out


# ----------------------------------------------------------------- reliability
def check_duplicates(raw_all: pd.DataFrame) -> list[dict]:
    """Same (ticker, date) delivered more than once; conflicting values are the real risk."""
    out = []
    for ticker, g in raw_all.groupby("ticker"):
        grp = g.groupby("trade_date")
        sizes = grp.size()
        dup_days = sizes[sizes > 1].index
        conflicting = 0
        for d in dup_days:
            sub = g[g["trade_date"] == d]
            if sub[["open", "high", "low", "close", "volume"]].round(8).drop_duplicates().shape[0] > 1:
                conflicting += 1
        if conflicting:
            status, detail = "warn", f"{conflicting} day(s) delivered twice with conflicting values (latest valid load wins)"
        elif len(dup_days):
            status, detail = "pass", f"{len(dup_days)} identical duplicate day(s) collapsed"
        else:
            status, detail = "pass", "no duplicates"
        out.append(_row("reliability", "conflicting_duplicates", ticker, status, conflicting, 0, detail))
    return out


def run_all_checks(raw_all, raw_latest, quarantine, silver, actions, as_of, cfg: Config):
    jump_checks, anomalies = detect_price_jumps(silver, actions, cfg)
    results = (
        check_completeness(raw_latest, cfg)  # delivered days; invalid rows are judged by check_row_validity
        + check_nulls(raw_latest)
        + check_row_validity(raw_latest, quarantine)
        + jump_checks
        + check_freshness(silver, as_of, cfg)
        + check_duplicates(raw_all)
    )
    return pd.DataFrame(results), pd.DataFrame(anomalies)