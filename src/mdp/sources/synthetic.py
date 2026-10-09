"""Offline SYNTHETIC data with known, planted data-quality defects.

This is NOT real market data. It exists so the pipeline and its checks can be demonstrated and
tested without internet access, against ground truth.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

SOURCE_PRICES = "synthetic"
SOURCE_ATTENTION = "synthetic_pageviews"
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
START = "2026-01-02"
AS_OF = dt.date(2026, 9, 4)
HOLIDAYS = pd.to_datetime(
    ["2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03"]
)
SPLIT_DATE = pd.Timestamp("2026-05-26")
JUMP_DATE = pd.Timestamp("2026-06-22")
_BASE = {"AAPL": (190.0, 6.0e7), "MSFT": (410.0, 2.5e7), "NVDA": (3520.0, 4.0e7),
         "AMZN": (175.0, 4.5e7), "GOOGL": (150.0, 3.0e7)}


def generate(seed: int = 42):
    """Return (prices, actions, attention, as_of) in the platform's raw schema."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(START, AS_OF.isoformat()).difference(HOLIDAYS)
    n = len(days)
    t0 = pd.Timestamp("2026-09-04 21:00")        # initial load
    t_late = pd.Timestamp("2026-09-05 06:00")    # a later re-delivery

    frames = {}
    for ticker in TICKERS:
        px0, vol0 = _BASE[ticker]
        close = px0 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n)))
        open_ = np.empty(n)
        open_[0] = close[0]
        open_[1:] = close[:-1] * (1 + rng.normal(0, 0.002, n - 1))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
        volume = vol0 * rng.lognormal(0, 0.25, n)
        df = pd.DataFrame({"source": SOURCE_PRICES, "ticker": ticker, "trade_date": days,
                           "open": open_, "high": high, "low": low, "close": close,
                           "volume": volume})
        if ticker == "NVDA":                      # 4:1 split: prices /4, volume x4 from the split day
            after = df["trade_date"] >= SPLIT_DATE
            df.loc[after, ["open", "high", "low", "close"]] /= 4.0
            df.loc[after, "volume"] *= 4.0
        if ticker == "GOOGL":                     # +38% level shift, no corporate action
            after = df["trade_date"] >= JUMP_DATE
            df.loc[after, ["open", "high", "low", "close"]] *= 1.38
            df.loc[df["trade_date"] == JUMP_DATE, "volume"] *= 3.5
            df.loc[df["trade_date"] == JUMP_DATE + pd.Timedelta(days=1), "volume"] *= 2.0
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].round(4)
        df["volume"] = df["volume"].round(0)
        df["ingested_at"] = t0
        frames[ticker] = df

    # --- planted defects -----------------------------------------------------------------
    msft = frames["MSFT"]
    msft.loc[msft.index[60], "volume"] = np.nan                            # null value
    frames["MSFT"] = msft.drop(index=msft.index[[30, 31, 80, 120, 121]])   # missing days

    nvda = frames["NVDA"]
    i = nvda.index[140]
    nvda.loc[i, "low"] = round(nvda.loc[i, "high"] * 1.05, 4)              # low > high

    frames["AMZN"] = frames["AMZN"].iloc[:-7]                              # stale feed

    aapl = frames["AAPL"]
    bad = aapl.iloc[[70]].copy()                                           # corrupted re-delivery
    bad["low"] = round(float(bad["high"].iloc[0]) * 1.10, 4)
    bad["ingested_at"] = t_late
    frames["AAPL"] = pd.concat([aapl, bad], ignore_index=True)

    prices = pd.concat(frames.values(), ignore_index=True)

    actions = pd.DataFrame(
        [
            ("synthetic", "NVDA", SPLIT_DATE, "split", 4.0),
            ("synthetic", "AAPL", pd.Timestamp("2026-02-13"), "dividend", 0.25),
            ("synthetic", "AAPL", pd.Timestamp("2026-05-15"), "dividend", 0.25),
            ("synthetic", "AAPL", pd.Timestamp("2026-08-14"), "dividend", 0.26),
            ("synthetic", "MSFT", pd.Timestamp("2026-02-19"), "dividend", 0.83),
            ("synthetic", "MSFT", pd.Timestamp("2026-05-21"), "dividend", 0.83),
        ],
        columns=["source", "ticker", "action_date", "action_type", "value"],
    )

    cal_days = pd.date_range(START, AS_OF.isoformat(), freq="D")   # page views include weekends
    att = []
    for k, ticker in enumerate(TICKERS):
        r = np.random.default_rng(seed + 100 + k)
        views = r.lognormal(9.0 + 0.1 * k, 0.12, len(cal_days))
        if ticker == "GOOGL":
            views[cal_days == JUMP_DATE] *= 6.0
            views[cal_days == JUMP_DATE + pd.Timedelta(days=1)] *= 3.0
        att.append(pd.DataFrame({"source": SOURCE_ATTENTION, "ticker": ticker,
                                 "obs_date": cal_days, "pageviews": views.round(0)}))
    attention = pd.concat(att, ignore_index=True)

    return prices, actions, attention, AS_OF