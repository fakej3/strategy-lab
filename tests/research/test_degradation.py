"""Unit tests for research/degradation.py — hand-calculated examples."""
from __future__ import annotations

import pytest

from research.degradation import (
    analyze_degradation,
    _profit_factor,
    _trade_sharpe,
    _win_rate,
)


def _trade(pnl: float):
    """Minimal trade stub with net_pnl."""
    class _T:
        def __init__(self, p):
            self.net_pnl = p
    return _T(pnl)


class TestHelpers:
    def test_trade_sharpe_returns_none_for_one_trade(self):
        assert _trade_sharpe([_trade(10)]) is None

    def test_trade_sharpe_zero_std(self):
        # All same PnL → std=0 → sharpe=0
        trades = [_trade(10), _trade(10), _trade(10)]
        assert _trade_sharpe(trades) == 0.0

    def test_trade_sharpe_known_value(self):
        # pnls = [10, -10] → mean=0, std=14.142 → sharpe=0
        trades = [_trade(10), _trade(-10)]
        assert _trade_sharpe(trades) == 0.0

    def test_trade_sharpe_positive_edge(self):
        # pnls = [10, 20] → mean=15, std=7.071 → sharpe≈2.121
        import math
        trades = [_trade(10.0), _trade(20.0)]
        sh = _trade_sharpe(trades)
        expected = 15.0 / (10.0 / math.sqrt(2))  # std = 10/sqrt(2)
        assert sh == pytest.approx(expected, rel=1e-4)

    def test_win_rate_all_wins(self):
        trades = [_trade(1), _trade(2), _trade(3)]
        assert _win_rate(trades) == pytest.approx(1.0)

    def test_win_rate_mixed(self):
        trades = [_trade(1), _trade(-1), _trade(1), _trade(-1)]
        assert _win_rate(trades) == pytest.approx(0.5)

    def test_profit_factor_no_losses(self):
        trades = [_trade(10), _trade(20)]
        assert _profit_factor(trades) == 999.0

    def test_profit_factor_known_value(self):
        # gross=30 / loss=10 = 3.0
        trades = [_trade(10), _trade(20), _trade(-10)]
        assert _profit_factor(trades) == pytest.approx(3.0)


class TestAnalyzeDegradation:
    def test_too_few_trades_returns_none_score(self):
        result = analyze_degradation([_trade(1)] * 5)
        assert result["degradation_score"] is None

    def test_uniform_wins_score_near_100(self):
        # Same PnL throughout → no degradation
        trades = [_trade(10.0)] * 20
        result = analyze_degradation(trades)
        # With uniform trades: h1_sharpe = 0, no sharpe penalty applied (h1_sh <= 0)
        # win rate stays the same → no penalty
        # The result should be between 70 and 100 (Sharpe=0 → no sharpe penalty,
        # win rate = 1.0 in both halves → no wr penalty, PF=999 in both → no pf penalty)
        assert result["degradation_score"] is not None
        assert result["degradation_score"] >= 70.0

    def test_first_half_good_second_half_bad(self):
        # First 10: big winners; Last 10: losers
        # Uniform trades have std=0 → Sharpe=0 → no Sharpe penalty (correct).
        # Win-rate collapses (1.0 → 0.0) and PF collapses (999 → 0): heavy penalty.
        good   = [_trade(50.0)] * 10
        bad    = [_trade(-10.0)] * 10
        result = analyze_degradation(good + bad)
        assert result["degradation_score"] is not None
        # Win-rate penalty (30) + PF penalty (15) = 45 → score = 55
        assert result["degradation_score"] <= 60.0

    def test_no_degradation_score_in_0_100(self):
        import random
        random.seed(0)
        trades = [_trade(random.gauss(5, 10)) for _ in range(30)]
        result = analyze_degradation(trades)
        s = result["degradation_score"]
        if s is not None:
            assert 0.0 <= s <= 100.0

    def test_all_keys_present(self):
        trades = [_trade(10.0)] * 20
        result = analyze_degradation(trades)
        for key in ("degradation_score", "first_half_sharpe", "second_half_sharpe",
                    "first_half_wr", "second_half_wr", "first_half_pf", "second_half_pf",
                    "first_third_sharpe", "second_third_sharpe", "third_third_sharpe"):
            assert key in result

    def test_thirds_present_for_12_trades(self):
        trades = [_trade(10.0)] * 12
        result = analyze_degradation(trades)
        assert result["first_third_sharpe"] is not None
        assert result["second_third_sharpe"] is not None
        assert result["third_third_sharpe"] is not None
