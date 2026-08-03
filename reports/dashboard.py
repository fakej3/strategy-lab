"""FastAPI dashboard — 7 pages, server-side HTML, no React, no build tools.

Pages
-----
/               Overview
/sessions       Research Sessions
/strategies     Strategy Results
/reports        Generated Report Files
/jobs           Job Queue
/market-data    Market Data Status
/settings       Pipeline Settings (read-only display)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from research_db.storage import ResearchStorage

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="EdgeLab Dashboard", docs_url=None, redoc_url=None)

_DB_PATH     = Path(os.environ.get("EDGELAB_DB",      "research.db"))
_REPORTS_DIR = Path(os.environ.get("EDGELAB_REPORTS", "reports"))
_DATA_DIR    = Path(os.environ.get("EDGELAB_DATA_DIR","data/bars"))


def _storage() -> ResearchStorage:
    return ResearchStorage(str(_DB_PATH))


# ── Shared CSS + layout ───────────────────────────────────────────────────────

_NAV_LINKS = [
    ("/",             "Overview"),
    ("/sessions",     "Research Runs"),
    ("/strategies",   "Strategies"),
    ("/reports",      "Reports"),
    ("/jobs",         "Job Queue"),
    ("/market-data",  "Market Data"),
    ("/robustness",   "Robustness"),
    ("/regimes",      "Regimes"),
    ("/rolling",      "Rolling"),
    ("/bootstrap",    "Bootstrap CI"),
    ("/degradation",  "Degradation"),
    ("/settings",     "Settings"),
]

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--surface:#161b22;--border:#30363d;
  --text:#e6edf3;--muted:#8b949e;--accent:#4FC3F7;
  --pass-bg:#1a2e1a;--pass-fg:#3fb950;
  --reject-bg:#2e1a1a;--reject-fg:#f85149;
}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  font-size:14px;line-height:1.6;display:flex;min-height:100vh}
nav{width:180px;flex-shrink:0;background:var(--surface);
  border-right:1px solid var(--border);padding:24px 0;position:sticky;
  top:0;height:100vh;overflow-y:auto}
nav .logo{padding:0 20px 20px;font-size:16px;font-weight:700;
  color:var(--accent);border-bottom:1px solid var(--border);margin-bottom:12px}
nav a{display:block;padding:8px 20px;color:var(--muted);
  text-decoration:none;font-size:13px;border-left:3px solid transparent}
nav a:hover,nav a.active{color:var(--text);background:rgba(255,255,255,.04);
  border-left-color:var(--accent)}
main{flex:1;padding:32px 40px;max-width:1200px}
h1{font-size:20px;font-weight:700;margin-bottom:24px}
h2{font-size:13px;font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted);
  border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:16px;margin-bottom:32px}
.tile{background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:16px}
.tile-val{font-size:26px;font-weight:700;color:var(--accent);
  font-variant-numeric:tabular-nums}
.tile-label{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.05em;margin-top:4px}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;
  font-variant-numeric:tabular-nums}
th{background:var(--surface);color:var(--muted);text-align:left;
  padding:8px 12px;border-bottom:1px solid var(--border);
  font-size:11px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:hover td{background:rgba(255,255,255,.03)}
td.r,th.r{text-align:right}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;
  font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.badge.pass  {background:var(--pass-bg);color:var(--pass-fg)}
.badge.reject{background:var(--reject-bg);color:var(--reject-fg)}
.badge.pend  {background:#1c2433;color:#79c0ff}
.badge.run   {background:#2d2200;color:#f0b429}
.badge.done  {background:var(--pass-bg);color:var(--pass-fg)}
.badge.error {background:var(--reject-bg);color:var(--reject-fg)}
.empty{color:var(--muted);font-style:italic;padding:24px 0}
a.dl{color:var(--accent);text-decoration:none}
a.dl:hover{text-decoration:underline}
code{font-family:'Courier New',monospace;font-size:11px;color:var(--muted)}
"""


def _page(path: str, title: str, body: str) -> HTMLResponse:
    nav_items = "".join(
        f'<a href="{href}" class="{"active" if href == path else ""}">{label}</a>'
        for href, label in _NAV_LINKS
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} — EdgeLab</title>
  <style>{_CSS}</style>
