"""BacktestExecutor — event-driven fill simulation."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .models import BacktestTrade, EngineConfig, ExitReason, _Position
from .strategy import Signal, StrategyBase


class BacktestExecutor:
    """Translate a strategy's signals into a list of completed trades.

    Execution rules
    ---------------
    - Signal at bar T close → fill at bar T+1 open.  No bar-T data is
      used after the signal is emitted, so lookahead bias is impossible
      at the execution layer.
    - One position at a time.  A BUY signal while already long is ignored.
    - Stop-loss and take-profit are checked against each held bar's
      intrabar low/high.
    - When SL and TP both trigger on the same bar, SL wins (conservative).
    - Gap-through-stop: if the bar opens on the wrong side of the stop,
      the fill is at the bar open (not at the stop level).
    - Slippage is applied symmetrically: buyers pay more, sellers receive
      less.
    - Any open position at the last bar is closed at that bar's close.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

    def run(self, bars: pd.DataFrame, strategy: StrategyBase) -> list[BacktestTrade]:
        """Run the strategy over bars and return completed trades in order."""
        if bars.empty:
            return []

        signals = strategy.generate_signals(bars)
        if len(signals) != len(bars):
            raise ValueError(
                f"generate_signals returned {len(signals)} values for {len(bars)} bars"
            )

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
                break  # no next bar to fill into

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
        """Return (raw_exit_price, reason) if SL or TP is triggered, else None."""
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        bar_open = float(bar["open"])

        sl_hit = pos.stop_loss is not None and bar_low <= pos.stop_loss
        tp_hit = pos.take_profit is not None and bar_high >= pos.take_profit

        if not sl_hit and not tp_hit:
            return None

        if sl_hit:
            # SL wins when both fire on the same bar.
            # Gap-down: if bar opened below stop, we fill at open (not stop).
            raw = min(pos.stop_loss, bar_open)
            return raw, ExitReason.STOP_LOSS

        # TP only
        # Gap-up: if bar opened above target, we get the better fill.
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
