"""Pre-trade risk engine for the paper trading bot.

Every potential order passes through ``RiskEngine.check()`` before being
submitted to the ``OrderManager``.  The engine is stateless given its inputs —
all runtime state is provided by the caller.

Risk checks (in order of evaluation)
--------------------------------------
1. Max daily loss (USD)   — halt if today's net PnL < -max_daily_loss_usd
2. Max drawdown (%)       — halt if equity drawdown > max_drawdown_pct
3. Max daily trades       — reject if n_trades_today >= max_daily_trades
4. Max open positions     — reject if open positions >= max_open_positions
5. Trading cooldown       — reject if time since last trade < cooldown_s
6. Max position size (USD)— reject if order notional > max_position_size_usd
7. Max leverage           — always 1.0 in paper mode (informational)

If any check fails, ``RiskEngine.check()`` returns a non-empty rejection
reason string.  The caller must not submit the order in that case.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .config import RiskConfig
from .events import EventBus, RiskRejectionEvent

log = logging.getLogger("strategy_lab.bot.risk")


@dataclass
class RiskContext:
    """All runtime state needed for a risk check.

    All monetary values are in the account's quote currency (USDT).
    """

    # Current order intent
    symbol:        str
    side:          str
    qty:           float
    ref_price:     float    # best-guess fill price (e.g. current close)

    # Account state
    equity:        float    # current total equity
    peak_equity:   float    # all-time high equity (for drawdown)

    # Daily state
    daily_pnl:     float    # net PnL for today (negative = loss)
    n_trades_today: int     # closed trades since midnight UTC

    # Position state
    open_positions: int     # number of currently open positions

    # Timing
    last_trade_ts: float = 0.0   # unix timestamp of most recent trade close


class RiskEngine:
    """Evaluates pre-trade risk checks.

    Usage::

        risk = RiskEngine(config, bus)
        reason = risk.check(ctx)
        if reason:
            log.warning("Trade rejected: %s", reason)
        else:
            order_manager.submit_market(...)
    """

    def __init__(self, config: RiskConfig, bus: EventBus | None = None) -> None:
        self.cfg = config
        self.bus = bus

    def check(self, ctx: RiskContext) -> str:
        """Run all risk checks.  Returns rejection reason or empty string."""

        reason = (
            self._check_daily_loss(ctx)
            or self._check_drawdown(ctx)
            or self._check_daily_trades(ctx)
            or self._check_open_positions(ctx)
            or self._check_cooldown(ctx)
            or self._check_position_size(ctx)
        )

        if reason:
            log.warning("Risk check failed [%s %s]: %s", ctx.symbol, ctx.side, reason)
            if self.bus:
                self.bus.emit(RiskRejectionEvent(
                    symbol=ctx.symbol,
                    side=ctx.side,
                    reason=reason,
                ))

        return reason

    # ── Individual checks ──────────────────────────────────────────────────────

    def _check_daily_loss(self, ctx: RiskContext) -> str:
        if ctx.daily_pnl < -self.cfg.max_daily_loss_usd:
            return (
                f"max daily loss reached: pnl={ctx.daily_pnl:.2f} "
                f"limit={-self.cfg.max_daily_loss_usd:.2f}"
            )
        return ""

    def _check_drawdown(self, ctx: RiskContext) -> str:
        if ctx.peak_equity <= 0:
            return ""
        dd = (ctx.peak_equity - ctx.equity) / ctx.peak_equity
        if dd > self.cfg.max_drawdown_pct:
            return (
                f"max drawdown reached: dd={dd:.2%} "
                f"limit={self.cfg.max_drawdown_pct:.2%}"
            )
        return ""

    def _check_daily_trades(self, ctx: RiskContext) -> str:
        if ctx.n_trades_today >= self.cfg.max_daily_trades:
            return (
                f"max daily trades reached: {ctx.n_trades_today} "
                f">= {self.cfg.max_daily_trades}"
            )
        return ""

    def _check_open_positions(self, ctx: RiskContext) -> str:
        if ctx.open_positions >= self.cfg.max_open_positions:
            return (
                f"max open positions reached: {ctx.open_positions} "
                f">= {self.cfg.max_open_positions}"
            )
        return ""

    def _check_cooldown(self, ctx: RiskContext) -> str:
        if self.cfg.trading_cooldown_s <= 0:
            return ""
        elapsed = time.monotonic() - ctx.last_trade_ts
        if elapsed < self.cfg.trading_cooldown_s:
            remaining = self.cfg.trading_cooldown_s - elapsed
            return f"trading cooldown: {remaining:.1f}s remaining"
        return ""

    def _check_position_size(self, ctx: RiskContext) -> str:
        notional = ctx.qty * ctx.ref_price
        if notional > self.cfg.max_position_size_usd:
            return (
                f"position size too large: notional={notional:.2f} "
                f"limit={self.cfg.max_position_size_usd:.2f}"
            )
        return ""
