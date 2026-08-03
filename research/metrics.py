"""Institutional-quality performance metrics — no scipy dependency."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class InstitutionalMetrics:
    """Complete set of institutional-quality performance statistics.

    All rate fields (CAGR, Sharpe, etc.) are annualised using
    ``bars_per_year``.  Ratio fields are dimensionless.

    Attributes
    ----------
    cagr : float
        Compound Annual Growth Rate as a fraction (0.12 = 12 %).
    sharpe_ratio : float
        Annualised Sharpe ratio (excess return / annualised volatility).
        Uses risk-free rate of 0 unless overridden in
        :func:`calculate_research_metrics`.
    sortino_ratio : float
        Annualised Sortino ratio (excess return / downside deviation).
    calmar_ratio : float
        CAGR divided by maximum drawdown magnitude.
        math.nan when max DD = 0 or CAGR period < 1 year.
    information_ratio : float
        Mean excess return over benchmark divided by tracking error.
        0.0 when benchmark returns are not provided.
    kelly_fraction : float
        Full Kelly position size as a fraction of capital.
        Capped at 1.0.  Negative Kelly is returned as-is (no edge).
    recovery_factor : float
        Net profit divided by max drawdown in absolute terms.
        0.0 when max DD = 0.
    payoff_ratio : float
        Average winner / average loser (absolute values).
        0.0 when there are no losing trades.
    profit_factor : float
        Total gross profit / total gross loss.
        math.inf when there are no losing trades.
    win_rate : float
        Fraction of trades that are winners (in [0, 1]).
    avg_trade_pnl : float
        Mean net PnL per trade in quote currency.
    avg_holding_period : float
        Mean trade duration in bars.
    avg_r_multiple : float
        Mean R-multiple (net_pnl / risk_per_trade).  Computed only when
        ``stop_loss_pct`` is available; otherwise 0.0.
    total_trades : int
        Number of completed trades.
    skewness : float
        Third standardised moment of per-bar returns.
    kurtosis : float
        Excess kurtosis (fourth standardised moment − 3) of per-bar returns.
    downside_volatility : float
        Annualised standard deviation of negative returns only.
    avg_drawdown : float
        Mean of all negative drawdown values (absolute magnitude).
    max_drawdown_pct : float
        Maximum drawdown as a positive fraction (0.15 = 15 % below peak).
    bars_per_year : int
        Annualisation factor used (e.g. 252 for daily, 8760 for hourly).
    """

    cagr              : float
    sharpe_ratio      : float
    sortino_ratio     : float
    calmar_ratio      : float
    information_ratio : float
    kelly_fraction    : float
    recovery_factor   : float
    payoff_ratio      : float
    profit_factor     : float
    win_rate          : float
    avg_trade_pnl     : float
    avg_holding_period: float
    avg_r_multiple    : float
    total_trades      : int
    skewness          : float
    kurtosis          : float
    downside_volatility: float
    avg_drawdown      : float
    max_drawdown_pct  : float
    bars_per_year     : int


def calculate_research_metrics(
    equity_curve      : pd.Series,
    trades            : Sequence,
    bars_per_year     : int   = 252,
    risk_free_rate    : float = 0.0,
    benchmark_returns : pd.Series | None = None,
) -> InstitutionalMetrics:
    """Compute institutional-grade performance metrics from an equity curve.

    Requires no external libraries beyond NumPy and Pandas.

    Args:
        equity_curve:      Bar-level portfolio equity (e.g. from
                           :class:`~portfolio.PortfolioResult`).
        trades:            Iterable of trade objects with ``.net_pnl``,
                           ``.is_winner``, ``.is_loser``, and
                           ``.holding_period`` attributes.  Compatible
                           with both ``BacktestTrade`` and
                           ``PortfolioTrade``.
        bars_per_year:     Bars in a calendar year.  Use 252 for daily
                           equity data, 8760 for hourly crypto, 365 for
                           daily crypto.
        risk_free_rate:    Annual risk-free rate as a decimal (default 0).
                           Converted to per-bar rate internally.
        benchmark_returns: Optional per-bar returns of a benchmark series
                           (same index as *equity_curve*).  Required for
                           ``information_ratio``.

    Returns:
        :class:`InstitutionalMetrics` populated with all computed values.

    Usage example
    -------------
    >>> from research import calculate_research_metrics
    >>> metrics = calculate_research_metrics(
    ...     result.equity_curve,
    ...     result.trades,
    ...     bars_per_year=8760,
    ... )
    >>> print(f"Sharpe: {metrics.sharpe_ratio:.2f}")
    >>> print(f"CAGR:   {metrics.cagr:.2%}")
    """
    if bars_per_year <= 0:
        raise ValueError(
            f"bars_per_year must be a positive integer, got {bars_per_year}"
        )
    rf_per_bar = (1 + risk_free_rate) ** (1 / bars_per_year) - 1

    # ── Returns ───────────────────────────────────────────────────────────────
    returns = equity_curve.pct_change().dropna()
    n_bars  = len(equity_curve)

    # ── CAGR ─────────────────────────────────────────────────────────────────
    starting = float(equity_curve.iloc[0])
    ending   = float(equity_curve.iloc[-1])
    n_years  = n_bars / bars_per_year

    # Suppress CAGR when the period is shorter than one full year.  The
    # annualisation exponent (1 / n_years) blows up for short periods:
    # a 5 % gain over 50 daily bars produces a CAGR > 28 %.  Rather than
    # report a meaningless number, return nan and let the display layer
    # format it as "N/A".
    if starting > 0 and ending > 0 and n_years >= 1.0:
        cagr = (ending / starting) ** (1 / n_years) - 1
    else:
        cagr = math.nan

    # ── Volatility & Sharpe ───────────────────────────────────────────────────
    excess   = returns - rf_per_bar
    ann_vol  = float(returns.std(ddof=1)) * math.sqrt(bars_per_year)
    mean_excess = float(excess.mean())

    if ann_vol > 0:
        sharpe = (mean_excess * bars_per_year) / ann_vol
    else:
        sharpe = 0.0

    # ── Sortino ───────────────────────────────────────────────────────────────
    # Semi-deviation = sqrt(mean(min(r - MAR, 0)^2)) across ALL periods
    neg_sq           = np.minimum(returns.to_numpy() - rf_per_bar, 0.0) ** 2
    mean_neg_sq      = float(neg_sq.mean())
    downside_vol_bar = math.sqrt(mean_neg_sq) if mean_neg_sq > 0 else 0.0
    ann_downside_vol = downside_vol_bar * math.sqrt(bars_per_year)

    if ann_downside_vol > 0:
        sortino = (mean_excess * bars_per_year) / ann_downside_vol
    else:
        sortino = math.inf if mean_excess > 0 else 0.0

    # ── Drawdown stats ────────────────────────────────────────────────────────
    rolling_peak = equity_curve.cummax()
    dd_curve     = (equity_curve - rolling_peak) / rolling_peak

    max_dd_pct = float(-dd_curve.min()) if len(dd_curve) > 0 else 0.0
    neg_dd     = dd_curve[dd_curve < 0]
    avg_dd     = float(-neg_dd.mean()) if len(neg_dd) > 0 else 0.0

    # ── Calmar ────────────────────────────────────────────────────────────────
    # Only valid when both CAGR is meaningful (period ≥ 1 year) AND there is
    # a non-zero drawdown.  Otherwise return nan — never 0.0 or Infinity.
    if max_dd_pct > 0 and not math.isnan(cagr):
        calmar = cagr / max_dd_pct
    else:
        calmar = math.nan

    # ── Recovery factor ───────────────────────────────────────────────────────
    # Use the rolling peak at the drawdown trough (local peak), not the global
    # peak.  After a new ATH follows a past drawdown, equity_curve.max() >
    # local_peak, causing max_dd_abs to be overstated.
    # Computed here (before the early-return) because it depends only on the
    # equity curve, not on individual trade records.
    net_profit = ending - starting
    if max_dd_pct > 0:
        trough_idx  = dd_curve.idxmin()
        local_peak  = float(rolling_peak[trough_idx])
        max_dd_abs  = max_dd_pct * local_peak
        recovery    = net_profit / max_dd_abs if max_dd_abs > 0 else 0.0
    else:
        recovery = 0.0

    # ── Information ratio ─────────────────────────────────────────────────────
    if benchmark_returns is not None and len(benchmark_returns) > 1:
        aligned_ret, aligned_bm = returns.align(benchmark_returns, join="inner")
        active   = aligned_ret - aligned_bm
        te       = float(active.std(ddof=1))
        ir       = float(active.mean() * math.sqrt(bars_per_year) / te) if te > 0 else 0.0
    else:
        ir = 0.0

    # ── Trade-level metrics ───────────────────────────────────────────────────
    trade_list = list(trades)
    total      = len(trade_list)

    if total == 0:
        return InstitutionalMetrics(
            cagr               = cagr,
            sharpe_ratio       = sharpe,
            sortino_ratio      = sortino,
            calmar_ratio       = calmar,
            information_ratio  = ir,
            kelly_fraction     = 0.0,
            recovery_factor    = recovery,
            payoff_ratio       = 0.0,
            profit_factor      = 0.0,
            win_rate           = 0.0,
            avg_trade_pnl      = 0.0,
            avg_holding_period = 0.0,
            avg_r_multiple     = 0.0,
            total_trades       = 0,
            skewness           = _skewness(returns),
            kurtosis           = _kurtosis(returns),
            downside_volatility= ann_downside_vol,
            avg_drawdown       = avg_dd,
            max_drawdown_pct   = max_dd_pct,
            bars_per_year      = bars_per_year,
        )

    pnls    = [t.net_pnl for t in trade_list]
    winners = [t for t in trade_list if t.is_winner]
    losers  = [t for t in trade_list if t.is_loser]

    win_rate        = len(winners) / total
    avg_trade_pnl   = float(np.mean(pnls))
    avg_holding     = float(np.mean([t.holding_period for t in trade_list]))

    avg_win  = float(np.mean([t.net_pnl for t in winners])) if winners else 0.0
    avg_loss = float(np.mean([abs(t.net_pnl) for t in losers])) if losers else 0.0

    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

    gross_profit = sum(t.net_pnl for t in winners)
    gross_loss   = sum(abs(t.net_pnl) for t in losers)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf

    # ── Kelly fraction ────────────────────────────────────────────────────────
    # Full Kelly = W - (1 - W) / (avg_win / avg_loss)
    if payoff > 0:
        kelly = win_rate - (1 - win_rate) / payoff
    else:
        kelly = 0.0
    kelly = min(kelly, 1.0)

    # ── R-multiple ────────────────────────────────────────────────────────────
    # Best-effort: use portfolio_equity_at_entry and SL to compute risk,
    # but those fields are not guaranteed. Fall back to 0.0.
    r_multiples = []
    for t in trade_list:
        risk = getattr(t, "risk_per_trade", None)
        if risk is None:
            eq_at_entry = getattr(t, "portfolio_equity_at_entry", None)
            if eq_at_entry and eq_at_entry > 0:
                pass  # no SL info available at this level
        if risk and risk > 0:
            r_multiples.append(t.net_pnl / risk)
    avg_r = float(np.mean(r_multiples)) if r_multiples else 0.0

    return InstitutionalMetrics(
        cagr               = cagr,
        sharpe_ratio       = sharpe,
        sortino_ratio      = sortino,
        calmar_ratio       = calmar,
        information_ratio  = ir,
        kelly_fraction     = kelly,
        recovery_factor    = recovery,
        payoff_ratio       = payoff,
        profit_factor      = profit_factor,
        win_rate           = win_rate,
        avg_trade_pnl      = avg_trade_pnl,
        avg_holding_period = avg_holding,
        avg_r_multiple     = avg_r,
        total_trades       = total,
        skewness           = _skewness(returns),
        kurtosis           = _kurtosis(returns),
        downside_volatility= ann_downside_vol,
        avg_drawdown       = avg_dd,
        max_drawdown_pct   = max_dd_pct,
        bars_per_year      = bars_per_year,
    )


# ── Pure-numpy moment calculations ────────────────────────────────────────────

def _skewness(returns: pd.Series) -> float:
    """Third standardised moment (no scipy)."""
    arr = returns.to_numpy(dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < 3:
        return 0.0
    mean  = arr.mean()
    std   = arr.std(ddof=1)
    if std == 0:
        return 0.0
    return float(((arr - mean) ** 3).mean() / std ** 3)


def _kurtosis(returns: pd.Series) -> float:
    """Excess kurtosis (fourth standardised moment − 3, no scipy)."""
    arr = returns.to_numpy(dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < 4:
        return 0.0
    mean = arr.mean()
    std  = arr.std(ddof=1)
    if std == 0:
        return 0.0
    return float(((arr - mean) ** 4).mean() / std ** 4) - 3.0
