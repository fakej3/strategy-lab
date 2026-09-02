"""Portfolio engine — wraps BacktestExecutor with capital tracking and sizing."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from engine.executor import BacktestExecutor
from engine.models import BacktestTrade, EngineConfig
from engine.strategy import StrategyBase

from .models import PortfolioConfig, PortfolioResult, PortfolioTrade, SizingMode


class PortfolioEngine:
    """Capital-aware backtest engine.

    V2 portfolio accounting is cash-only by default: a long entry must fund
    its filled notional plus entry fee from available equity. Leverage is
    intentionally not implicit; it must be added as an explicit portfolio
    policy rather than emerging accidentally from sizing parameters.
    """

    def __init__(self, portfolio_config: PortfolioConfig | None = None) -> None:
        self.config = portfolio_config or PortfolioConfig()

    def run(self, bars: pd.DataFrame, strategy: StrategyBase, engine_config: EngineConfig | None = None) -> PortfolioResult:
        cfg = self.config
        ec = engine_config or EngineConfig()

        if cfg.sizing_mode == SizingMode.FIXED_UNITS:
            run_cfg = EngineConfig(position_size=cfg.position_size, stop_loss_pct=ec.stop_loss_pct, take_profit_pct=ec.take_profit_pct, fee_rate=ec.fee_rate, slippage_pct=ec.slippage_pct)
            raw_trades = BacktestExecutor(run_cfg).run(bars, strategy)
            ptrades = _to_portfolio_trades(raw_trades, cfg.starting_capital, ec)
        else:
            unit_cfg = EngineConfig(position_size=1.0, stop_loss_pct=ec.stop_loss_pct, take_profit_pct=ec.take_profit_pct, fee_rate=ec.fee_rate, slippage_pct=ec.slippage_pct)
            raw_trades = BacktestExecutor(unit_cfg).run(bars, strategy)
            ptrades = _apply_dynamic_sizing(raw_trades, cfg, ec)

        if not ptrades:
            flat = pd.Series(cfg.starting_capital, index=bars.index, dtype=float)
            zero = pd.Series(0.0, index=bars.index, dtype=float)
            return PortfolioResult(starting_capital=cfg.starting_capital, ending_equity=cfg.starting_capital, peak_equity=cfg.starting_capital, net_profit=0.0, total_return=0.0, max_drawdown_pct=0.0, max_drawdown_abs=0.0, exposure_pct=0.0, equity_curve=flat, balance_curve=flat.copy(), drawdown_curve=zero, trades=[])

        equity_curve = build_equity_curve(bars, ptrades, cfg.starting_capital)
        balance_curve = pd.Series(dtype=float) if cfg.summary_only else build_balance_curve(bars, ptrades, cfg.starting_capital)
        drawdown_curve = build_drawdown_curve(equity_curve)

        peak_equity = float(equity_curve.max())
        ending_equity = float(equity_curve.iloc[-1])
        net_profit = ending_equity - cfg.starting_capital
        total_return = net_profit / cfg.starting_capital
        max_drawdown_pct = float(-drawdown_curve.min())
        if max_drawdown_pct > 0:
            trough_idx = drawdown_curve.idxmin()
            rolling_peak = equity_curve.cummax()
            local_peak = float(rolling_peak.loc[trough_idx])
            max_drawdown_abs = float(local_peak - equity_curve.loc[trough_idx])
        else:
            max_drawdown_abs = 0.0

        n_bars = max(len(bars), 1)
        in_bars = sum(t.exit_bar - t.entry_bar + 1 for t in ptrades)
        exposure = min(in_bars / n_bars, 1.0)

        if cfg.summary_only:
            empty = pd.Series(dtype=float)
            equity_curve = empty
            balance_curve = empty.copy()
            drawdown_curve = empty.copy()

        return PortfolioResult(starting_capital=cfg.starting_capital, ending_equity=ending_equity, peak_equity=peak_equity, net_profit=net_profit, total_return=total_return, max_drawdown_pct=max_drawdown_pct, max_drawdown_abs=max_drawdown_abs, exposure_pct=exposure, equity_curve=equity_curve, balance_curve=balance_curve, drawdown_curve=drawdown_curve, trades=ptrades)


def build_equity_curve(bars: pd.DataFrame, trades: list[PortfolioTrade], starting_capital: float) -> pd.Series:
    """Build mark-to-market equity with transaction costs recognized at fill time."""
    n = len(bars)
    if n == 0:
        return pd.Series(dtype=float, name="equity")
    closes = bars["close"].to_numpy(dtype=float)
    equity_arr = np.empty(n, dtype=float)
    sorted_t = sorted(trades, key=lambda t: t.entry_bar)
    realized = 0.0
    prev_end = 0
    for trade in sorted_t:
        entry = trade.entry_bar
        exit_ = trade.exit_bar
        if prev_end < entry:
            equity_arr[prev_end:entry] = starting_capital + realized
        entry_fee = float(trade.entry_fee)
        if entry < exit_ and exit_ <= n:
            direction_sign = _direction_sign(trade.direction)
            unrealized = (closes[entry:exit_] - trade.entry_price) * trade.size * direction_sign
            equity_arr[entry:exit_] = starting_capital + realized - entry_fee + unrealized
        if exit_ < n:
            equity_arr[exit_] = starting_capital + realized + trade.net_pnl
        realized += trade.net_pnl
        prev_end = exit_ + 1
    if prev_end < n:
        equity_arr[prev_end:] = starting_capital + realized
    return pd.Series(equity_arr, index=bars.index, name="equity")


def _direction_sign(direction: str) -> float:
    """Return the P&L sign for a position direction, rejecting ambiguity."""
    normalized = str(direction).strip().lower()
    if normalized == "long":
        return 1.0
    if normalized == "short":
        return -1.0
    raise ValueError(f"unsupported trade direction: {direction!r}")


def build_balance_curve(bars: pd.DataFrame, trades: list[PortfolioTrade], starting_capital: float) -> pd.Series:
    """Build a realized-only balance curve (steps at trade exits; flat otherwise)."""
    n = len(bars)
    if n == 0:
        return pd.Series(dtype=float, name="balance")
    balance_arr = np.empty(n, dtype=float)
    sorted_t = sorted(trades, key=lambda t: t.exit_bar)
    realized = 0.0
    ti = 0
    for i in range(n):
        while ti < len(sorted_t) and sorted_t[ti].exit_bar <= i:
            realized += sorted_t[ti].net_pnl
            ti += 1
        balance_arr[i] = starting_capital + realized
    return pd.Series(balance_arr, index=bars.index, name="balance")


def build_drawdown_curve(equity_curve: pd.Series) -> pd.Series:
    """Compute rolling drawdown from equity peak as a fraction in [−1, 0]."""
    rolling_peak = equity_curve.cummax()
    drawdown = (equity_curve - rolling_peak) / rolling_peak.clip(lower=1e-10)
    drawdown.name = "drawdown"
    return drawdown


def _validate_entry_funding(equity: float, entry_price: float, size: float, fee_rate: float) -> None:
    """Reject an entry whose filled notional plus entry fee exceeds equity.

    This is deliberately fail-closed. Silently clipping a requested position
    would make the reported strategy different from the strategy that was
    tested. Leverage, margin, and borrowing belong to a future explicit policy.
    """
    if not all(math.isfinite(x) for x in (equity, entry_price, size, fee_rate)):
        raise ValueError("entry funding inputs must all be finite")
    if equity <= 0.0:
        raise ValueError(f"cannot open position with non-positive equity: {equity!r}")
    if entry_price <= 0.0 or size <= 0.0:
        raise ValueError("entry_price and size must be > 0")
    entry_notional = entry_price * size
    entry_fee = entry_notional * fee_rate
    required_cash = entry_notional + entry_fee
    if required_cash > equity * (1.0 + 1e-12):
        raise ValueError(f"insufficient capital for entry: required={required_cash:.12g}, available={equity:.12g}")


def _to_portfolio_trades(raw_trades: list[BacktestTrade], starting_capital: float, engine_cfg: EngineConfig) -> list[PortfolioTrade]:
    equity = starting_capital
    result = []
    for t in raw_trades:
        _validate_entry_funding(equity, t.entry_price, t.size, engine_cfg.fee_rate)
        result.append(PortfolioTrade(trade_number=t.trade_number, direction=t.direction, entry_time=t.entry_time, exit_time=t.exit_time, entry_bar=t.entry_bar, exit_bar=t.exit_bar, entry_price=t.entry_price, exit_price=t.exit_price, size=t.size, entry_fee=t.entry_fee, exit_fee=t.exit_fee, entry_slippage=t.entry_slippage, exit_slippage=t.exit_slippage, gross_pnl=t.gross_pnl, net_pnl=t.net_pnl, exit_reason=t.exit_reason, holding_period=t.holding_period, portfolio_equity_at_entry=equity))
        equity += t.net_pnl
    return result


def _apply_dynamic_sizing(raw_trades: list[BacktestTrade], portfolio_cfg: PortfolioConfig, engine_cfg: EngineConfig) -> list[PortfolioTrade]:
    equity = portfolio_cfg.starting_capital
    result = []
    for t in raw_trades:
        actual_size = _compute_size(equity=equity, entry_price=t.entry_price, sizing_mode=portfolio_cfg.sizing_mode, equity_fraction=portfolio_cfg.equity_fraction, trade_capital=portfolio_cfg.trade_capital, fraction=portfolio_cfg.fraction)
        _validate_entry_funding(equity, t.entry_price, actual_size, engine_cfg.fee_rate)
        direction_sign = _direction_sign(t.direction)
        gross_pnl = (t.exit_price - t.entry_price) * actual_size * direction_sign
        entry_fee = t.entry_price * actual_size * engine_cfg.fee_rate
        exit_fee = t.exit_price * actual_size * engine_cfg.fee_rate
        net_pnl = gross_pnl - entry_fee - exit_fee
        result.append(PortfolioTrade(trade_number=t.trade_number, direction=t.direction, entry_time=t.entry_time, exit_time=t.exit_time, entry_bar=t.entry_bar, exit_bar=t.exit_bar, entry_price=t.entry_price, exit_price=t.exit_price, size=actual_size, entry_fee=entry_fee, exit_fee=exit_fee, entry_slippage=t.entry_slippage * actual_size, exit_slippage=t.exit_slippage * actual_size, gross_pnl=gross_pnl, net_pnl=net_pnl, exit_reason=t.exit_reason, holding_period=t.holding_period, portfolio_equity_at_entry=equity))
        equity += net_pnl
    return result


def _compute_size(equity: float, entry_price: float, sizing_mode: SizingMode, equity_fraction: float, trade_capital: float, fraction: float) -> float:
    if entry_price <= 0.0:
        return 0.0
    if sizing_mode == SizingMode.PCT_OF_EQUITY:
        return max((equity * equity_fraction) / entry_price, 0.0)
    if sizing_mode == SizingMode.FIXED_DOLLAR:
        return max(trade_capital / entry_price, 0.0)
    if sizing_mode == SizingMode.FRACTIONAL:
        return max((equity * fraction) / entry_price, 0.0)
    return 1.0
