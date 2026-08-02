"""BacktestExecutor — event-driven fill simulation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models import BacktestTrade, EngineConfig, ExitReason, _Position
from .strategy import Signal, StrategyBase

# ── Module-level constants ─────────────────────────────────────────────────────

_REQUIRED_OHLC: frozenset[str] = frozenset({"open", "high", "low", "close"})

# Accepted signal values: Signal enum members or their exact string equivalents.
_VALID_SIGNAL_VALUES: frozenset[str] = frozenset(s.value for s in Signal)


# ── Input validators ───────────────────────────────────────────────────────────

def _validate_bars(bars: pd.DataFrame) -> None:
    """Raise ``ValueError`` if *bars* is not a structurally valid OHLC DataFrame.

    Checks performed (in order):
    1. All required columns (open, high, low, close) are present.
    2. No NaN values in those columns.
    3. No infinite values in those columns.
    4. ``high >= low`` for every row.
    5. ``open`` is within ``[low, high]`` for every row.
    6. ``close`` is within ``[low, high]`` for every row.
    """
    missing = _REQUIRED_OHLC - set(bars.columns)
    if missing:
        raise ValueError(
            f"bars is missing required column(s): {sorted(missing)}"
        )

    ohlc = bars[["open", "high", "low", "close"]]

    if ohlc.isnull().any().any():
        raise ValueError(
            "bars contains NaN values in OHLC columns; "
            "clean or forward-fill the data before backtesting"
        )

    if np.isinf(ohlc.to_numpy(dtype=float)).any():
        raise ValueError(
            "bars contains infinite values in OHLC columns"
        )

    if (bars["high"] < bars["low"]).any():
        raise ValueError(
            "bars contains rows where high < low (corrupted candle data)"
        )

    if (bars["open"] < bars["low"]).any() or (bars["open"] > bars["high"]).any():
        raise ValueError(
            "bars contains rows where open is outside [low, high]"
        )

    if (bars["close"] < bars["low"]).any() or (bars["close"] > bars["high"]).any():
        raise ValueError(
            "bars contains rows where close is outside [low, high]"
        )


def _validate_signals(signals: pd.Series, expected_len: int) -> None:
    """Raise ``ValueError`` if *signals* has the wrong length or invalid values.

    Accepted values: ``Signal`` enum members, or their exact uppercase string
    equivalents (e.g. ``"BUY"``).  Lowercase variants, ``None``, and
    arbitrary objects are rejected.
    """
    if len(signals) != expected_len:
        raise ValueError(
            f"generate_signals returned {len(signals)} values for "
            f"{expected_len} bars"
        )

    invalid_mask = ~signals.isin(_VALID_SIGNAL_VALUES)
    if invalid_mask.any():
        bad_val = signals[invalid_mask].iloc[0]
        bad_idx = signals[invalid_mask].index[0]
        raise ValueError(
            f"generate_signals returned invalid signal {bad_val!r} at "
            f"index {bad_idx!r}. "
            f"Valid values are: {sorted(_VALID_SIGNAL_VALUES)}"
        )


# ── Executor ───────────────────────────────────────────────────────────────────

class BacktestExecutor:
    """Translate a strategy's signals into a list of completed trades.

    Execution rules
    ---------------
    - Signal at bar T  →  fill at bar T+1 open.  No bar-T data is used after
      the signal is emitted, so lookahead bias is structurally impossible at
      the execution layer.
    - One position at a time.  A BUY signal while already long is ignored.
    - SL/TP are evaluated at the start of every held bar, including the entry
      bar.  A position can be stopped out intrabar on the same bar it opened.
    - When SL and TP both trigger on the same bar, SL wins (conservative).
    - Gap-through-stop: if the bar opens on the wrong side of the stop level,
      fill is at the bar open (the first executable price), not at the stop.
    - Slippage is applied symmetrically: buyers pay more, sellers receive less.
    - Any open position at the last bar is closed at that bar's close.

    See ``EngineConfig`` for full documentation of each parameter and the
    underlying assumptions of each model (stop-loss, take-profit, slippage,
    position sizing).
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

    def run(self, bars: pd.DataFrame, strategy: StrategyBase) -> list[BacktestTrade]:
        """Run *strategy* over *bars* and return completed trades in order.

        Args:
            bars:     OHLCV DataFrame from ``data.get_bars()``.  Must contain
                      columns ``open``, ``high``, ``low``, ``close`` with no
                      NaN or infinite values and valid candle geometry
                      (high ≥ low, open/close within [low, high]).
            strategy: A ``StrategyBase`` implementation.  Its
                      ``generate_signals`` method is called once with the
                      full ``bars`` DataFrame.  Signals must be causal — see
                      ``StrategyBase`` for the lookahead constraint.

        Returns:
            List of ``BacktestTrade`` records in chronological order.

        Raises:
            ValueError: If ``bars`` fails structural validation, or if
                        ``generate_signals`` returns an invalid result.
        """
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
            signal = signals.iloc[i]

            # ── 1. Check SL / TP for the current open position ───────────────
            if position is not None:
                sl_tp = self._check_sl_tp(position, bar)
                if sl_tp is not None:
                    raw_exit, reason = sl_tp
                    trade_count += 1
                    trades.append(
                        self._close(position, trade_count, raw_exit, bars.index[i], i, reason)
                    )
                    position = None

            # ── 2. Execute signal at next bar open ────────────────────────────
            if i + 1 >= n:
                break  # no next bar to fill into; last bar's signal is discarded

            raw_next_open = float(bars.iloc[i + 1]["open"])
            next_time = bars.index[i + 1]

            if position is None and signal == Signal.BUY:
                position = self._open_long(raw_next_open, next_time, i + 1)

            elif position is not None and signal in (Signal.EXIT, Signal.SELL):
                trade_count += 1
                trades.append(
                    self._close(
                        position, trade_count, raw_next_open, next_time, i + 1,
                        ExitReason.SIGNAL,
                    )
                )
                position = None

        # ── 3. Close any remaining position at end of data ────────────────────
        if position is not None:
            last_close = float(bars.iloc[-1]["close"])
            trade_count += 1
            trades.append(
                self._close(
                    position, trade_count, last_close, bars.index[-1],
                    n - 1, ExitReason.END_OF_DATA,
                )
            )

        return trades

    # ── private ───────────────────────────────────────────────────────────────

    def _open_long(self, raw_open: float, entry_time, entry_bar: int) -> _Position:
        """Build a ``_Position`` for a new long entry.

        ``entry_price`` is the fill price after slippage.
        SL/TP levels are derived from the fill price, not the raw open.
        """
        cfg = self.config
        fill = raw_open * (1.0 + cfg.slippage_pct)
        size = cfg.position_size
        sl = fill * (1.0 - cfg.stop_loss_pct) if cfg.stop_loss_pct is not None else None
        tp = fill * (1.0 + cfg.take_profit_pct) if cfg.take_profit_pct is not None else None
        return _Position(
            direction="Long",
            entry_bar=entry_bar,
            entry_time=entry_time,
            entry_price=fill,
            size=size,
            stop_loss=sl,
            take_profit=tp,
            entry_fee=fill * size * cfg.fee_rate,
            entry_slippage=raw_open * cfg.slippage_pct * size,
        )

    def _check_sl_tp(
        self, pos: _Position, bar: pd.Series
    ) -> tuple[float, ExitReason] | None:
        """Return ``(raw_exit_price, reason)`` if SL or TP fires on *bar*, else ``None``.

        SL check: ``bar_low <= stop_loss_level``.
        TP check: ``bar_high >= take_profit_level``.
        SL takes priority when both fire on the same bar.

        Gap handling:
        - Gap-down through SL: ``raw = min(stop_level, bar_open)`` — fills at
          bar open when the bar opens below the stop level.
        - Gap-up through TP: ``raw = max(tp_level, bar_open)`` — fills at bar
          open when the bar opens above the target.
        """
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        bar_open = float(bar["open"])

        sl_hit = pos.stop_loss is not None and bar_low <= pos.stop_loss
        tp_hit = pos.take_profit is not None and bar_high >= pos.take_profit

        if not sl_hit and not tp_hit:
            return None

        if sl_hit:
            # SL wins when both fire on the same bar.
            # Gap-down: bar opened below stop → fill at open (first executable price).
            raw = min(pos.stop_loss, bar_open)
            return raw, ExitReason.STOP_LOSS

        # TP only.
        # Gap-up: bar opened above target → receive the better opening price.
        raw = max(pos.take_profit, bar_open)
        return raw, ExitReason.TAKE_PROFIT

    def _close(
        self,
        pos: _Position,
        trade_number: int,
        raw_exit: float,
        exit_time,
        exit_bar: int,
        reason: ExitReason,
    ) -> BacktestTrade:
        """Build a ``BacktestTrade`` by closing *pos* at *raw_exit*.

        *raw_exit* is the reference price before slippage (stop level, TP
        level, bar open, or last-bar close depending on exit type).
        Slippage and fees are applied here.
        """
        cfg = self.config
        exit_fill = raw_exit * (1.0 - cfg.slippage_pct)
        exit_slippage = raw_exit * cfg.slippage_pct * pos.size
        exit_fee = exit_fill * pos.size * cfg.fee_rate
        gross_pnl = (exit_fill - pos.entry_price) * pos.size
        net_pnl = gross_pnl - pos.entry_fee - exit_fee

        return BacktestTrade(
            trade_number=trade_number,
            direction=pos.direction,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            entry_bar=pos.entry_bar,
            exit_bar=exit_bar,
            entry_price=pos.entry_price,
            exit_price=exit_fill,
            size=pos.size,
            entry_fee=pos.entry_fee,
            exit_fee=exit_fee,
            entry_slippage=pos.entry_slippage,
            exit_slippage=exit_slippage,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            exit_reason=reason,
            holding_period=exit_bar - pos.entry_bar,
        )
