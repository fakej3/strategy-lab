"""Generate a self-contained dark-mode HTML research report.

Single public function: generate_html_report(...) -> str
"""
from __future__ import annotations

import json
from typing import Any

from research_db.models import StrategyResult


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt(v: float | None, decimals: int = 4, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.2f}%"
    return f"{v:.{decimals}f}"


def _decision_class(d: str) -> str:
    u = d.upper()
    if u == "PROMISING":
        return "pass"
    if u == "NEEDS_IMPROVEMENT" or u == "NEEDS IMPROVEMENT":
        return "warning"
    return "reject"


def _equity_json(r: StrategyResult) -> str:
    """Return JS-safe equity curve JSON or empty array string."""
    if not r.equity_curve_json:
        return "[]"
    return r.equity_curve_json


# ── sub-sections ──────────────────────────────────────────────────────────────

def _stats_grid(
    session_id: str,
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    results: list[StrategyResult],
    n_tested: int,
    elapsed_secs: float,
) -> str:
    n_pass   = sum(1 for r in results if r.gate_decision.upper() in ("PROMISING", "NEEDS_IMPROVEMENT", "NEEDS IMPROVEMENT"))
    n_reject = n_tested - n_pass
    best_sh  = max((r.sharpe_ratio for r in results if r.sharpe_ratio), default=None)
    best_cagr= max((r.cagr         for r in results if r.cagr),         default=None)

    def tile(label: str, value: str, sub: str = "") -> str:
        return f"""
        <div class="tile">
          <div class="tile-val">{value}</div>
          <div class="tile-label">{label}</div>
          {"<div class='tile-sub'>" + sub + "</div>" if sub else ""}
        </div>"""

    return f"""
    <section class="stats-grid">
      {tile("Session", session_id[:12], f"{symbol} · {interval}")}
      {tile("Period", f"{start_date}", f"→ {end_date}")}
      {tile("Tested", str(n_tested), "strategies")}
      {tile("Passed", str(n_pass), "quality gate")}
      {tile("Rejected", str(n_reject), "below threshold")}
      {tile("Best Sharpe", _fmt(best_sh, 3))}
      {tile("Best CAGR", _fmt(best_cagr, 2, pct=True) if best_cagr else "—")}
      {tile("Runtime", f"{elapsed_secs:.1f}s")}
    </section>"""


def _strategy_table(results: list[StrategyResult]) -> str:
    if not results:
        return "<p class='empty'>No strategies to display.</p>"

    rows = ""
    for r in sorted(results, key=lambda x: -(x.sharpe_ratio or -999)):
        d = _decision_class(r.gate_decision)
        try:
            params = json.dumps(json.loads(r.params), separators=(",", ":"))
        except Exception:
            params = r.params or ""
        rows += f"""
        <tr>
          <td class="strategy-name">{r.strategy_class}</td>
          <td><code>{params}</code></td>
          <td>{r.symbol}</td>
          <td class="num">{_fmt(r.sharpe_ratio, 3)}</td>
          <td class="num">{_fmt(r.cagr, 4, pct=True)}</td>
          <td class="num">{_fmt(r.max_drawdown_pct, 2, pct=True)}</td>
          <td class="num">{_fmt(r.win_rate, 2, pct=True)}</td>
          <td class="num">{_fmt(r.profit_factor, 3)}</td>
          <td class="num">{r.total_trades}</td>
          <td><span class="badge {d}">{r.gate_decision}</span></td>
        </tr>"""

    return f"""
    <div class="table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>Strategy</th><th>Params</th><th>Symbol</th>
          <th class="num">Sharpe</th><th class="num">CAGR</th>
          <th class="num">Max DD</th><th class="num">Win Rate</th>
          <th class="num">Prof Factor</th><th class="num">Trades</th>
          <th>Gate</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </div>"""


