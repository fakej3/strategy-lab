"""Bot dashboard — FastAPI pages for live bot monitoring.

Pages
-----
/bot                Overview (equity, PnL, uptime, candles)
/bot/orders         Recent orders
/bot/positions      Open + closed positions
/bot/portfolio      Equity curve + balance history
/bot/runtime        Runtime metrics (memory, CPU, latency)
/bot/logs           Recent errors
/bot/risk           Risk limits and daily stats
/bot/performance    Performance metrics

These pages attach to the existing Research Lab dashboard app (reports/dashboard.py)
or can run standalone via ``bot_dashboard_app`` below.

Standalone usage::

    uvicorn bot.dashboard:bot_dashboard_app --host 0.0.0.0 --port 8001
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .storage import BotStorage

# ── App setup ─────────────────────────────────────────────────────────────────

bot_dashboard_app = FastAPI(title="Bot Dashboard", docs_url=None, redoc_url=None)

_BOT_DB = Path(os.environ.get("BOT_DB", "bot.db"))


def _storage() -> BotStorage:
    s = BotStorage(str(_BOT_DB))
    s.connect()
    return s


# ── Shared CSS + layout ───────────────────────────────────────────────────────

_NAV_LINKS = [
    ("/bot",             "Overview"),
    ("/bot/orders",      "Orders"),
    ("/bot/positions",   "Positions"),
    ("/bot/portfolio",   "Portfolio"),
    ("/bot/runtime",     "Runtime"),
    ("/bot/logs",        "Error Log"),
    ("/bot/risk",        "Risk"),
    ("/bot/performance", "Performance"),
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
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:16px;margin-bottom:32px}
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
.badge.filled{background:var(--pass-bg);color:var(--pass-fg)}
.badge.cancelled,.badge.rejected,.badge.expired{background:var(--reject-bg);color:var(--reject-fg)}
.badge.accepted,.badge.new{background:#1c2433;color:#79c0ff}
.badge.open{background:var(--pass-bg);color:var(--pass-fg)}
.badge.closed{background:var(--surface);color:var(--muted)}
.badge.long{background:#1a2e1a;color:#3fb950}
.badge.short{background:#2e1a1a;color:#f85149}
.empty{color:var(--muted);font-style:italic;padding:24px 0}
code{font-family:'Courier New',monospace;font-size:11px;color:var(--muted)}
.pnl-pos{color:#3fb950}
.pnl-neg{color:#f85149}
canvas{display:block;width:100%;height:140px;
  border:1px solid var(--border);border-radius:8px;
  background:var(--surface);margin-bottom:32px}
.refresh{float:right;font-size:12px;color:var(--muted);margin-top:-28px}
"""


