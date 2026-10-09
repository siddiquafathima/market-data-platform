from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path

from . import report as report_mod
from .config import load_config
from .pipeline import run_pipeline
from .sources import synthetic
from .storage import connect

DEFAULT_DB = "data/warehouse.duckdb"
DEFAULT_REPORT = "reports/quality_report.html"


def cmd_demo(args):
    cfg = load_config(args.config)
    prices, actions, attention, as_of = synthetic.generate()
    Path(args.db).unlink(missing_ok=True)
    conn = connect(args.db)
    summary = run_pipeline(conn, prices, actions, attention, cfg, as_of, mode="demo")
    out = report_mod.build_report(conn, args.report, demo=True)
    conn.close()
    print("Demo run complete (SYNTHETIC data).")
    print(summary)
    print(f"Report: {out}")


def cmd_report(args):
    conn = connect(args.db, read_only=True)
    print(report_mod.build_report(conn, args.report))
    conn.close()


def cmd_serve(args):
    import os

    import uvicorn

    os.environ["MDP_DB"] = args.db
    uvicorn.run("mdp.api:app", host=args.host, port=args.port)

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="mdp", description="Market Data Quality Platform")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--report", default=DEFAULT_REPORT)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="offline run on synthetic data with injected defects").set_defaults(fn=cmd_demo)
    sub.add_parser("report", help="rebuild the HTML report from the warehouse").set_defaults(fn=cmd_report)
    s = sub.add_parser("serve", help="start the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()