def _chart_section(results: list[StrategyResult]) -> str:
    """Inline JS that draws equity curves for each strategy on Canvas."""
    non_reject = [r for r in results if r.gate_decision.upper() != "REJECT"]
    if not non_reject:
        return ""

    datasets = []
    for i, r in enumerate(non_reject[:8]):  # cap at 8 curves
        try:
            pts = json.loads(r.equity_curve_json or "[]")
        except Exception:
            pts = []
        if not pts:
            continue
        if pts and isinstance(pts[0], (int, float)):
            values = [float(p) for p in pts]
        else:
            values = [p.get("equity", p.get("v", 0)) for p in pts]
        label  = f"{r.strategy_class} {r.params[:30]}"
        datasets.append({"label": label, "values": values})

    if not datasets:
        return ""

    data_js = json.dumps(datasets)

    return f"""
    <section class="chart-section">
      <h2>Equity Curves — Passed Strategies</h2>
      <canvas id="eqCanvas" width="900" height="340"></canvas>
    </section>
    <script>
    (function(){{
      const datasets = {data_js};
      if (!datasets.length) return;
      const canvas  = document.getElementById('eqCanvas');
      if (!canvas) return;
      const ctx     = canvas.getContext('2d');
      const W = canvas.width, H = canvas.height;
      const PAD = {{top:24, right:20, bottom:40, left:80}};
      const colours = ['#4FC3F7','#81C784','#FFB74D','#F06292',
                       '#CE93D8','#80DEEA','#FFCC02','#FF8A65'];

      let allVals = [];
      datasets.forEach(d => allVals = allVals.concat(d.values));
      const vMin = Math.min(...allVals), vMax = Math.max(...allVals);
      const vRange = vMax - vMin || 1;
      const maxLen = Math.max(...datasets.map(d => d.values.length));

      function xOf(i)  {{ return PAD.left + (i/(maxLen-1||1))*(W-PAD.left-PAD.right); }}
      function yOf(v)  {{ return PAD.top  + (1-(v-vMin)/vRange)*(H-PAD.top-PAD.bottom); }}

      // grid
      ctx.strokeStyle = 'rgba(255,255,255,0.07)';
      ctx.lineWidth   = 1;
      for (let g=0; g<=4; g++) {{
        const y = PAD.top + g/4*(H-PAD.top-PAD.bottom);
        ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W-PAD.right, y); ctx.stroke();
        const val = vMax - g/4*vRange;
        ctx.fillStyle='rgba(255,255,255,0.45)'; ctx.font='11px monospace';
        ctx.fillText('$'+val.toFixed(0), 4, y+4);
      }}

      // curves
      datasets.forEach((d, di) => {{
        ctx.strokeStyle = colours[di % colours.length];
        ctx.lineWidth   = 1.8;
        ctx.beginPath();
        d.values.forEach((v, i) => {{
          i===0 ? ctx.moveTo(xOf(i), yOf(v)) : ctx.lineTo(xOf(i), yOf(v));
        }});
        ctx.stroke();
      }});

      // legend
      datasets.forEach((d, di) => {{
        const lx = PAD.left + di*180;
        if (lx + 160 > W) return;
        ctx.fillStyle = colours[di % colours.length];
        ctx.fillRect(lx, H-18, 12, 12);
        ctx.fillStyle = 'rgba(255,255,255,0.7)'; ctx.font='10px sans-serif';
        ctx.fillText(d.label.substring(0,22), lx+16, H-8);
      }});
    }})();
    </script>"""


def _mc_section(results: list[StrategyResult]) -> str:
    rows = [r for r in results if r.mc_median_return is not None]
    if not rows:
        return ""

    table_rows = ""
    for r in sorted(rows, key=lambda x: -(x.mc_median_return or 0)):
        table_rows += f"""
        <tr>
          <td>{r.strategy_class}</td>
          <td class="num">{_fmt(r.mc_median_return, 2, pct=True)}</td>
          <td class="num">{_fmt(r.mc_pct5_return,   2, pct=True)}</td>
          <td class="num">{_fmt(r.mc_pct95_return,  2, pct=True)}</td>
          <td class="num">{_fmt(r.mc_prob_positive, 2, pct=True)}</td>
        </tr>"""

    return f"""
    <section>
      <h2>Monte Carlo Summary</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Strategy</th>
            <th class="num">Median Return</th>
            <th class="num">5th Pct</th>
            <th class="num">95th Pct</th>
            <th class="num">Prob Positive</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      </div>
    </section>"""


def _degradation_section(results: list[StrategyResult]) -> str:
    rows = [r for r in results if r.degradation_json]
    if not rows:
        return ""

    table_rows = ""
    for r in sorted(rows, key=lambda x: -(x.degradation_score or 0)):
        try:
            d = json.loads(r.degradation_json)
        except Exception:
            continue
        score = d.get("degradation_score")
        score_str = f"{score:.1f}" if score is not None else "—"
        score_cls = "pass" if score is not None and score >= 70 else "reject"
        table_rows += f"""
        <tr>
          <td>{r.strategy_class}</td>
          <td class="num"><span class="badge {score_cls}">{score_str}</span></td>
          <td class="num">{_fmt(d.get('first_half_sharpe'), 3)}</td>
          <td class="num">{_fmt(d.get('second_half_sharpe'), 3)}</td>
          <td class="num">{_fmt(d.get('first_half_wr'),  2, pct=True)}</td>
          <td class="num">{_fmt(d.get('second_half_wr'), 2, pct=True)}</td>
          <td class="num">{_fmt(d.get('first_half_pf'),  3)}</td>
          <td class="num">{_fmt(d.get('second_half_pf'), 3)}</td>
        </tr>"""

    if not table_rows:
        return ""

    return f"""
    <section>
      <h2>Strategy Degradation Analysis</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Strategy</th>
            <th class="num">Score /100</th>
            <th class="num">H1 Sharpe</th><th class="num">H2 Sharpe</th>
            <th class="num">H1 WinRate</th><th class="num">H2 WinRate</th>
            <th class="num">H1 PF</th><th class="num">H2 PF</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      </div>
    </section>"""


