"""Pure-Python reference engine for differential testing.

Completely independent of NumPy, Pandas, and production code.
Implements identical fill mechanics to BacktestExecutor:

- BUY at bar T → fill at bar T+1 open
- SL/TP checked at start of every held bar including entry bar
- SL wins when both fire on the same bar
- Gap-down SL: fill at min(sl_level, bar_open)
- Gap-up TP:   fill at max(tp_level, bar_open)
- End-of-data: fill at last bar close
- Exit signal:  fill at next bar open

Equity curve mirrors build_equity_curve in portfolio/engine.py:
- Flat regions use starting_capital + cumulative_realized
- In-position bars: starting_capital + realized + (close - entry_fill) * size
- Exit bar: starting_capital + realized + net_pnl
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RefTrade:
    trade_number: int
    entry_bar: int
    exit_bar: int
    entry_price: float   # fill price (after slippage)
    exit_price: float    # fill price (after slippage)
    size: float
    entry_fee: float
    exit_fee: float
    entry_slippage: float
    exit_slippage: float
    gross_pnl: float
    net_pnl: float
    exit_reason: str     # "signal" | "stop_loss" | "take_profit" | "end_of_data"
    holding_period: int  # exit_bar - entry_bar


def run_reference(
    bars: list[tuple[float, float, float, float]],  # (open, high, low, close)
    signals: list[str],
    *,
    fee_rate: float = 0.0,
    slippage_pct: float = 0.0,
    position_size: float = 1.0,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    starting_capital: float = 10_000.0,
) -> tuple[list[RefTrade], list[float]]:
    """Run reference engine; return (trades, equity_curve)."""
    n = len(bars)
    if n == 0:
        return [], []

    in_position = False
    entry_bar_idx = -1
    entry_price   = 0.0
    entry_fee_val = 0.0
    entry_slip    = 0.0
    sl_level: float | None = None
    tp_level: float | None = None

    trades: list[RefTrade] = []
    trade_count = 0

    def _open(bar_idx: int, raw_open: float) -> None:
        nonlocal in_position, entry_bar_idx, entry_price, entry_fee_val
        nonlocal entry_slip, sl_level, tp_level
        fill       = raw_open * (1.0 + slippage_pct)
        in_position    = True
        entry_bar_idx  = bar_idx
        entry_price    = fill
        entry_fee_val  = fill * position_size * fee_rate
        entry_slip     = raw_open * slippage_pct * position_size
        sl_level = fill * (1.0 - stop_loss_pct)   if stop_loss_pct    is not None else None
        tp_level = fill * (1.0 + take_profit_pct) if take_profit_pct  is not None else None

    def _close(bar_idx: int, raw_exit: float, reason: str) -> None:
        nonlocal in_position, trade_count
        exit_fill  = raw_exit * (1.0 - slippage_pct)
        x_slip     = raw_exit * slippage_pct * position_size
        exit_fee   = exit_fill * position_size * fee_rate
        gross      = (exit_fill - entry_price) * position_size
        net        = gross - entry_fee_val - exit_fee
        trade_count += 1
        trades.append(RefTrade(
            trade_number  = trade_count,
            entry_bar     = entry_bar_idx,
            exit_bar      = bar_idx,
            entry_price   = entry_price,
            exit_price    = exit_fill,
            size          = position_size,
            entry_fee     = entry_fee_val,
            exit_fee      = exit_fee,
            entry_slippage = entry_slip,
            exit_slippage  = x_slip,
            gross_pnl     = gross,
            net_pnl       = net,
            exit_reason   = reason,
            holding_period = bar_idx - entry_bar_idx,
        ))
        in_position = False

    for i in range(n):
        bar_open, bar_high, bar_low, bar_close = bars[i]
        sig = signals[i]

        # 1. SL/TP check for current position
        if in_position:
            sl_hit = sl_level is not None and bar_low  <= sl_level
            tp_hit = tp_level is not None and bar_high >= tp_level

            if sl_hit:
                raw = min(sl_level, bar_open)  # type: ignore[arg-type]
                _close(i, raw, "stop_loss")
            elif tp_hit:
                raw = max(tp_level, bar_open)  # type: ignore[arg-type]
                _close(i, raw, "take_profit")

        # 2. Fill signal at next bar open
        if i + 1 >= n:
            break

        raw_next = bars[i + 1][0]

        if not in_position and sig == "BUY":
            _open(i + 1, raw_next)
        elif in_position and sig in ("EXIT", "SELL"):
            _close(i + 1, raw_next, "signal")

    # 3. End-of-data liquidation
    if in_position:
        last_close = bars[-1][3]
        _close(n - 1, last_close, "end_of_data")

    equity = _build_equity(bars, trades, starting_capital)
    return trades, equity


def _build_equity(
    bars: list[tuple[float, float, float, float]],
    trades: list[RefTrade],
    starting_capital: float,
) -> list[float]:
    """Mirror of portfolio.engine.build_equity_curve in pure Python."""
    n = len(bars)
    equity = [0.0] * n
    sorted_t = sorted(trades, key=lambda t: t.entry_bar)
    realized = 0.0
    prev_end = 0

    for t in sorted_t:
        entry = t.entry_bar
        exit_ = t.exit_bar

        # Flat region before this trade
        for i in range(prev_end, entry):
            equity[i] = starting_capital + realized

        # In-position bars: unrealized PnL from bar close
        if entry < exit_:
            for i in range(entry, exit_):
                bar_close  = bars[i][3]
                unrealized = (bar_close - t.entry_price) * t.size
                equity[i]  = starting_capital + realized + unrealized

        # Exit bar: position closed
        if exit_ < n:
            equity[exit_] = starting_capital + realized + t.net_pnl

        realized += t.net_pnl
        prev_end  = exit_ + 1

    # Tail flat region
    for i in range(prev_end, n):
        equity[i] = starting_capital + realized

    return equity
