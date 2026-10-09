"""Pipeline configuration. Defaults live here; config/config.yaml overrides them."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class Config:
    tickers: list[str] = field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"])
    wiki_articles: dict[str, str] = field(
        default_factory=lambda: {
            "AAPL": "Apple_Inc.",
            "MSFT": "Microsoft",
            "NVDA": "Nvidia",
            "AMZN": "Amazon_(company)",
            "GOOGL": "Google",
        }
    )
    jump_threshold: float = 0.25
    completeness_fail_ratio: float = 0.02
    freshness_sla_days: int = 3
    attention_spike_z: float = 3.0
    volume_spike_ratio: float = 2.0


def load_config(path: str | Path | None = None) -> Config:
    """Load config.yaml on top of the defaults. A missing file just yields the defaults."""
    cfg = Config()
    if path is None or not Path(path).exists():
        return cfg
    raw = yaml.safe_load(Path(path).read_text()) or {}
    flat = {**{k: v for k, v in raw.items() if k != "thresholds"}, **(raw.get("thresholds") or {})}
    known = {f.name for f in fields(Config)}
    for key, value in flat.items():
        if key in known:
            setattr(cfg, key, value)
    return cfg