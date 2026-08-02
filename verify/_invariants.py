"""Financial invariant checks for PortfolioResult objects.

Each invariant is a mathematical property that must hold for every valid
backtest result, regardless of strategy, market, or configuration.
Violations indicate accounting bugs, not edge-case inputs.
"""
from __future__ import annotations

import math
from typing import NamedTuple

from portfolio.models import PortfolioResult, PortfolioTrade


class Violation(NamedTuple):
    invariant: str
    message  : str


def check_all(result: PortfolioResult) -> list[Violation]:
    """Check all financial invariants; return list of violations (empty = clean)."""
    v: list[Violation] = []
    v.extend(_i1_ending_equity(result))
    v.extend(_i2_peak_ge_ending(result))
    v.extend(_i3_drawdown_bounds(result))
    v.extend(_i4_max_dd_consistency(result))
    v.extend(_i5_no_nan_curves(result))
    v.extend(_i6_positive_equity(result))
    v.extend(_i7_exposure_bounds(result))
    v.extend(_i8_total_return(result))
    for t in result.trades:
        v.extend(_i9_trade(t))
    return v


# ── Portfolio-level invariants ─────────────────────────────────────────────────

def _i1_ending_equity(r: PortfolioResult) -> list[Violation]:
    """I1: ending_equity = starting_capital + net_profit."""
    expected = r.starting_capital + r.net_profit
    if not _close(r.ending_equity, expected):
        return [Violation(
            "I1_ENDING_EQUITY",
            f"ending_equity={r.ending_equity} != starting_capital + net_profit = {expected}",
        )]
    return []


def _i2_peak_ge_ending(r: PortfolioResult) -> list[Violation]:
    """I2: peak_equity >= ending_equity (ATH is never below final equity)."""
    if r.peak_equity < r.ending_equity - 1e-9:
        return [Violation(
            "I2_PEAK_GE_ENDING",
            f"peak_equity={r.peak_equity} < ending_equity={r.ending_equity}",
        )]
    return []


def _i3_drawdown_bounds(r: PortfolioResult) -> list[Violation]:
    """I3: all drawdown values in (−1, 0]; drawdown cannot exceed 100% loss."""
    dd  = r.drawdown_curve
    out = []
    if (dd < -1.0 - 1e-9).any():
        out.append(Violation(
            "I3_DD_LOWER",
            f"drawdown < -1.0: min={float(dd.min()):.8f}",
        ))
    if (dd > 1e-9).any():
        out.append(Violation(
            "I3_DD_UPPER",
            f"drawdown > 0: max={float(dd.max()):.8f}",
        ))
    return out


def _i4_max_dd_consistency(r: PortfolioResult) -> list[Violation]:
    """I4: max_drawdown_pct matches the minimum of the drawdown curve."""
    if len(r.drawdown_curve) == 0:
        return []
    from_curve = float(-r.drawdown_curve.min())
    if not _close(r.max_drawdown_pct, from_curve, rel=1e-6):
        return [Violation(
            "I4_MAX_DD_CONSISTENCY",
            f"max_drawdown_pct={r.max_drawdown_pct:.8f} != from_curve={from_curve:.8f}",
        )]
    return []


def _i5_no_nan_curves(r: PortfolioResult) -> list[Violation]:
    """I5: no NaN or Inf values in equity, balance, or drawdown curves."""
    out = []
    for name, curve in [
        ("equity_curve",   r.equity_curve),
        ("balance_curve",  r.balance_curve),
        ("drawdown_curve", r.drawdown_curve),
    ]:
        if curve.isna().any():
            out.append(Violation(f"I5_NAN_{name.upper()}", f"{name} contains NaN"))
        import numpy as np
        if np.isinf(curve.to_numpy()).any():
            out.append(Violation(f"I5_INF_{name.upper()}", f"{name} contains Inf"))
    return out


