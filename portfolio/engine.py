"""Portfolio engine — wraps BacktestExecutor with capital tracking and sizing."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.executor import BacktestExecutor
from engine.models import BacktestTrade, EngineConfig
from engine.strategy import StrategyBase

from .models import PortfolioConfig, PortfolioResult, PortfolioTrade, SizingMode


class PortfolioEngine:
    """Capital-aware backtest engine.

    Wraps ``BacktestExecutor`` to add:

    * Portfolio capital tracking (equity, balance, drawdown at every bar).
    * Dynamic position sizing: fixed units, % of equity, fixed dollar, or
      fractional (Kelly-style).
    * Equity curve generation including unrealized PnL while a position is open.

    The underlying ``BacktestExecutor`` is completely untouched.  All fill
    semantics (signal-at-T fills at T+1 open, SL/TP logic, gap handling,
    end-of-data liquidation) are identical to a direct engine run.

    Sizing model
    ------------
    FIXED_UNITS: EngineConfig.position_size is set directly from
    PortfolioConfig.position_size.  All trade fields are as produced by the
    engine.

    All other modes: the engine runs with position_size=1.0 (unit size).
    For each resulting trade, the actual size is computed from the portfolio
    equity at entry time and the sizing rule.  All monetary fields (PnL, fees,
    slippage) are scaled proportionally: they are all linear in position size
    when entry/exit prices are held fixed.

    This approach correctly compounds portfolio equity across trades, while
    keeping the execution engine stateless and generic.

    Usage example
    -------------
    >>> from portfolio import PortfolioEngine, PortfolioConfig, SizingMode
    >>> from engine import EngineConfig
    >>> from strategies import EMACrossover
    >>>
    >>> cfg = PortfolioConfig(starting_capital=100_000)
    >>> engine = PortfolioEngine(cfg)
    >>> result = engine.run(bars, EMACrossover(), EngineConfig())
    >>> print(f"Return: {result.total_return:.2%}")
    >>> print(f"Max DD: {result.max_drawdown_pct:.2%}")
    """

    def __init__(self, portfolio_config: PortfolioConfig | None = None) -> None:
        self.config = portfolio_config or PortfolioConfig()

    def run(
        self,
        bars         : pd.DataFrame,
        strategy     : StrategyBase,
        engine_config: EngineConfig | None = None,
    ) -> PortfolioResult:
        """Run strategy over bars and return portfolio-level results.

        Args:
            bars:          OHLCV DataFrame.  Passed unchanged to BacktestExecutor.
            strategy:      Any StrategyBase implementation.
            engine_config: Execution parameters (fees, slippage, SL/TP).
                           When sizing_mode is not FIXED_UNITS, position_size
                           in this config is overridden to 1.0 internally.

        Returns:
            PortfolioResult with equity/balance/drawdown curves and scaled trades.

        Raises:
            ValueError: Propagated from BacktestExecutor if bars or signals are
                        structurally invalid.
        """
        cfg = self.config
        ec  = engine_config or EngineConfig()

        if cfg.sizing_mode == SizingMode.FIXED_UNITS:
            run_cfg = EngineConfig(
                position_size   = cfg.position_size,
                stop_loss_pct   = ec.stop_loss_pct,
                take_profit_pct = ec.take_profit_pct,
                fee_rate        = ec.fee_rate,
                slippage_pct    = ec.slippage_pct,
            )
            raw_trades = BacktestExecutor(run_cfg).run(bars, strategy)
            ptrades    = _to_portfolio_trades(raw_trades, cfg.starting_capital)
        else:
            unit_cfg = EngineConfig(
                position_size   = 1.0,
                stop_loss_pct   = ec.stop_loss_pct,
                take_profit_pct = ec.take_profit_pct,
                fee_rate        = ec.fee_rate,
                slippage_pct    = ec.slippage_pct,
            )
            raw_trades = BacktestExecutor(unit_cfg).run(bars, strategy)
            ptrades    = _apply_dynamic_sizing(raw_trades, cfg, ec)

        if not ptrades:
            flat = pd.Series(cfg.starting_capital, index=bars.index, dtype=float)
            zero = pd.Series(0.0, index=bars.index, dtype=float)
            return PortfolioResult(
                starting_capital = cfg.starting_capital,
                ending_equity    = cfg.starting_capital,
                peak_equity      = cfg.starting_capital,
                net_profit       = 0.0,
                total_return     = 0.0,
                max_drawdown_pct = 0.0,
                max_drawdown_abs = 0.0,
                exposure_pct     = 0.0,
                equity_curve     = flat,
                balance_curve    = flat.copy(),
                drawdown_curve   = zero,
                trades           = [],
            )

        equity_curve   = build_equity_curve(bars, ptrades, cfg.starting_capital)
        balance_curve  = build_balance_curve(bars, ptrades, cfg.starting_capital)
        drawdown_curve = build_drawdown_curve(equity_curve)

        peak_equity      = float(equity_curve.max())
        ending_equity    = float(equity_curve.iloc[-1])
        net_profit       = ending_equity - cfg.starting_capital
        total_return     = net_profit / cfg.starting_capital
        max_drawdown_pct = float(-drawdown_curve.min())
        max_drawdown_abs = max_drawdown_pct * peak_equity

        n_bars   = max(len(bars), 1)
        in_bars  = sum(t.exit_bar - t.entry_bar + 1 for t in ptrades)
        exposure = min(in_bars / n_bars, 1.0)

        return PortfolioResult(
            starting_capital = cfg.starting_capital,
            ending_equity    = ending_equity,
            peak_equity      = peak_equity,
            net_profit       = net_profit,
            total_return     = total_return,
            max_drawdown_pct = max_drawdown_pct,
            max_drawdown_abs = max_drawdown_abs,
            exposure_pct     = exposure,
            equity_curve     = equity_curve,
            balance_curve    = balance_curve,
            drawdown_curve   = drawdown_curve,
            trades           = ptrades,
        )


# ── Equity curve builders (also importable from research.curves) ───────────────

def build_equity_curve(
    bars            : pd.DataFrame,
    trades          : list[PortfolioTrade],
    starting_capital: float,
) -> pd.Series:
    """Build a bar-level equity curve including unrealized PnL.

    For bars outside any position: equity = starting_capital + cumulative_realized.
    For bars inside a position (entry_bar ≤ i < exit_bar): adds unrealized PnL
    computed from bar's close price.
    At exit_bar: position is closed; equity reflects net_pnl realized.

    Args:
        bars:             OHLCV DataFrame (provides index and close prices).
        trades:           PortfolioTrade list in any order (sorted internally).
        starting_capital: Initial portfolio value.

    Returns:
        pd.Series indexed by bars.index with name "equity".
    """
    n = len(bars)
    if n == 0:
        return pd.Series(dtype=float, name="equity")

    closes       = bars["close"].to_numpy(dtype=float)
    equity_arr   = np.empty(n, dtype=float)
    sorted_t     = sorted(trades, key=lambda t: t.entry_bar)

    realized = 0.0
    prev_end = 0

    for trade in sorted_t:
        entry = trade.entry_bar
        exit_ = trade.exit_bar

        # Flat region before this trade
        if prev_end < entry:
            equity_arr[prev_end:entry] = starting_capital + realized

        # In-position bars: unrealized PnL from bar close
        if entry < exit_ and exit_ <= n:
            unrealized = (closes[entry:exit_] - trade.entry_price) * trade.size
            equity_arr[entry:exit_] = starting_capital + realized + unrealized

        # Exit bar: position closed; net_pnl realized
        if exit_ < n:
            equity_arr[exit_] = starting_capital + realized + trade.net_pnl

        realized += trade.net_pnl
        prev_end  = exit_ + 1

    # Tail flat region after last trade
    if prev_end < n:
        equity_arr[prev_end:] = starting_capital + realized

    return pd.Series(equity_arr, index=bars.index, name="equity")


def build_balance_curve(
    bars            : pd.DataFrame,
    trades          : list[PortfolioTrade],
    starting_capital: float,
) -> pd.Series:
    """Build a realized-only balance curve (steps at trade exits; flat otherwise).

    Unlike equity_curve, this does not include unrealized PnL.  It shows the
    liquidated portfolio value if all positions were closed at each bar.

    Returns:
        pd.Series indexed by bars.index with name "balance".
    """
    n = len(bars)
    if n == 0:
        return pd.Series(dtype=float, name="balance")

    balance_arr   = np.empty(n, dtype=float)
    sorted_t      = sorted(trades, key=lambda t: t.exit_bar)
    realized      = 0.0
    ti            = 0

    for i in range(n):
        while ti < len(sorted_t) and sorted_t[ti].exit_bar <= i:
            realized += sorted_t[ti].net_pnl
            ti += 1
        balance_arr[i] = starting_capital + realized

    return pd.Series(balance_arr, index=bars.index, name="balance")


def build_drawdown_curve(equity_curve: pd.Series) -> pd.Series:
    """Compute rolling drawdown from equity peak as a fraction in [−1, 0].

    A value of −0.15 means equity is 15 % below its previous all-time high.

    Returns:
        pd.Series indexed identically to equity_curve, named "drawdown".
    """
    rolling_peak = equity_curve.cummax()
    drawdown     = (equity_curve - rolling_peak) / rolling_peak
    drawdown.name = "drawdown"
    return drawdown


# ── Private helpers ────────────────────────────────────────────────────────────

def _to_portfolio_trades(
    raw_trades      : list[BacktestTrade],
    starting_capital: float,
) -> list[PortfolioTrade]:
    """Copy BacktestTrade objects to PortfolioTrade, tracking running equity."""
    equity = starting_capital
    result = []
    for t in raw_trades:
        result.append(PortfolioTrade(
            trade_number              = t.trade_number,
            direction                 = t.direction,
            entry_time                = t.entry_time,
            exit_time                 = t.exit_time,
            entry_bar                 = t.entry_bar,
            exit_bar                  = t.exit_bar,
            entry_price               = t.entry_price,
            exit_price                = t.exit_price,
            size                      = t.size,
            entry_fee                 = t.entry_fee,
            exit_fee                  = t.exit_fee,
            entry_slippage            = t.entry_slippage,
            exit_slippage             = t.exit_slippage,
            gross_pnl                 = t.gross_pnl,
            net_pnl                   = t.net_pnl,
            exit_reason               = t.exit_reason,
            holding_period            = t.holding_period,
            portfolio_equity_at_entry = equity,
        ))
        equity += t.net_pnl
    return result


def _apply_dynamic_sizing(
    raw_trades    : list[BacktestTrade],
    portfolio_cfg : PortfolioConfig,
    engine_cfg    : EngineConfig,
) -> list[PortfolioTrade]:
    """Scale unit-size (size=1) trades to actual portfolio sizing.

    Each trade's actual size is computed from the portfolio equity at the time
    of entry.  All monetary fields scale linearly with size.
    """
    equity = portfolio_cfg.starting_capital
    result = []

    for t in raw_trades:
        actual_size = _compute_size(
            equity          = equity,
            entry_price     = t.entry_price,
            sizing_mode     = portfolio_cfg.sizing_mode,
            equity_fraction = portfolio_cfg.equity_fraction,
            trade_capital   = portfolio_cfg.trade_capital,
            fraction        = portfolio_cfg.fraction,
        )

        gross_pnl = (t.exit_price - t.entry_price) * actual_size
        entry_fee = t.entry_price * actual_size * engine_cfg.fee_rate
        exit_fee  = t.exit_price  * actual_size * engine_cfg.fee_rate
        net_pnl   = gross_pnl - entry_fee - exit_fee

        result.append(PortfolioTrade(
            trade_number              = t.trade_number,
            direction                 = t.direction,
            entry_time                = t.entry_time,
            exit_time                 = t.exit_time,
            entry_bar                 = t.entry_bar,
            exit_bar                  = t.exit_bar,
            entry_price               = t.entry_price,
            exit_price                = t.exit_price,
            size                      = actual_size,
            entry_fee                 = entry_fee,
            exit_fee                  = exit_fee,
            entry_slippage            = t.entry_slippage * actual_size,
            exit_slippage             = t.exit_slippage  * actual_size,
            gross_pnl                 = gross_pnl,
            net_pnl                   = net_pnl,
            exit_reason               = t.exit_reason,
            holding_period            = t.holding_period,
            portfolio_equity_at_entry = equity,
        ))
        equity += net_pnl

    return result


def _compute_size(
    equity         : float,
    entry_price    : float,
    sizing_mode    : SizingMode,
    equity_fraction: float,
    trade_capital  : float,
    fraction       : float,
) -> float:
    """Return the position size (in base-asset units) for a given sizing mode."""
    if entry_price <= 0.0:
        return 0.0
    if sizing_mode == SizingMode.PCT_OF_EQUITY:
        return max((equity * equity_fraction) / entry_price, 0.0)
    if sizing_mode == SizingMode.FIXED_DOLLAR:
        return max(trade_capital / entry_price, 0.0)
    if sizing_mode == SizingMode.FRACTIONAL:
        return max((equity * fraction) / entry_price, 0.0)
    return 1.0  # unreachable for FIXED_UNITS (handled before this function)
