"""Expected shapes of data coming out of each source. Checked at ingestion."""
from __future__ import annotations

import pandas as pd

PRICE_COLS = ["source", "ticker", "trade_date", "open", "high", "low", "close", "volume"]
ACTION_COLS = ["source", "ticker", "action_date", "action_type", "value"]
ATTENTION_COLS = ["source", "ticker", "obs_date", "pageviews"]


class SchemaError(ValueError):
    """Raised when a source returns data that does not match the expected schema."""


def validate_frame(df: pd.DataFrame, required: list[str], name: str) -> pd.DataFrame:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SchemaError(f"{name}: missing columns {missing}; got {list(df.columns)}")
    return df