</head>
<body>
  <nav>
    <div class="logo">EdgeLab</div>
    {nav_items}
  </nav>
  <main>
    <h1>{title}</h1>
    {body}
  </main>
</body>
</html>"""
    return HTMLResponse(html)


def _fmt(v: float | None, d: int = 4, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{v*100:.2f}%"
    return f"{v:.{d}f}"


def _badge(decision: str) -> str:
    d = decision.lower()
    cls = "pass" if d == "pass" else "reject"
    return f'<span class="badge {cls}">{decision}</span>'


def _job_badge(status: str) -> str:
    m = {"pending": "pend", "running": "run", "done": "done",
         "completed": "done", "error": "error", "failed": "error"}
    cls = m.get(status.lower(), "pend")
    return f'<span class="badge {cls}">{status}</span>'


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    store    = _storage()
    stats    = store.get_stats()
    sessions = store.get_sessions(limit=1000)
    store.db.close()

    n_sessions  = len(sessions)
    n_total     = stats.get("total", 0)
    n_promising = stats.get("promising", 0)
    n_needs_imp = stats.get("needs_imp", 0)
    n_rejected  = stats.get("rejected", 0)
    n_passed    = n_promising + n_needs_imp
    best_sharpe = stats.get("best_sharpe")

    tiles = f"""
    <div class="grid">
      <div class="tile"><div class="tile-val">{n_sessions}</div>
        <div class="tile-label">Sessions</div></div>
      <div class="tile"><div class="tile-val">{n_total}</div>
        <div class="tile-label">Results</div></div>
      <div class="tile"><div class="tile-val">{n_passed}</div>
        <div class="tile-label">Passed Gate</div></div>
      <div class="tile"><div class="tile-val">{n_rejected}</div>
        <div class="tile-label">Rejected</div></div>
      <div class="tile"><div class="tile-val">{_fmt(best_sharpe, 2)}</div>
        <div class="tile-label">Best Sharpe</div></div>
      <div class="tile"><div class="tile-val">{_fmt(stats.get('avg_sharpe'), 3)}</div>
        <div class="tile-label">Avg Sharpe</div></div>
    </div>"""

    return _page("/", "Overview", tiles)


@app.get("/sessions", response_class=HTMLResponse)
def sessions(limit: int = Query(50, ge=1, le=500)) -> HTMLResponse:
    store    = _storage()
    sessions = store.get_sessions(limit=limit)
    store.db.close()

    if not sessions:
        return _page("/sessions", "Research Runs", "<p class='empty'>No sessions found.</p>")

    rows = "".join(f"""
    <tr>
      <td><code>{s.session_id[:16]}</code></td>
      <td>{s.started_at[:19] if s.started_at else '—'}</td>
      <td>{s.status}</td>
      <td class="r">{s.n_strategies_run}</td>
      <td class="r">{s.n_passed}</td>
      <td class="r">{s.n_rejected}</td>
      <td class="r">{f"{s.elapsed_secs:.1f}s" if s.elapsed_secs else '—'}</td>
    </tr>""" for s in sessions)

    body = f"""<div class="table-wrap"><table>
    <thead><tr>
      <th>Session</th><th>Started</th><th>Status</th>
      <th class="r">Tested</th><th class="r">Passed</th>
      <th class="r">Rejected</th><th class="r">Elapsed</th>
    </tr></thead>
    <tbody>{rows}</tbody>
    </table></div>"""

    return _page("/sessions", "Research Runs", body)


@app.get("/strategies", response_class=HTMLResponse)
def strategies(
    decision: str  = Query("", title="Filter by gate decision"),
    metric:   str  = Query("sharpe_ratio", title="Sort metric"),
    limit:    int  = Query(100, ge=1, le=1000),
) -> HTMLResponse:
    store   = _storage()
    results = store.get_best_by(metric=metric, limit=limit)
    store.db.close()

    if decision:
        results = [r for r in results if r.gate_decision.upper() == decision.upper()]

    if not results:
        return _page("/strategies", "Strategies", "<p class='empty'>No results found.</p>")

    rows = "".join(f"""
    <tr>
      <td>{r.strategy_class}</td>
      <td><code>{r.params[:40] if r.params else ''}</code></td>
      <td>{r.symbol} {r.interval}</td>
      <td class="r">{_fmt(r.sharpe_ratio, 3)}</td>
      <td class="r">{_fmt(r.cagr, 4, pct=True)}</td>
      <td class="r">{_fmt(r.max_drawdown_pct, 2, pct=True)}</td>
      <td class="r">{_fmt(r.win_rate, 2, pct=True)}</td>
      <td class="r">{r.total_trades}</td>
      <td>{_badge(r.gate_decision)}</td>
    </tr>""" for r in results)

    body = f"""<div class="table-wrap"><table>
    <thead><tr>
      <th>Class</th><th>Params</th><th>Market</th>
      <th class="r">Sharpe</th><th class="r">CAGR</th>
      <th class="r">Max DD</th><th class="r">Win Rate</th>
      <th class="r">Trades</th><th>Gate</th>
    </tr></thead>
    <tbody>{rows}</tbody>
    </table></div>"""

    return _page("/strategies", "Strategies", body)


@app.get("/reports", response_class=HTMLResponse)
def report_list() -> HTMLResponse:
    rdir = _REPORTS_DIR
    if not rdir.exists():
        return _page("/reports", "Reports", "<p class='empty'>Reports directory not found.</p>")

    files = sorted(rdir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return _page("/reports", "Reports", "<p class='empty'>No HTML reports yet.</p>")

    rows = "".join(f"""
    <tr>
      <td><a class="dl" href="/reports/view/{f.name}">{f.name}</a></td>
      <td class="r">{f.stat().st_size // 1024} KB</td>
      <td>{datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')}</td>
    </tr>""" for f in files)

    body = f"""<div class="table-wrap"><table>
    <thead><tr><th>File</th><th class="r">Size</th><th>Modified</th></tr></thead>
    <tbody>{rows}</tbody>
    </table></div>"""

    return _page("/reports", "Reports", body)


@app.get("/reports/view/{filename}")
def view_report(filename: str) -> FileResponse:
    safe = Path(filename).name
    path = _REPORTS_DIR / safe
    if not path.exists() or path.suffix != ".html":
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(str(path), media_type="text/html")


@app.get("/jobs", response_class=HTMLResponse)
def jobs(status: str = Query("", title="Filter by status"), limit: int = Query(50)) -> HTMLResponse:
    store = _storage()
    filter_status = status or None
    job_list = store.get_jobs(status=filter_status, limit=limit)
    store.db.close()

    if not job_list:
        return _page("/jobs", "Job Queue", "<p class='empty'>No jobs found.</p>")

    rows = "".join(f"""
    <tr>
      <td><code>{j.job_id[:16]}</code></td>
      <td>{j.job_type}</td>
      <td>{_job_badge(j.status)}</td>
      <td>{j.created_at[:19] if j.created_at else '—'}</td>
      <td>{j.started_at[:19]  if j.started_at  else '—'}</td>
      <td>{j.finished_at[:19] if j.finished_at else '—'}</td>
      <td class="r">{j.retry_count}</td>
    </tr>""" for j in job_list)

    body = f"""<div class="table-wrap"><table>
    <thead><tr>
      <th>Job ID</th><th>Type</th><th>Status</th>
      <th>Created</th><th>Started</th><th>Finished</th><th class="r">Retries</th>
    </tr></thead>
    <tbody>{rows}</tbody>
    </table></div>"""

    return _page("/jobs", "Job Queue", body)


@app.get("/market-data", response_class=HTMLResponse)
def market_data() -> HTMLResponse:
    data_dir = _DATA_DIR
    if not data_dir.exists():
        return _page("/market-data", "Market Data", "<p class='empty'>Data directory not found.</p>")

    rows = ""
    for sym_dir in sorted(data_dir.iterdir()):
        if not sym_dir.is_dir():
            continue
        for iv_dir in sorted(sym_dir.iterdir()):
            if not iv_dir.is_dir():
                continue
            files = list(iv_dir.glob("*.parquet"))
            size_kb = sum(f.stat().st_size for f in files) // 1024
            rows += f"""
            <tr>
              <td>{sym_dir.name}</td>
              <td>{iv_dir.name}</td>
              <td class="r">{len(files)}</td>
              <td class="r">{size_kb:,} KB</td>
            </tr>"""

    if not rows:
        return _page("/market-data", "Market Data", "<p class='empty'>No data files found.</p>")

    body = f"""<div class="table-wrap"><table>
    <thead><tr>
      <th>Symbol</th><th>Interval</th>
      <th class="r">Files</th><th class="r">Size</th>
    </tr></thead>
    <tbody>{rows}</tbody>
    </table></div>"""

    return _page("/market-data", "Market Data", body)


@app.get("/robustness", response_class=HTMLResponse)
def robustness_page(limit: int = Query(100, ge=1, le=1000)) -> HTMLResponse:
    store   = _storage()
    results = store.get_best_by(metric="sharpe_ratio", limit=limit)
    store.db.close()

    rows_with_data = [r for r in results if r.robustness_json]
    if not rows_with_data:
        return _page("/robustness", "Parameter Robustness",
                     "<p class='empty'>No robustness data yet. Run a pipeline with run_robustness=True.</p>")

    rows_with_data.sort(key=lambda r: -(r.robustness_score or 0))
    table_rows = ""
    for r in rows_with_data:
        try:
            d = json.loads(r.robustness_json)
        except Exception:
            continue
        rob  = d.get("robustness_score")
        stab = d.get("stability_score")
        rob_cls = "pass" if rob is not None and rob >= 60 else "reject"
        table_rows += f"""
        <tr>
          <td>{r.strategy_class}</td>
          <td><code>{r.params[:40] if r.params else ''}</code></td>
          <td class="r"><span class="badge {rob_cls}">{_fmt(rob, 1)}</span></td>
          <td class="r">{_fmt(stab, 1)}</td>
          <td class="r">{d.get('n_neighbors', '—')}</td>
          <td class="r">{d.get('n_profitable_neighbors', '—')}</td>
          <td class="r">{_fmt(d.get('focal_sharpe'), 3)}</td>
          <td class="r">{_fmt(d.get('neighbor_sharpe_mean'), 3)}</td>
          <td class="r">{_fmt(d.get('neighbor_sharpe_std'), 3)}</td>
          <td>{_badge(r.gate_decision)}</td>
        </tr>"""

    body = f"""<div class="table-wrap"><table>
    <thead><tr>
      <th>Strategy</th><th>Params</th>
      <th class="r">Robustness</th><th class="r">Stability</th>
      <th class="r">Neighbors</th><th class="r">Profitable</th>
      <th class="r">Focal Sh</th><th class="r">Nbr Sh μ</th><th class="r">Nbr Sh σ</th>
      <th>Gate</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
    </table></div>"""

    return _page("/robustness", "Parameter Robustness", body)


@app.get("/regimes", response_class=HTMLResponse)
def regimes_page(limit: int = Query(50, ge=1, le=500)) -> HTMLResponse:
    store   = _storage()
    results = store.get_best_by(metric="sharpe_ratio", limit=limit)
    store.db.close()

    rows_with_data = [r for r in results if r.regime_json]
    if not rows_with_data:
        return _page("/regimes", "Regime Analysis",
                     "<p class='empty'>No regime data yet.</p>")

    _REGIMES = ("Bull", "Bear", "Sideways", "HighVol", "LowVol")

    table_rows = ""
    for r in rows_with_data:
        try:
            d = json.loads(r.regime_json)
        except Exception:
            continue
        stats = d.get("regime_stats", {})
        cells = ""
        for reg in _REGIMES:
            s = stats.get(reg, {})
            n  = s.get("n_trades", 0)
            wr = s.get("win_rate")
            cells += f'<td class="r">{n}</td><td class="r">{_fmt(wr, 0, pct=True) if n else "—"}</td>'
        table_rows += f"<tr><td>{r.strategy_class}</td>{cells}</tr>"

    header_cells = "".join(
        f'<th class="r">{reg} N</th><th class="r">WR</th>'
        for reg in _REGIMES
    )

    body = f"""<div class="table-wrap"><table>
    <thead><tr><th>Strategy</th>{header_cells}</tr></thead>
    <tbody>{table_rows}</tbody>
    </table></div>"""

    return _page("/regimes", "Regime Analysis", body)


@app.get("/rolling", response_class=HTMLResponse)
def rolling_page(limit: int = Query(20, ge=1, le=100)) -> HTMLResponse:
    store   = _storage()
    results = store.get_best_by(metric="sharpe_ratio", limit=limit)
    store.db.close()

    rows_with_data = [r for r in results if r.rolling_json]
    if not rows_with_data:
        return _page("/rolling", "Rolling Metrics",
                     "<p class='empty'>No rolling metrics data yet.</p>")

    # Show summary stats for each strategy's rolling windows
    table_rows = ""
    for r in rows_with_data:
        try:
            d = json.loads(r.rolling_json)
        except Exception:
            continue
        sharpes = [x for x in d.get("sharpe", []) if x is not None]
        sorinos = [x for x in d.get("sortino", []) if x is not None]
        cagrs   = [x for x in d.get("cagr", []) if x is not None]
        dds     = [x for x in d.get("drawdown", []) if x is not None]
        window  = d.get("window", "?")
        n_pts   = len(sharpes)

        def safe_avg(lst: list) -> float | None:
            return sum(lst) / len(lst) if lst else None

        table_rows += f"""
        <tr>
          <td>{r.strategy_class}</td>
          <td class="r">{window}</td>
          <td class="r">{n_pts}</td>
          <td class="r">{_fmt(safe_avg(sharpes), 3)}</td>
          <td class="r">{_fmt(min(sharpes) if sharpes else None, 3)}</td>
          <td class="r">{_fmt(max(sharpes) if sharpes else None, 3)}</td>
          <td class="r">{_fmt(safe_avg(cagrs), 4, pct=True)}</td>
          <td class="r">{_fmt(max(dds) if dds else None, 2)}</td>
        </tr>"""

    body = f"""<p style="color:var(--muted);font-size:12px;margin-bottom:16px">
      Rolling window stats across all window positions for each strategy.</p>
    <div class="table-wrap"><table>
    <thead><tr>
      <th>Strategy</th><th class="r">Window</th><th class="r">Points</th>
      <th class="r">Avg Sharpe</th><th class="r">Min Sharpe</th><th class="r">Max Sharpe</th>
      <th class="r">Avg CAGR</th><th class="r">Max DD</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
    </table></div>"""

    return _page("/rolling", "Rolling Metrics", body)


@app.get("/bootstrap", response_class=HTMLResponse)
def bootstrap_page(limit: int = Query(20, ge=1, le=100)) -> HTMLResponse:
    store   = _storage()
    results = store.get_best_by(metric="sharpe_ratio", limit=limit)
    store.db.close()

    rows_with_data = [r for r in results if r.bootstrap_json]
    if not rows_with_data:
        return _page("/bootstrap", "Bootstrap Confidence Intervals",
                     "<p class='empty'>No bootstrap data yet.</p>")

    _METRICS = [
        ("total_return",  "Total Return",   True),
        ("trade_sharpe",  "Trade Sharpe",   False),
        ("win_rate",      "Win Rate",       True),
        ("profit_factor", "Profit Factor",  False),
        ("expectancy",    "Expectancy",     False),
        ("max_drawdown",  "Max Drawdown",   False),
    ]

    sections = ""
    for r in rows_with_data[:5]:  # cap at 5 strategies
        try:
            d = json.loads(r.bootstrap_json)
        except Exception:
            continue
        n_sim = d.get("n_simulations", "?")
        n_tr  = d.get("n_trades", "?")
        table_rows = ""
        for key, label, is_pct in _METRICS:
            ci = d.get(key, {})
            if not ci or ci.get("pct_50") is None:
                continue
            fmt = lambda v: _fmt(v, 2, pct=is_pct) if is_pct else _fmt(v, 4)
            table_rows += f"""
            <tr>
              <td>{label}</td>
              <td class="r">{fmt(ci.get('pct_5'))}</td>
              <td class="r">{fmt(ci.get('pct_50'))}</td>
              <td class="r">{fmt(ci.get('pct_95'))}</td>
            </tr>"""
        sections += f"""
        <h2>{r.strategy_class} · {n_sim} sims · {n_tr} trades</h2>
        <div class="table-wrap"><table>
        <thead><tr>
          <th>Metric</th><th class="r">5th Pct</th>
          <th class="r">Median</th><th class="r">95th Pct</th>
        </tr></thead>
        <tbody>{table_rows}</tbody>
        </table></div>
        <div style="margin-bottom:32px"></div>"""

    return _page("/bootstrap", "Bootstrap Confidence Intervals", sections)


@app.get("/degradation", response_class=HTMLResponse)
def degradation_page(limit: int = Query(100, ge=1, le=1000)) -> HTMLResponse:
    store   = _storage()
    results = store.get_best_by(metric="sharpe_ratio", limit=limit)
    store.db.close()

    rows_with_data = [r for r in results if r.degradation_json]
    if not rows_with_data:
        return _page("/degradation", "Strategy Degradation",
                     "<p class='empty'>No degradation data yet.</p>")

    rows_with_data.sort(key=lambda r: -(r.degradation_score or 0))

    table_rows = ""
    for r in rows_with_data:
        try:
            d = json.loads(r.degradation_json)
        except Exception:
            continue
        score = d.get("degradation_score")
        score_cls = "pass" if score is not None and score >= 70 else "reject"
        score_str = f"{score:.1f}" if score is not None else "—"
        table_rows += f"""
        <tr>
          <td>{r.strategy_class}</td>
          <td><code>{r.params[:30] if r.params else ''}</code></td>
          <td class="r"><span class="badge {score_cls}">{score_str}</span></td>
          <td class="r">{_fmt(d.get('first_half_sharpe'), 3)}</td>
          <td class="r">{_fmt(d.get('second_half_sharpe'), 3)}</td>
          <td class="r">{_fmt(d.get('first_half_wr'), 2, pct=True)}</td>
          <td class="r">{_fmt(d.get('second_half_wr'), 2, pct=True)}</td>
          <td class="r">{_fmt(d.get('first_half_pf'), 3)}</td>
          <td class="r">{_fmt(d.get('second_half_pf'), 3)}</td>
          <td class="r">{_fmt(d.get('first_third_sharpe'), 3)}</td>
          <td class="r">{_fmt(d.get('second_third_sharpe'), 3)}</td>
          <td class="r">{_fmt(d.get('third_third_sharpe'), 3)}</td>
        </tr>"""

    body = f"""<div class="table-wrap"><table>
    <thead><tr>
      <th>Strategy</th><th>Params</th>
      <th class="r">Score</th>
      <th class="r">H1 Sh</th><th class="r">H2 Sh</th>
      <th class="r">H1 WR</th><th class="r">H2 WR</th>
      <th class="r">H1 PF</th><th class="r">H2 PF</th>
      <th class="r">T1 Sh</th><th class="r">T2 Sh</th><th class="r">T3 Sh</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
    </table></div>"""

    return _page("/degradation", "Strategy Degradation", body)


@app.get("/settings", response_class=HTMLResponse)
def settings() -> HTMLResponse:
    rows = f"""
    <tr><td>Database</td><td><code>{_DB_PATH}</code></td></tr>
    <tr><td>Reports Dir</td><td><code>{_REPORTS_DIR}</code></td></tr>
    <tr><td>Data Dir</td><td><code>{_DATA_DIR}</code></td></tr>
    """
    env_rows = "".join(
        f"<tr><td><code>{k}</code></td><td><code>{v}</code></td></tr>"
        for k, v in sorted(os.environ.items())
        if k.startswith("EDGELAB_")
    )

    body = f"""
    <h2>Paths</h2>
    <div class="table-wrap"><table>
    <thead><tr><th>Setting</th><th>Value</th></tr></thead>
    <tbody>{rows}</tbody>
    </table></div>
    <h2 style="margin-top:32px">Environment</h2>
    <div class="table-wrap"><table>
    <thead><tr><th>Variable</th><th>Value</th></tr></thead>
    <tbody>{env_rows if env_rows else "<tr><td colspan='2' class='empty'>No EDGELAB_ vars set</td></tr>"}</tbody>
    </table></div>"""

    return _page("/settings", "Settings", body)
