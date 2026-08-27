"""BacktestExecutor — event-driven fill simulation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models import BacktestTrade, EngineConfig, ExitReason, _Position
from .strategy import CausalStrategyBase, Signal, StrategyBase

_REQUIRED_OHLC: frozenset[str] = frozenset({"open", "high", "low", "close"})
_VALID_SIGNAL_VALUES: frozenset[str] = frozenset(s.value for s in Signal)


def _validate_bars(bars: pd.DataFrame) -> None:
    """Raise ValueError if bars is structurally valid, ordered OHLC data.

    A backtest must not silently operate on ambiguous chronology. Duplicate or
    descending timestamps can otherwise create impossible execution ordering.
    """
    missing = _REQUIRED_OHLC - set(bars.columns)
    if missing:
        raise ValueError(f"bars is missing required column(s): {sorted(missing)}")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("bars index must be monotonically increasing")
    if bars.index.has_duplicates:
        raise ValueError("bars index contains duplicate timestamps")

    try:
        ohlc = bars[["open", "high", "low", "close"]].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("bars OHLC columns must contain numeric values") from exc

    o, h, l, c = ohlc[:, 0], ohlc[:, 1], ohlc[:, 2], ohlc[:, 3]
    if np.isnan(ohlc).any():
        raise ValueError("bars contains NaN values in OHLC columns; clean or forward-fill the data before backtesting")
    if np.isinf(ohlc).any():
        raise ValueError("bars contains infinite values in OHLC columns")
    if (h < l).any():
        raise ValueError("bars contains rows where high < low (corrupted candle data)")
    if (o < l).any() or (o > h).any():
        raise ValueError("bars contains rows where open is outside [low, high]")
    if (c < l).any() or (c > h).any():
        raise ValueError("bars contains rows where close is outside [low, high]")


def _validate_signals(signals: pd.Series, expected_len: int) -> None:
    """Raise ValueError if signals has the wrong length or invalid values."""
    if len(signals) != expected_len:
        raise ValueError(f"generate_signals returned {len(signals)} values for {expected_len} bars")
    invalid_mask = ~signals.isin(_VALID_SIGNAL_VALUES)
    if invalid_mask.any():
        bad_val = signals[invalid_mask].iloc[0]
        bad_idx = signals[invalid_mask].index[0]
        raise ValueError(
            f"generate_signals returned invalid signal {bad_val!r} at index {bad_idx!r}. "
            f"Valid values are: {sorted(_VALID_SIGNAL_VALUES)}"
        )


class BacktestExecutor:
    """Translate strategy signals into completed trades.

    For ``CausalStrategyBase`` implementations the strategy is called with
    history ending at the current bar, so future OHLCV rows are unavailable.
    Legacy ``StrategyBase`` implementations still receive the full dataset
    and retain the older author-enforced causality contract.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

    def run(self, bars: pd.DataFrame, strategy: StrategyBase) -> list[BacktestTrade]:
        if bars.empty:
            return []
        _validate_bars(bars)
        signals = strategy.generate_signals(bars)
        _validate_signals(signals, len(bars))

        n = len(bars)
        position: _Position | None = None
        trades: list[BacktestTrade] = []
        trade_count = 0

        for i in range(n):
            bar = bars.iloc[i]

            if position is not None:
                sl_tp = self._check_sl_tp(position, bar)
                if sl_tp is not None:
                    raw_exit, reason = sl_tp
                    trade_count += 1
                    trades.append(self._close(position, trade_count, raw_exit, bars.index[i], i, reason))
                    position = None

            if i + 1 >= n:
                break

            raw_next_open = float(bars.iloc[i + 1]["open"])
            next_time = bars.index[i + 1]

            if position is None and signal_is(signals.iloc[i], Signal.BUY):
                position = self._open_long(raw_next_open, next_time, i + 1)
            elif position is not None and signal_is_any(signals.iloc[i], (Signal.EXIT, Signal.SELL)):
                trade_count += 1
                trades.append(self._close(position, trade_count, raw_next_open, next_time, i + 1, ExitReason.SIGNAL))
                position = None

        if position is not None:
            last_close = float(bars.iloc[-1]["close"])
            trade_count += 1
            trades.append(self._close(position, trade_count, last_close, bars.index[-1], n - 1, ExitReason.END_OF_DATA))

        return trades

    def _open_long(self, raw_open: float, entry_time, entry_bar: int) -> _Position:
        cfg = self.config
        fill = raw_open * (1.0 + cfg.slippage_pct)
        size = cfg.position_size
        sl = fill * (1.0 - cfg.stop_loss_pct) if cfg.stop_loss_pct is not None else None
        tp = fill * (1.0 + cfg.take_profit_pct) if cfg.take_profit_pct is not None else None
        return _Position(
            direction="Long", entry_bar=entry_bar, entry_time=entry_time,
            entry_price=fill, size=size, stop_loss=sl, take_profit=tp,
            entry_fee=fill * size * cfg.fee_rate,
            entry_slippage=raw_open * cfg.slippage_pct * size,
        )

    def _check_sl_tp(self, pos: _Position, bar: pd.Series) -> tuple[float, ExitReason] | None:
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        bar_open = float(bar["open"])
        sl_hit = pos.stop_loss is not None and bar_low <= pos.stop_loss
        tp_hit = pos.take_profit is not None and bar_high >= pos.take_profit
        if not sl_hit and not tp_hit:
            return None
        if sl_hit:
            return min(pos.stop_loss, bar_open), ExitReason.STOP_LOSS
        return max(pos.take_profit, bar_open), ExitReason.TAKE_PROFIT

    def _close(self, pos: _Position, trade_number: int, raw_exit: float, exit_time, exit_bar: int, reason: ExitReason) -> BacktestTrade:
        cfg = self.config
        exit_fill = raw_exit * (1.0 - cfg.slippage_pct)
        exit_slippage = raw_exit * cfg.slippage_pct * pos.size
        exit_fee = exit_fill * pos.size * cfg.fee_rate
        gross_pnl = (exit_fill - pos.entry_price) * pos.size
        net_pnl = gross_pnl - pos.entry_fee - exit_fee
        return BacktestTrade(
            trade_number=trade_number, direction=pos.direction,
            entry_time=pos.entry_time, exit_time=exit_time,
            entry_bar=pos.entry_bar, exit_bar=exit_bar,
            entry_price=pos.entry_price, exit_price=exit_fill, size=pos.size,
            entry_fee=pos.entry_fee, exit_fee=exit_fee,
            entry_slippage=pos.entry_slippage, exit_slippage=exit_slippage,
            gross_pnl=gross_pnl, net_pnl=net_pnl, exit_reason=reason,
            holding_period=exit_bar - pos.entry_bar,
        )


def signal_is(value, target: Signal) -> bool:
    return value == target or value == target.value


def signal_is_any(value, targets: tuple[Signal, ...]) -> bool:
    return any(signal_is(value, target) for target in targets)
