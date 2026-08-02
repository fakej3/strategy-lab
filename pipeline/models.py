"""
Data models for the Strategy Research Lab pipeline.

All monetary/percentage values use the same unit throughout a single
analysis run — either "%" or "$", detected from the source CSV.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ParseError(Exception):
    """Raised when the TradingView CSV cannot be parsed."""


class RuleStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class Decision(str, Enum):
    PROMISING = "PROMISING"
    NEEDS_IMPROVEMENT = "NEEDS IMPROVEMENT"
    REJECT = "REJECT"


@dataclass
class Trade:
    trade_number: int
    direction: str          # "Long" or "Short"
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    contracts: float
    profit: float           # same unit as source CSV ("%" or "$")
    run_up: float           # max favorable excursion for this trade
    drawdown: float         # max adverse excursion for this trade

    @property
    def is_winner(self) -> bool:
        return self.profit > 0

    @property
    def is_loser(self) -> bool:
        return self.profit < 0


@dataclass
class Metrics:
    # ── Trade counts ─────────────────────────────────────────────────────
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    profit_unit: str        # "%" or "$"

    # ── P&L ──────────────────────────────────────────────────────────────
    net_profit: float
    gross_profit: float
    gross_loss: float       # stored as a positive value

    # ── Rates and ratios ─────────────────────────────────────────────────
    profit_factor: float    # gross_profit / gross_loss; math.inf if no losses
    win_rate: float         # 0.0 – 1.0

    # ── Averages ─────────────────────────────────────────────────────────
    avg_win: float
    avg_loss: float         # stored as a positive value
    risk_reward: float      # avg_win / avg_loss; math.inf if no losses

    # ── Single-trade extremes ─────────────────────────────────────────────
    largest_win: float
    largest_loss: float     # stored as a positive value

    # ── Streaks ──────────────────────────────────────────────────────────
    max_consecutive_wins: int
    max_consecutive_losses: int

    # ── Summary ──────────────────────────────────────────────────────────
    avg_trade: float        # net_profit / total_trades
    expectancy: float       # (win_rate * avg_win) - (loss_rate * avg_loss)

    # ── Risk-adjusted ────────────────────────────────────────────────────
    max_drawdown: float             # magnitude; same unit as profit
    return_over_max_drawdown: float # net_profit / max_drawdown; math.inf if no drawdown


@dataclass
class RuleResult:
    name: str
    status: RuleStatus
    score: float    # 0 – 100
    detail: str     # human-readable explanation of the result
    weight: float   # relative weight within its category (0.0 – 1.0)


@dataclass
class CategoryResult:
    name: str
    score: float    # 0 – 100, weighted average of its rules
    weight: float   # relative weight in the overall score (0.0 – 1.0)
    rules: list[RuleResult]


@dataclass
class GateResult:
    decision: Decision
    overall_score: float        # 0 – 100
    categories: list[CategoryResult]
    weakest_category: str
    primary_failure: Optional[str]  # key of the most critical rule to fix
    next_experiment: str
    expected_goal: str
    critical_failures: list[str]    # rule keys that forced REJECT regardless of score