def _robustness_section(results: list[StrategyResult]) -> str:
    rows = [r for r in results if r.robustness_json]
    if not rows:
        return ""

    table_rows = ""
    for r in sorted(rows, key=lambda x: -(x.robustness_score or 0)):
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
          <td class="num"><span class="badge {rob_cls}">{_fmt(rob, 1)}</span></td>
          <td class="num">{_fmt(stab, 1)}</td>
          <td class="num">{d.get('n_neighbors', '—')}</td>
          <td class="num">{d.get('n_profitable', '—')}</td>
          <td class="num">{_fmt(d.get('focal_sharpe'), 3)}</td>
          <td class="num">{_fmt(d.get('neighbor_sharpe_mean'), 3)}</td>
          <td class="num">{_fmt(d.get('neighbor_sharpe_std'), 3)}</td>
        </tr>"""

    if not table_rows:
        return ""

    return f"""
    <section>
      <h2>Parameter Robustness</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Strategy</th>
            <th class="num">Robustness</th>
            <th class="num">Stability</th>
            <th class="num">Neighbors</th>
            <th class="num">Profitable</th>
            <th class="num">Focal Sharpe</th>
            <th class="num">Nbr Sharpe μ</th>
            <th class="num">Nbr Sharpe σ</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      </div>
    </section>"""


def _bootstrap_section(results: list[StrategyResult]) -> str:
    rows = [r for r in results if r.bootstrap_json]
    if not rows:
        return ""

    # Show the single best-Sharpe strategy's CI table, or first available
    best = sorted(rows, key=lambda x: -(x.sharpe_ratio or -999))[0]
    try:
        d = json.loads(best.bootstrap_json)
    except Exception:
        return ""

    metrics = [
        ("total_return",  "Total Return", True),
        ("trade_sharpe",  "Trade Sharpe", False),
        ("win_rate",      "Win Rate",     True),
        ("profit_factor", "Profit Factor",False),
        ("expectancy",    "Expectancy",   False),
        ("max_drawdown",  "Max Drawdown", False),
    ]

    table_rows = ""
    for key, label, is_pct in metrics:
        ci = d.get(key, {})
        if not ci or ci.get("pct_50") is None:
            continue
        p5  = ci.get("pct_5")
        p50 = ci.get("pct_50")
        p95 = ci.get("pct_95")
        fmt = lambda v: _fmt(v, 2, pct=is_pct) if is_pct else _fmt(v, 4)
        table_rows += f"""
        <tr>
          <td>{label}</td>
          <td class="num">{fmt(p5)}</td>
          <td class="num">{fmt(p50)}</td>
          <td class="num">{fmt(p95)}</td>
        </tr>"""

    if not table_rows:
        return ""

    n_sim = d.get("n_simulations", "?")
    n_tr  = d.get("n_trades", "?")

    return f"""
    <section>
      <h2>Bootstrap Confidence Intervals — {best.strategy_class}</h2>
      <p style="color:var(--muted);font-size:12px;margin-bottom:16px">
        {n_sim} simulations · {n_tr} trades (5th / 50th / 95th percentile)
      </p>
      <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th class="num">5th Pct</th>
            <th class="num">Median</th>
            <th class="num">95th Pct</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      </div>
    </section>"""


def _regime_section(results: list[StrategyResult]) -> str:
    rows = [r for r in results if r.regime_json]
    if not rows:
        return ""

    best = sorted(rows, key=lambda x: -(x.sharpe_ratio or -999))[0]
    try:
        d = json.loads(best.regime_json)
    except Exception:
        return ""

    regime_stats = d.get("regime_stats", {})
    if not regime_stats:
        return ""

    table_rows = ""
    for regime, stats in regime_stats.items():
        n = stats.get("n_trades", 0)
        if n == 0:
            table_rows += f"""
            <tr>
              <td>{regime}</td>
              <td class="num">0</td>
              <td class="num">—</td><td class="num">—</td>
              <td class="num">—</td><td class="num">—</td>
            </tr>"""
        else:
            wr = stats.get("win_rate")
            pf = stats.get("profit_factor")
            table_rows += f"""
            <tr>
              <td>{regime}</td>
              <td class="num">{n}</td>
              <td class="num">{_fmt(wr, 2, pct=True)}</td>
              <td class="num">{_fmt(pf, 3)}</td>
              <td class="num">{_fmt(stats.get('avg_pnl'), 2)}</td>
              <td class="num">{_fmt(stats.get('total_pnl'), 2)}</td>
            </tr>"""

    return f"""
    <section>
      <h2>Regime Performance — {best.strategy_class}</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Regime</th>
            <th class="num">Trades</th>
            <th class="num">Win Rate</th>
            <th class="num">Prof Factor</th>
            <th class="num">Avg PnL</th>
            <th class="num">Total PnL</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      </div>
    </section>"""


def _wf_section(results: list[StrategyResult]) -> str:
    rows = [r for r in results if r.walk_forward_return is not None]
    if not rows:
        return ""

    table_rows = ""
    for r in sorted(rows, key=lambda x: -(x.walk_forward_return or 0)):
        table_rows += f"""
        <tr>
          <td>{r.strategy_class}</td>
          <td class="num">{_fmt(r.walk_forward_return, 2, pct=True)}</td>
          <td class="num">{_fmt(r.sharpe_ratio, 3)}</td>
          <td><span class="badge {_decision_class(r.gate_decision)}">{r.gate_decision}</span></td>
        </tr>"""

    return f"""
    <section>
      <h2>Walk-Forward Results</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Strategy</th>
            <th class="num">WF Return</th>
            <th class="num">Sharpe</th>
            <th>Gate</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      </div>
    </section>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #0d1117;
  --surface:  #161b22;
  --border:   #30363d;
  --text:     #e6edf3;
  --muted:    #8b949e;
  --accent:   #4FC3F7;
  --pass:     #238636;
  --pass-fg:  #3fb950;
  --reject:   #6e2c2c;
  --reject-fg:#f85149;
  --font-mono: 'Courier New', Courier, monospace;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.6;
}

