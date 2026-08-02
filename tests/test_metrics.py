"""Tests for pipeline.metrics — metric calculations."""
from __future__ import annotations

import math
from datetime import datetime

import pytest

from pipeline.metrics import _calculate_max_drawdown, _consecutive_streaks, calculate_metrics
from pipeline.models import Metrics, ParseError, Trade

# ── Test-data factory ──────────────────────────────────────────────────────────

_T0 = datetime(2024, 1, 1, 9, 30)
_T1 = datetime(2024, 1, 2, 9, 30)


def _trade(n: int, profit: float, direction: str = "Long") -> Trade:
    return Trade(
        trade_number=n,
        direction=direction,
        entry_time=_T0,
        exit_time=_T1,
        entry_price=100.0,
        exit_price=100.0 + profit,
        contracts=1.0,
        profit=profit,
        run_up=max(profit, 0.0),
        drawdown=abs(min(profit, 0.0)),
    )


def _make_trades(profits: list[float]) -> list[Trade]:
    return [_trade(i + 1, p) for i, p in enumerate(profits)]


# ── Fixture: 20-trade dataset with known expected values ───────────────────────
#
# Profits (in %):
#   +2.5, +1.8, -1.2, +3.1, -0.8, +2.0, -1.5, +1.5, +2.8, -1.0,
#   +1.2, -2.0, +3.5, +1.0, -0.5, +2.2, -1.8, +4.0, -0.9, +1.6
#
# Winners : 2.5, 1.8, 3.1, 2.0, 1.5, 2.8, 1.2, 3.5, 1.0, 2.2, 4.0, 1.6
# Losers  : 1.2, 0.8, 1.5, 1.0, 2.0, 0.5, 1.8, 0.9
#
# Gross profit  = 27.2
# Gross loss    = 9.7
# Net profit    = 17.5
# Profit factor = 27.2 / 9.7 ≈ 2.8041
# Win rate      = 12/20 = 0.60
# Avg win       = 27.2 / 12 ≈ 2.2667
# Avg loss      = 9.7  / 8  = 1.2125
# R/R           = 2.2667 / 1.2125 ≈ 1.8696
# Largest win   = 4.0
# Largest loss  = 2.0
# Max DD        = 2.0  (trade 12 takes cumulative from 10.4 to 8.4)
# Ret/DD        = 17.5 / 2.0 = 8.75

_PROFITS_20 = [
    2.5, 1.8, -1.2, 3.1, -0.8, 2.0, -1.5, 1.5, 2.8, -1.0,
    1.2, -2.0, 3.5, 1.0, -0.5, 2.2, -1.8, 4.0, -0.9, 1.6,
]


@pytest.fixture
def metrics_20() -> Metrics:
    trades = _make_trades(_PROFITS_20)
    return calculate_metrics(trades, "%")


# ── Core metric tests ──────────────────────────────────────────────────────────

class TestBasicCounts:
    def test_total_trades(self, metrics_20):
        assert metrics_20.total_trades == 20

    def test_winning_trades(self, metrics_20):
        assert metrics_20.winning_trades == 12

    def test_losing_trades(self, metrics_20):
        assert metrics_20.losing_trades == 8

    def test_breakeven_trades(self, metrics_20):
        assert metrics_20.breakeven_trades == 0

    def test_profit_unit_preserved(self, metrics_20):
        assert metrics_20.profit_unit == "%"


class TestPnL:
    def test_gross_profit(self, metrics_20):
        assert metrics_20.gross_profit == pytest.approx(27.2, abs=1e-9)

    def test_gross_loss(self, metrics_20):
        assert metrics_20.gross_loss == pytest.approx(9.7, abs=1e-9)

    def test_net_profit(self, metrics_20):
        assert metrics_20.net_profit == pytest.approx(17.5, abs=1e-9)

    def test_profit_factor(self, metrics_20):
        assert metrics_20.profit_factor == pytest.approx(27.2 / 9.7, rel=1e-6)


class TestRates:
    def test_win_rate(self, metrics_20):
        assert metrics_20.win_rate == pytest.approx(0.60, abs=1e-9)

    def test_avg_win(self, metrics_20):
        assert metrics_20.avg_win == pytest.approx(27.2 / 12, rel=1e-6)

    def test_avg_loss(self, metrics_20):
        assert metrics_20.avg_loss == pytest.approx(9.7 / 8, rel=1e-6)

    def test_risk_reward(self, metrics_20):
        expected = (27.2 / 12) / (9.7 / 8)
        assert metrics_20.risk_reward == pytest.approx(expected, rel=1e-6)