def _page(path: str, title: str, body: str) -> HTMLResponse:
    nav = "".join(
        f'<a href="{href}" class="{"active" if href == path else ""}">{label}</a>'
        for href, label in _NAV_LINKS
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>{title} — Bot</title>
  <style>{_CSS}</style>
</head>
<body>
  <nav>
    <div class="logo">TradingBot</div>
    {nav}
  </nav>
  <main>
    <h1>{title}</h1>
    <div class="refresh">Auto-refreshes every 30s</div>
    {body}
  </main>
</body>
</html>"""
    return HTMLResponse(html)


# ── Helper formatters ─────────────────────────────────────────────────────────

def _fmt(v, d: int = 4, pct: bool = False) -> str:
    if v is None:
        return "–"
    try:
        f = float(v)
        return f"{f:.{d}f}{'%' if pct else ''}"
    except (TypeError, ValueError):
        return str(v)


def _pnl_class(v) -> str:
    try:
        return "pnl-pos" if float(v) >= 0 else "pnl-neg"
    except (TypeError, ValueError):
        return ""


def _badge(status: str) -> str:
    cls = status.lower()
    return f'<span class="badge {cls}">{status}</span>'


def _ts(s: str | None) -> str:
    if not s:
        return "–"
    return s[:19].replace("T", " ")


# ── Routes ────────────────────────────────────────────────────────────────────

@bot_dashboard_app.get("/bot", response_class=HTMLResponse)
async def bot_overview() -> HTMLResponse:
    st = _storage()
    hb = st.get_last_heartbeat()
    daily = st.get_daily_stats(limit=1)
    today_stats = daily[0] if daily else {}
    balance = st.get_balance_history(limit=2)
    latest_bal = balance[-1] if balance else {}

    uptime_s = hb.get("uptime_s", 0) if hb else 0
    uptime_h = uptime_s / 3600

    equity   = latest_bal.get("equity", 0.0)
    cash     = latest_bal.get("cash", 0.0)
    unrealized = latest_bal.get("unrealized", 0.0)
    drawdown = latest_bal.get("drawdown", 0.0)

    net_pnl  = today_stats.get("net_pnl", 0.0)
    n_trades = today_stats.get("n_trades", 0)
    win_rate = today_stats.get("win_rate")

    pnl_color = "var(--pass-fg)" if (net_pnl or 0) >= 0 else "var(--reject-fg)"

    body = f"""
    <div class="grid">
      <div class="tile">
        <div class="tile-val">{equity:,.2f}</div>
        <div class="tile-label">Equity (USDT)</div>
      </div>
      <div class="tile">
        <div class="tile-val" style="color:{pnl_color}">{net_pnl:+.2f}</div>
        <div class="tile-label">Today's P&L</div>
      </div>
      <div class="tile">
        <div class="tile-val">{unrealized:+.2f}</div>
        <div class="tile-label">Unrealized</div>
      </div>
      <div class="tile">
        <div class="tile-val" style="color:var(--reject-fg)">{drawdown:.2%}</div>
        <div class="tile-label">Drawdown</div>
      </div>
      <div class="tile">
        <div class="tile-val">{n_trades}</div>
        <div class="tile-label">Trades Today</div>
      </div>
      <div class="tile">
        <div class="tile-val">{f"{win_rate:.1%}" if win_rate else "–"}</div>
        <div class="tile-label">Win Rate</div>
      </div>
      <div class="tile">
        <div class="tile-val">{uptime_h:.1f}h</div>
        <div class="tile-label">Uptime</div>
      </div>
      <div class="tile">
        <div class="tile-val">{hb.get("candles_recv", 0) if hb else 0}</div>
        <div class="tile-label">Candles</div>
      </div>
    </div>
    """
    return _page("/bot", "Overview", body)


@bot_dashboard_app.get("/bot/orders", response_class=HTMLResponse)
async def bot_orders() -> HTMLResponse:
    st = _storage()
    orders = st.get_orders(limit=100)

    rows = ""
    for o in orders:
        rows += (
            f"<tr>"
            f"<td><code>{o['order_id'][:8]}</code></td>"
            f"<td>{o['symbol']}</td>"
            f"<td>{o['side']}</td>"
            f"<td>{o['order_type']}</td>"
            f"<td>{_badge(o['status'])}</td>"
            f"<td class='r'>{_fmt(o.get('qty'), 5)}</td>"
            f"<td class='r'>{_fmt(o.get('avg_fill_price'), 2)}</td>"
            f"<td class='r'>{_fmt(o.get('total_fee'), 4)}</td>"
            f"<td>{_ts(o.get('updated_at'))}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='9' class='empty'>No orders yet</td></tr>"

    body = f"""
    <h2>Recent Orders</h2>
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>ID</th><th>Symbol</th><th>Side</th><th>Type</th><th>Status</th>
        <th class="r">Qty</th><th class="r">Avg Fill</th><th class="r">Fee</th><th>Updated</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    """
    return _page("/bot/orders", "Orders", body)


@bot_dashboard_app.get("/bot/positions", response_class=HTMLResponse)
async def bot_positions() -> HTMLResponse:
    st = _storage()
    positions = st.get_positions(limit=100)

    rows = ""
    for p in positions:
        pnl = p.get("realized_pnl", 0.0) or 0.0
        rows += (
            f"<tr>"
            f"<td>{p['symbol']}</td>"
            f"<td>{_badge(p['direction'])}</td>"
            f"<td>{_badge(p['status'])}</td>"
            f"<td class='r'>{_fmt(p.get('size'), 5)}</td>"
            f"<td class='r'>{_fmt(p.get('avg_entry_price'), 2)}</td>"
            f"<td class='r'>{_fmt(p.get('exit_price'), 2)}</td>"
            f"<td class='r {_pnl_class(pnl)}'>{pnl:+.4f}</td>"
            f"<td>{_ts(p.get('opened_at'))}</td>"
            f"<td>{_ts(p.get('closed_at'))}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='9' class='empty'>No positions yet</td></tr>"

    body = f"""
    <h2>Positions (last 100)</h2>
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Symbol</th><th>Dir</th><th>Status</th>
        <th class="r">Size</th><th class="r">Entry</th><th class="r">Exit</th>
        <th class="r">P&L</th><th>Opened</th><th>Closed</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    """
    return _page("/bot/positions", "Positions", body)


@bot_dashboard_app.get("/bot/portfolio", response_class=HTMLResponse)
async def bot_portfolio() -> HTMLResponse:
    st = _storage()
    history = st.get_balance_history(limit=500)

    eq_data   = json.dumps([h["equity"]   for h in history])
    cash_data = json.dumps([h["cash"]     for h in history])
    dd_data   = json.dumps([h["drawdown"] for h in history])

    latest = history[-1] if history else {}

    body = f"""
    <div class="grid">
      <div class="tile">
        <div class="tile-val">{latest.get("equity", 0):,.2f}</div>
        <div class="tile-label">Equity</div>
      </div>
      <div class="tile">
        <div class="tile-val">{latest.get("cash", 0):,.2f}</div>
        <div class="tile-label">Cash</div>
      </div>
      <div class="tile">
        <div class="tile-val">{latest.get("unrealized", 0):+.2f}</div>
        <div class="tile-label">Unrealized</div>
      </div>
      <div class="tile">
        <div class="tile-val" style="color:var(--reject-fg)">{latest.get("drawdown",0):.2%}</div>
        <div class="tile-label">Drawdown</div>
      </div>
    </div>

    <h2>Equity Curve</h2>
    <canvas id="eq_chart"></canvas>

    <h2>Drawdown</h2>
    <canvas id="dd_chart"></canvas>

    <script>
    function drawChart(id, data, color, fill){{
      const canvas=document.getElementById(id);
      if(!canvas||!data.length) return;
      canvas.width=canvas.offsetWidth; canvas.height=140;
      const ctx=canvas.getContext('2d');
      const W=canvas.width,H=canvas.height,pad=8;
      const min=Math.min(...data),max=Math.max(...data),range=max-min||1;
      ctx.strokeStyle=color; ctx.lineWidth=1.5;
      ctx.beginPath();
      data.forEach((v,i)=>{{
        const x=pad+(W-2*pad)*i/(data.length-1||1);
        const y=H-pad-(H-2*pad)*(v-min)/range;
        i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
      }});
      ctx.stroke();
      if(fill){{
        ctx.lineTo(pad+(W-2*pad),H-pad);
        ctx.lineTo(pad,H-pad);
        ctx.closePath();
        ctx.fillStyle=fill; ctx.fill();
      }}
    }}
    drawChart('eq_chart',{eq_data},'#4FC3F7','rgba(79,195,247,0.08)');
    drawChart('dd_chart',{dd_data},'#f85149','rgba(248,81,73,0.08)');
    </script>
    """
    return _page("/bot/portfolio", "Portfolio", body)


@bot_dashboard_app.get("/bot/runtime", response_class=HTMLResponse)
async def bot_runtime() -> HTMLResponse:
    st = _storage()
    history = st.get_runtime_history(limit=60)
    latest = history[-1] if history else {}

    lat_data = json.dumps([h.get("avg_latency_ms") or 0 for h in history])

    body = f"""
    <div class="grid">
      <div class="tile">
        <div class="tile-val">{latest.get("uptime_s",0)/3600:.1f}h</div>
        <div class="tile-label">Uptime</div>
      </div>
      <div class="tile">
        <div class="tile-val">{latest.get("candles_total",0):,}</div>
        <div class="tile-label">Candles</div>
      </div>
      <div class="tile">
        <div class="tile-val">{latest.get("reconnects",0)}</div>
        <div class="tile-label">Reconnects</div>
      </div>
      <div class="tile">
        <div class="tile-val">{latest.get("missed_candles",0)}</div>
        <div class="tile-label">Missed Candles</div>
      </div>
      <div class="tile">
        <div class="tile-val">{_fmt(latest.get("memory_mb"),1)} MB</div>
        <div class="tile-label">Memory</div>
      </div>
      <div class="tile">
        <div class="tile-val">{_fmt(latest.get("cpu_pct"),1)}%</div>
        <div class="tile-label">CPU</div>
      </div>
      <div class="tile">
        <div class="tile-val">{_fmt(latest.get("avg_latency_ms"),1)} ms</div>
        <div class="tile-label">Avg Latency</div>
      </div>
    </div>

    <h2>Candle Processing Latency (ms)</h2>
    <canvas id="lat_chart"></canvas>
    <script>
    (function(){{
      const data={lat_data};
      if(!data.length) return;
      const canvas=document.getElementById('lat_chart');
      canvas.width=canvas.offsetWidth; canvas.height=140;
      const ctx=canvas.getContext('2d');
      const W=canvas.width,H=canvas.height,pad=8;
      const min=0,max=Math.max(...data,1),range=max-min;
      ctx.strokeStyle='#f0b429'; ctx.lineWidth=1.5;
      ctx.beginPath();
      data.forEach((v,i)=>{{
        const x=pad+(W-2*pad)*i/(data.length-1||1);
        const y=H-pad-(H-2*pad)*(v-min)/range;
        i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
      }});
      ctx.stroke();
    }})();
    </script>
    """
    return _page("/bot/runtime", "Runtime", body)


@bot_dashboard_app.get("/bot/logs", response_class=HTMLResponse)
async def bot_logs() -> HTMLResponse:
    st = _storage()
    errors = st.get_errors(limit=100)

    rows = ""
    for e in errors:
        rows += (
            f"<tr>"
            f"<td>{_ts(e.get('ts'))}</td>"
            f"<td>{e.get('source','')}</td>"
            f"<td>{e.get('message','')}</td>"
            f"<td><code>{(e.get('detail') or '')[:80]}</code></td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='4' class='empty'>No errors logged</td></tr>"

    body = f"""
    <h2>Error Log (last 100)</h2>
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Timestamp</th><th>Source</th><th>Message</th><th>Detail</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    """
    return _page("/bot/logs", "Error Log", body)


@bot_dashboard_app.get("/bot/risk", response_class=HTMLResponse)
async def bot_risk() -> HTMLResponse:
    st = _storage()
    daily = st.get_daily_stats(limit=30)

    rows = ""
    for d in daily:
        net = d.get("net_pnl", 0.0) or 0.0
        rows += (
            f"<tr>"
            f"<td>{d.get('date_utc','')}</td>"
            f"<td>{d.get('n_trades',0)}</td>"
            f"<td>{d.get('n_winners',0)}</td>"
            f"<td>{d.get('n_losers',0)}</td>"
            f"<td class='r {_pnl_class(net)}'>{net:+.2f}</td>"
            f"<td class='r'>{_fmt(d.get('total_fees'),4)}</td>"
            f"<td class='r' style='color:var(--reject-fg)'>{_fmt(d.get('max_drawdown'),2)}%</td>"
            f"<td class='r'>{_fmt(d.get('win_rate'),1)}%</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='8' class='empty'>No daily stats yet</td></tr>"

    body = f"""
    <h2>Daily Statistics (last 30 days)</h2>
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Date</th><th>Trades</th><th>Winners</th><th>Losers</th>
        <th class="r">Net P&L</th><th class="r">Fees</th>
        <th class="r">Max DD</th><th class="r">Win Rate</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    """
    return _page("/bot/risk", "Risk & Daily Stats", body)


@bot_dashboard_app.get("/bot/performance", response_class=HTMLResponse)
async def bot_performance() -> HTMLResponse:
    st = _storage()
    daily = st.get_daily_stats(limit=90)

    total_trades  = sum(d.get("n_trades", 0) for d in daily)
    total_winners = sum(d.get("n_winners", 0) for d in daily)
    total_pnl     = sum(d.get("net_pnl", 0.0) or 0 for d in daily)
    total_fees    = sum(d.get("total_fees", 0.0) or 0 for d in daily)
    win_rate      = total_winners / total_trades if total_trades > 0 else None

    gross_profit = sum(d.get("gross_profit", 0.0) or 0 for d in daily)
    gross_loss   = abs(sum(d.get("gross_loss", 0.0) or 0 for d in daily))
    pf           = gross_profit / gross_loss if gross_loss > 0 else None

    pnl_color = "var(--pass-fg)" if total_pnl >= 0 else "var(--reject-fg)"

    body = f"""
    <div class="grid">
      <div class="tile">
        <div class="tile-val" style="color:{pnl_color}">{total_pnl:+.2f}</div>
        <div class="tile-label">Total Net P&L</div>
      </div>
      <div class="tile">
        <div class="tile-val">{total_trades}</div>
        <div class="tile-label">Total Trades</div>
      </div>
      <div class="tile">
        <div class="tile-val">{f"{win_rate:.1%}" if win_rate is not None else "–"}</div>
        <div class="tile-label">Win Rate</div>
      </div>
      <div class="tile">
        <div class="tile-val">{f"{pf:.2f}" if pf is not None else "–"}</div>
        <div class="tile-label">Profit Factor</div>
      </div>
      <div class="tile">
        <div class="tile-val">{gross_profit:.2f}</div>
        <div class="tile-label">Gross Profit</div>
      </div>
      <div class="tile">
        <div class="tile-val" style="color:var(--reject-fg)">{gross_loss:.2f}</div>
        <div class="tile-label">Gross Loss</div>
      </div>
      <div class="tile">
        <div class="tile-val">{total_fees:.4f}</div>
        <div class="tile-label">Total Fees</div>
      </div>
    </div>
    <p style="color:var(--muted);font-size:13px">Statistics computed from last 90 days of daily records.</p>
    """
    return _page("/bot/performance", "Performance", body)