header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 24px 40px;
}
header h1 { font-size: 22px; font-weight: 700; color: var(--accent); letter-spacing: -0.3px; }
header p  { color: var(--muted); font-size: 12px; margin-top: 4px; }

main { max-width: 1200px; margin: 0 auto; padding: 32px 40px; }

section { margin-bottom: 48px; }
h2 {
  font-size: 15px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted);
  border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 20px;
}

/* Stat tiles */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 16px;
  margin-bottom: 48px;
}
.tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.tile-val   { font-size: 24px; font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }
.tile-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }
.tile-sub   { font-size: 11px; color: var(--muted); }

/* Tables */
.table-wrap { overflow-x: auto; }
.data-table {
  width: 100%; border-collapse: collapse;
  font-size: 13px; font-variant-numeric: tabular-nums;
}
.data-table th {
  background: var(--surface); color: var(--muted);
  text-align: left; padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
  white-space: nowrap;
}
.data-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.data-table tr:hover td { background: rgba(255,255,255,0.03); }
.data-table td.num { text-align: right; }
.data-table th.num { text-align: right; }
.strategy-name { font-weight: 600; white-space: nowrap; }
.data-table code {
  font-family: var(--font-mono); font-size: 11px;
  color: var(--muted); white-space: nowrap;
}

/* Badges */
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
}
.badge.pass   { background: var(--pass); color: var(--pass-fg); }
.badge.reject { background: var(--reject); color: var(--reject-fg); }

/* Charts */
.chart-section canvas {
  display: block;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 100%; max-width: 900px;
}

.empty { color: var(--muted); font-style: italic; padding: 24px 0; }

footer {
  text-align: center; color: var(--muted); font-size: 11px;
  padding: 32px; border-top: 1px solid var(--border); margin-top: 48px;
}
"""


# ── entry point ───────────────────────────────────────────────────────────────

def generate_html_report(
    session_id: str,
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    results: list[StrategyResult],
    n_tested: int,
    elapsed_secs: float,
) -> str:
    """Return a complete self-contained HTML string for one research run."""
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    stats       = _stats_grid(session_id, symbol, interval, start_date, end_date,
                              results, n_tested, elapsed_secs)
    charts      = _chart_section(results)
    table       = _strategy_table(results)
    mc          = _mc_section(results)
    wf          = _wf_section(results)
    degradation = _degradation_section(results)
    robustness  = _robustness_section(results)
    bootstrap   = _bootstrap_section(results)
    regime      = _regime_section(results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EdgeLab Research Report — {symbol} {interval}</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <h1>EdgeLab Research Report</h1>
    <p>{symbol} · {interval} · {start_date} → {end_date} · Generated {generated_at}</p>
  </header>
  <main>
    {stats}
    {charts}
    <section>
      <h2>Strategy Rankings</h2>
      {table}
    </section>
    {wf}
    {mc}
    {degradation}
    {robustness}
    {bootstrap}
    {regime}
  </main>
  <footer>EdgeLab · Session {session_id[:16]}</footer>
</body>
</html>"""
