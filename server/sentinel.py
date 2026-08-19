"""SENTINEL: per-instance metadata for multi-strategy paper trading."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class StrategyInstance:
    """One (symbol × interval × strategy × params) trading unit."""

    instance_id:     str
    symbol:          str
    interval:        str
    strategy_name:   str
    strategy_params: dict
    status:          str = "starting"   # starting|running|stopped|failed
    error:           str = ""
    started_at:      str = field(default_factory=lambda: _now())
    stopped_at:      str = ""
    n_candles:       int   = 0
    n_trades:        int   = 0
    realized_pnl:    float = 0.0
    unrealized_pnl:  float = 0.0
    last_signal:     str   = ""
    last_candle_ts:  str   = ""

    @staticmethod
    def make_id(
        symbol: str,
        interval: str,
        strategy_name: str,
        params: dict,
    ) -> str:
        parts = [symbol, interval, strategy_name]
        for k, v in sorted(params.items()):
            parts.append(f"{k}={v}")
        return ":".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id":     self.instance_id,
            "symbol":          self.symbol,
            "interval":        self.interval,
            "strategy_name":   self.strategy_name,
            "strategy_params": self.strategy_params,
            "status":          self.status,
            "error":           self.error,
            "started_at":      self.started_at,
            "stopped_at":      self.stopped_at,
            "n_candles":       self.n_candles,
            "n_trades":        self.n_trades,
            "realized_pnl":    self.realized_pnl,
            "unrealized_pnl":  self.unrealized_pnl,
            "last_signal":     self.last_signal,
            "last_candle_ts":  self.last_candle_ts,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