def _i6_positive_equity(r: PortfolioResult) -> list[Violation]:
    """I6: equity curve is strictly positive (no bankruptcy bar)."""
    if (r.equity_curve <= 0).any():
        return [Violation(
            "I6_POSITIVE_EQUITY",
            f"equity_curve ≤ 0: min={float(r.equity_curve.min()):.4f}",
        )]
    return []


def _i7_exposure_bounds(r: PortfolioResult) -> list[Violation]:
    """I7: exposure fraction in [0, 1]."""
    if not (0.0 - 1e-9 <= r.exposure_pct <= 1.0 + 1e-9):
        return [Violation(
            "I7_EXPOSURE",
            f"exposure_pct={r.exposure_pct} not in [0, 1]",
        )]
    return []


def _i8_total_return(r: PortfolioResult) -> list[Violation]:
    """I8: total_return = (ending_equity − starting_capital) / starting_capital."""
    expected = (r.ending_equity - r.starting_capital) / r.starting_capital
    if not _close(r.total_return, expected):
        return [Violation(
            "I8_TOTAL_RETURN",
            f"total_return={r.total_return} != (ending-start)/start = {expected}",
        )]
    return []


# ── Trade-level invariants ─────────────────────────────────────────────────────

def _i9_trade(t: PortfolioTrade) -> list[Violation]:
    """I9: per-trade accounting invariants."""
    out = []

    # Prices positive
    if t.entry_price <= 0:
        out.append(Violation("I9_ENTRY_PRICE", f"entry_price={t.entry_price} ≤ 0"))
    if t.exit_price <= 0:
        out.append(Violation("I9_EXIT_PRICE", f"exit_price={t.exit_price} ≤ 0"))

    # Size positive
    if t.size <= 0:
        out.append(Violation("I9_SIZE", f"size={t.size} ≤ 0"))

    # Fees non-negative
    if t.entry_fee < -1e-12:
        out.append(Violation("I9_ENTRY_FEE", f"entry_fee={t.entry_fee} < 0"))
    if t.exit_fee < -1e-12:
        out.append(Violation("I9_EXIT_FEE", f"exit_fee={t.exit_fee} < 0"))

    # Slippage costs non-negative
    if t.entry_slippage < -1e-12:
        out.append(Violation("I9_ENTRY_SLIP", f"entry_slippage={t.entry_slippage} < 0"))
    if t.exit_slippage < -1e-12:
        out.append(Violation("I9_EXIT_SLIP", f"exit_slippage={t.exit_slippage} < 0"))

    # Holding period >= 0
    if t.holding_period < 0:
        out.append(Violation("I9_HOLDING", f"holding_period={t.holding_period} < 0"))

    # gross_pnl = (exit_price - entry_price) * size
    expected_gross = (t.exit_price - t.entry_price) * t.size
    if not _close(t.gross_pnl, expected_gross):
        out.append(Violation(
            "I9_GROSS_PNL",
            f"gross_pnl={t.gross_pnl} != (exit-entry)*size = {expected_gross:.6f}",
        ))

    # net_pnl = gross_pnl - entry_fee - exit_fee
    expected_net = t.gross_pnl - t.entry_fee - t.exit_fee
    if not _close(t.net_pnl, expected_net):
        out.append(Violation(
            "I9_NET_PNL",
            f"net_pnl={t.net_pnl} != gross - fees = {expected_net:.6f}",
        ))

    # No NaN or Inf in monetary fields
    for fname in ("entry_price", "exit_price", "gross_pnl", "net_pnl",
                  "entry_fee", "exit_fee"):
        val = getattr(t, fname)
        if math.isnan(val):
            out.append(Violation(f"I9_NAN_{fname.upper()}", f"{fname} is NaN"))
        elif math.isinf(val):
            out.append(Violation(f"I9_INF_{fname.upper()}", f"{fname} is Inf"))

    return out


# ── Helper ─────────────────────────────────────────────────────────────────────

def _close(a: float, b: float, rel: float = 1e-9, abs_: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)
