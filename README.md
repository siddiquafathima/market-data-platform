# Market Data Quality Platform

A data-engineering project that ingests market data from several sources, checks it for
completeness, accuracy, timeliness and reliability, quarantines bad rows, builds curated
datasets and serves them through a REST API.

> The demo and tests use SYNTHETIC data with planted defects. It is not real market data.

## Why
(2-3 sentences in your own words: why data quality matters for a company that sells data.)

## How it works
raw (append-only) -> silver (validated, deduplicated, quarantine) -> gold (curated metrics)
-> quality checks -> explanations -> API and HTML report

(Short list of the 4 check dimensions and one example of each.)

## Run it
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH="src"
python -m mdp demo
python -m mdp serve
pytest
```

## Demo result
839 rows delivered, 836 curated, 3 quarantined. 30 checks: 23 pass, 4 warn, 3 fail.
(Table: planted defect -> how it was caught.)

## Limitations
(Be honest: synthetic data, batch only, no scheduler, Wikipedia page views are only a proxy for
alternative data.)

## Built with
Python, DuckDB, pandas, FastAPI, pytest. Built with AI assistance (Claude).