class TestExtremes:
    def test_largest_win(self, metrics_20):
        assert metrics_20.largest_win == pytest.approx(4.0)

    def test_largest_loss(self, metrics_20):
        assert metrics_20.largest_loss == pytest.approx(2.0)


class TestExpectancy:
    def test_expectancy(self, metrics_20):
        avg_win  = 27.2 / 12
        avg_loss = 9.7  / 8
        expected = (0.60 * avg_win) - (0.40 * avg_loss)
        assert metrics_20.expectancy == pytest.approx(expected, rel=1e-6)

    def test_avg_trade(self, metrics_20):
        assert metrics_20.avg_trade == pytest.approx(17.5 / 20, rel=1e-6)


class TestDrawdown:
    def test_max_drawdown(self, metrics_20):
        # Peak at trade 11 (cumulative = 10.4), then drops to 8.4 after trade 12
        assert metrics_20.max_drawdown == pytest.approx(2.0, abs=1e-9)

    def test_return_over_max_drawdown(self, metrics_20):
        assert metrics_20.return_over_max_drawdown == pytest.approx(8.75, rel=1e-6)

    def test_max_drawdown_zero_when_all_winners(self):
        trades = _make_trades([1.0, 2.0, 3.0])
        m = calculate_metrics(trades, "%")
        assert m.max_drawdown == 0.0
        assert math.isinf(m.return_over_max_drawdown)

    def test_max_drawdown_magnitude_only(self):
        # -3 then +1 then -2: worst peak-to-trough is 3.0 from the start
        dd = _calculate_max_drawdown([-3.0, 1.0, -2.0])
        assert dd == pytest.approx(4.0)  # peak=0 → drops to -3, then up to -2, then down to -4


# ── Streak tests ───────────────────────────────────────────────────────────────

class TestConsecutiveStreaks:
    def test_max_wins_from_fixture(self, metrics_20):
        # Trace: WW L W L W L WW L W L WW L W L W L W = max 2
        assert metrics_20.max_consecutive_wins == 2

    def test_max_losses_from_fixture(self, metrics_20):
        # No two consecutive losses in this sequence
        assert metrics_20.max_consecutive_losses == 1

    def test_streak_all_winners(self):
        profits = [1.0, 2.0, 3.0, 4.0]
        wins, losses = _consecutive_streaks(profits)
        assert wins == 4
        assert losses == 0

    def test_streak_all_losers(self):
        profits = [-1.0, -2.0, -3.0]
        wins, losses = _consecutive_streaks(profits)
        assert wins == 0
        assert losses == 3

    def test_streak_alternating(self):
        profits = [1.0, -1.0, 1.0, -1.0, 1.0]
        wins, losses = _consecutive_streaks(profits)
        assert wins == 1
        assert losses == 1

    def test_streak_with_breakeven(self):
        profits = [1.0, 1.0, 0.0, 1.0, 1.0, 1.0]
        wins, losses = _consecutive_streaks(profits)
        assert wins == 3  # breakeven resets the streak
        assert losses == 0


# ── Edge-case tests ────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_raises_on_empty_trade_list(self):
        with pytest.raises(ParseError):
            calculate_metrics([], "%")

    def test_all_winners_profit_factor_is_infinity(self):
        trades = _make_trades([1.0, 2.0, 3.0])
        m = calculate_metrics(trades, "%")
        assert math.isinf(m.profit_factor)
        assert math.isinf(m.risk_reward)

    def test_all_losers_net_profit_is_negative(self):
        trades = _make_trades([-1.0, -2.0, -3.0])
        m = calculate_metrics(trades, "%")
        assert m.net_profit == pytest.approx(-6.0)
        assert m.gross_profit == 0.0
        assert m.profit_factor == pytest.approx(0.0)
        assert m.win_rate == 0.0

    def test_single_trade_winner(self):
        trades = _make_trades([5.0])
        m = calculate_metrics(trades, "$")
        assert m.total_trades == 1
        assert m.net_profit == pytest.approx(5.0)
        assert m.win_rate == pytest.approx(1.0)
        assert m.avg_loss == 0.0
        assert math.isinf(m.risk_reward)

    def test_single_trade_loser(self):
        trades = _make_trades([-3.0])
        m = calculate_metrics(trades, "$")
        assert m.net_profit == pytest.approx(-3.0)
        assert m.win_rate == 0.0
        assert m.avg_win == 0.0
        assert m.profit_factor == pytest.approx(0.0)
