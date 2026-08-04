"""Daily HTML report generator for the paper trading bot."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import BotStorage

log = logging.getLogger("strategy_lab.bot.report")


def generate_daily_report(storage: BotStorage, reports_dir: str) -> Path:
    """Generate a daily HTML performance report and return its path."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = storage.get_daily_stats_for(today)
    balance_history = storage.get_balance_history(limit=288)  # last 24h of 5-min snapshots
    closed_positions = [
        p for p in storage.get_positions(limit=500)
        if p.get("status") == "closed"
        and (p.get("closed_at") or "").startswith(today)
    ]

    report_path = Path(reports_dir) / f"bot_report_{today}.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    html = _render_report(today, stats, balance_history, closed_positions)
    report_path.write_text(html, encoding="utf-8")
    log.info("Daily report written to %s", report_path)
    return report_path


def _render_report(
    date: str,
    stats: dict | None,
    balance_history: list[dict],
    trades: list[dict],
) -> str:
    s = stats or {}
    net_pnl      = s.get("net_pnl", 0.0)
    n_trades     = s.get("n_trades", 0)
    win_rate     = s.get("win_rate")
    pf           = s.get("profit_factor")
    total_fees   = s.get("total_fees", 0.0)
    start_equity = s.get("starting_equity", 0.0)
    end_equity   = s.get("ending_equity",   0.0)
    max_dd       = s.get("max_drawdown", 0.0)

    pnl_color = "#3fb950" if net_pnl >= 0 else "#f85149"

    # Equity sparkline data
    eq_points = [b["equity"] for b in balance_history if b.get("equity")]
    sparkline_json = json.dumps(eq_points)

    # Trade rows
    trade_rows = ""
    for t in trades:
        pnl = t.get("realized_pnl", 0.0) or 0.0
        color = "#3fb950" if pnl >= 0 else "#f85149"
        trade_rows += (
            f"<tr>"
            f"<td>{t.get('symbol','')}</td>"
            f"<td>{t.get('direction','')}</td>"
            f"<td class='r'>{t.get('size',0):.5f}</td>"
            f"<td class='r'>{t.get('avg_entry_price',0):.2f}</td>"
            f"<td class='r'>{t.get('exit_price',0):.2f}</td>"
            f"<td class='r' style='color:{color}'>{pnl:+.4f}</td>"
            f"<td>{(t.get('closed_at') or '')[:19]}</td>"
            f"</tr>"
        )
    if not trade_rows:
        trade_rows = "<tr><td colspan='7' class='empty'>No trades today</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Bot Daily Report — {date}</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,sans-serif;
      font-size:14px;padding:40px;max-width:1000px;margin:0 auto}}
    h1{{font-size:22px;font-weight:700;margin-bottom:8px;color:#e6edf3}}
    .date{{color:#8b949e;font-size:13px;margin-bottom:32px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
      gap:16px;margin-bottom:40px}}
    .tile{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}}
    .tile-val{{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}}
    .tile-label{{font-size:11px;color:#8b949e;text-transform:uppercase;
      letter-spacing:.05em;margin-top:4px}}
    canvas{{display:block;width:100%;height:120px;margin-bottom:40px;
      border:1px solid #30363d;border-radius:8px;background:#161b22}}
    table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:40px;
      font-variant-numeric:tabular-nums}}
    th{{background:#161b22;color:#8b949e;text-align:left;padding:8px 12px;
      border-bottom:1px solid #30363d;font-size:11px;text-transform:uppercase}}
    td{{padding:8px 12px;border-bottom:1px solid #30363d}}
    td.r,th.r{{text-align:right}}
    .empty{{color:#8b949e;font-style:italic;padding:24px 0}}
    .footer{{color:#8b949e;font-size:12px;margin-top:40px;border-top:1px solid #30363d;
      padding-top:16px}}
  </style>
</head>
<body>
  <h1>Bot Daily Report</h1>
  <div class="date">{date} UTC</div>

  <div class="grid">
    <div class="tile">
      <div class="tile-val" style="color:{pnl_color}">{net_pnl:+.2f}</div>
      <div class="tile-label">Net P&amp;L (USDT)</div>
    </div>
    <div class="tile">
      <div class="tile-val" style="color:#4FC3F7">{n_trades}</div>
      <div class="tile-label">Trades</div>
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
      <div class="tile-val" style="color:#f85149">{max_dd:.2%}</div>
      <div class="tile-label">Max Drawdown</div>
    </div>
    <div class="tile">
      <div class="tile-val">{total_fees:.4f}</div>
      <div class="tile-label">Total Fees</div>
    </div>
    <div class="tile">
      <div class="tile-val">{end_equity:,.2f}</div>
      <div class="tile-label">Closing Equity</div>
    </div>
  </div>

  <canvas id="eq_chart"></canvas>
  <script>
    (function(){{
      const data = {sparkline_json};
      if(!data.length) return;
      const canvas = document.getElementById('eq_chart');
      const ctx = canvas.getContext('2d');
      canvas.width = canvas.offsetWidth;
      canvas.height = 120;
      const W=canvas.width, H=canvas.height, pad=8;
      const min=Math.min(...data), max=Math.max(...data), range=max-min||1;
      ctx.strokeStyle='#4FC3F7'; ctx.lineWidth=1.5;
      ctx.beginPath();
      data.forEach((v,i)=>{{
        const x=pad+(W-2*pad)*i/(data.length-1||1);
        const y=H-pad-(H-2*pad)*(v-min)/range;
        i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
      }});
      ctx.stroke();
      // fill
      ctx.lineTo(pad+(W-2*pad), H-pad);
      ctx.lineTo(pad, H-pad);
      ctx.closePath();
      ctx.fillStyle='rgba(79,195,247,0.08)';
      ctx.fill();
    }})();
  </script>

  <h2 style="font-size:13px;font-weight:600;text-transform:uppercase;
    color:#8b949e;border-bottom:1px solid #30363d;padding-bottom:8px;margin-bottom:16px">
    Trades
  </h2>
  <table>
    <thead>
      <tr>
        <th>Symbol</th><th>Dir</th><th class="r">Size</th>
        <th class="r">Entry</th><th class="r">Exit</th>
        <th class="r">P&amp;L</th><th>Closed At</th>
      </tr>
    </thead>
    <tbody>{trade_rows}</tbody>
  </table>

  <div class="footer">Generated at {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC</div>
</body>
</html>"""
