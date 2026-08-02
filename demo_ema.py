"""
EMA Crossover demo — BTCUSDT 1h, 2022-01-01 to 2023-12-31.

Pipeline:
  get_bars() → EMACrossover.generate_signals() → BacktestExecutor.run()
             → calculate_metrics() → evaluate_gate() → render_terminal()

BacktestTrade.profit (= net_pnl in USD) feeds calculate_metrics(); the
profit_unit is set to "$" so the Quality Gate uses absolute thresholds.

Network fallback: if Binance is unreachable, synthetic OHLCV bars are
generated with geometric Brownian motion (σ≈0.6%/h, drift=0, seed=42)
so results are reproducible.
"""
from __future__ import annotations

import sys
from datetime import date, timezone, timedelta, datetime

import numpy as np
import pandas as pd

from data import get_bars, BinanceProvider, BarStore
from engine import BacktestExecutor, EngineConfig
from strategies import EMACrossover
from pipeline.metrics import calculate_metrics
from pipeline.gate import evaluate_gate
from pipeline.report import render_terminal

# ── Config ────────────────────────────────────────────────────────────────────

SYMBOL    = "BTCUSDT"
INTERVAL  = "1h"
FROM_DATE = date(2022, 1, 1)
TO_DATE   = date(2023, 12, 31)

STRATEGY = EMACrossover(fast=20, slow=50)

ENGINE_CONFIG = EngineConfig(
    position_size   = 1.0,    # 1 BTC per trade
    stop_loss_pct   = None,   # pure signal exits — crossover drives all exits
    take_profit_pct = None,
    fee_rate        = 0.001,  # 0.10% Binance taker
    slippage_pct    = 0.0005, # 0.05% per side
)

# ── Data ──────────────────────────────────────────────────────────────────────

def _synthetic_bars(from_date: date, to_date: date, seed: int = 42) -> pd.DataFrame:
    """
    Geometric Brownian motion OHLCV bars.
    σ = 0.6% / hour  (≈ BTC daily vol 3% / √24)
    drift = 0 (neutral)
    Starting price = 46,000
    """
    rng   = np.random.default_rng(seed)
    start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc)
    end   = datetime(to_date.year, to_date.month, to_date.day, 23, tzinfo=timezone.utc)
    index = pd.date_range(start, end, freq="1h", tz="UTC")
    n     = len(index)

    sigma  = 0.006        # 0.6% per hour
    S0     = 46_000.0
    log_returns = rng.normal(0, sigma, n)
    closes  = S0 * np.exp(np.cumsum(log_returns))

    # Intrabar high/low: ±U[0, σ] around close
    half_spread = rng.uniform(0, sigma, n) * closes
    opens       = np.roll(closes, 1)
    opens[0]    = S0
    highs       = np.maximum(opens, closes) + half_spread
    lows        = np.minimum(opens, closes) - half_spread
    volumes     = rng.uniform(500, 2000, n)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def _fetch_bars() -> tuple[pd.DataFrame, str]:
    """Returns (bars, source_label)."""
    try:
        bars = get_bars(
            symbol    = SYMBOL,
            interval  = INTERVAL,
            from_date = FROM_DATE,
            to_date   = TO_DATE,
            provider  = BinanceProvider(),
            store     = BarStore("market_data"),
        )
        return bars, "Binance"
    except Exception as exc:
        print(f"Note: Binance unavailable ({type(exc).__name__}); using synthetic GBM data.\n",
              file=sys.stderr)
        return _synthetic_bars(FROM_DATE, TO_DATE), "Synthetic (GBM, σ=0.6%/h, seed=42)"


# ── Main ──────────────────────────────────────────────────────────────────────

print(f"Fetching {SYMBOL} {INTERVAL} {FROM_DATE} → {TO_DATE} …")
bars, source = _fetch_bars()
print(f"Source  : {source}")
print(f"Bars    : {len(bars):,}  ({bars.index[0]} → {bars.index[-1]})")
print()

executor = BacktestExecutor(ENGINE_CONFIG)
trades   = executor.run(bars, STRATEGY)

print(f"Trades  : {len(trades)} round-trip trades")
print()

if not trades:
    print("No trades generated — cannot produce a Quality Gate report.", file=sys.stderr)
    sys.exit(1)

metrics = calculate_metrics(trades, profit_unit="$")
gate    = evaluate_gate(metrics)
report  = render_terminal(metrics, gate)

print(report)
