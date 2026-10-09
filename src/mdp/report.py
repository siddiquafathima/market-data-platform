"""Static HTML data-quality report for the latest successful run."""
from __future__ import annotations

import html
from pathlib import Path

from .pipeline import latest_run_id

CSS = """body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#1a1a1a}
h1{margin-bottom:.2rem}.sub{color:#666;margin-top:0}table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}
th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px;vertical-align:top}th{background:#f4f4f4}
.cards{display:flex;gap:12px;margin:1rem 0}.card{flex:1;border-radius:8px;padding:12px;text-align:center}
.card b{display:block;font-size:28px}.pass{background:#e6f4ea}.warn{background:#fff4e0}.fail{background:#fde8e8}
td.s-pass{color:#137333;font-weight:600}td.s-warn{color:#b06000;font-weight:600}td.s-fail{color:#c5221f;font-weight:600}
.note{background:#eef3fb;border-radius:8px;padding:10px 14px;font-size:14px}"""


def _table(headers, rows, status_col=None):
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            cls = f' class="s-{html.escape(str(v))}"' if status_col is not None and i == status_col else ""
            cells.append(f"<td{cls}>{html.escape('' if v is None else str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def build_report(conn, out_path: str | Path, demo: bool = False) -> Path:
    run_id = latest_run_id(conn)
    if run_id is None:
        raise RuntimeError("no successful pipeline run found")
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM dq_results WHERE run_id=? GROUP BY status", [run_id]).fetchall())
    cards = "".join(f'<div class="card {s}"><b>{counts.get(s, 0)}</b>{s}</div>' for s in ("pass", "warn", "fail"))
    sections = []
    for dim in ("completeness", "accuracy", "timeliness", "reliability"):
        rows = conn.execute(
            """SELECT ticker, check_name, status, ROUND(observed, 4), details FROM dq_results
               WHERE run_id=? AND dimension=? ORDER BY CASE status WHEN 'fail' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, ticker""",
            [run_id, dim]).fetchall()
        sections.append(f"<h2>{dim.title()}</h2>" + _table(["Ticker", "Check", "Status", "Observed", "Details"], rows, 2))
    anomalies = conn.execute(
        """SELECT ticker, CAST(trade_date AS VARCHAR), ROUND(value, 3), COALESCE(explained_by, 'UNEXPLAINED'),
                  explanation, explanation_source FROM dq_anomalies WHERE run_id=? ORDER BY ticker, trade_date""",
        [run_id]).fetchall()
    quarantined = conn.execute(
        "SELECT ticker, CAST(trade_date AS VARCHAR), reason FROM quarantine_prices ORDER BY ticker, trade_date").fetchall()
    banner = ('<p class="note"><b>Synthetic demo data.</b> Defects were injected on purpose to show what each check catches.</p>'
              if demo else "")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Data quality report</title><style>{CSS}</style></head>
<body><h1>Market Data Quality Report</h1><p class="sub">Run {html.escape(run_id)}</p>{banner}
<div class="cards">{cards}</div>{''.join(sections)}
<h2>Price anomalies and explanations</h2>{_table(["Ticker", "Date", "Return", "Explained by", "Explanation", "Source"], anomalies)}
<h2>Quarantined rows (excluded from curated data)</h2>{_table(["Ticker", "Date", "Reason"], quarantined)}
</body></html>"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out