"""Tests for pipeline.metrics — calculate_metrics and edge cases."""
from __future__ import annotations

import math
import pytest

from pipeline.metrics import calculate_metrics
from pipeline.models import Trade, ParseError


def _trade(profit: float) -> Trade:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return Trade(
        trade_number=1,
        direction="Long",
        contracts=1.0,
        entry_time=now,
        exit_time=now,
        entry_price=100.0,
        exit_price=100.0 + profit,
        profit=profit,
        run_up=max(profit, 0.0),
        drawdown=max(-profit, 0.0),
    )


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_trades_raises():
    with pytest.raises(ParseError):
        calculate_metrics([], "$")


# ── Basic sanity ──────────────────────────────────────────────────────────────

def test_mixed_trades_basic():
    trades = [_trade(100.0), _trade(200.0), _trade(-50.0), _trade(-100.0)]
    m = calculate_metrics(trades, "$")
    assert m.total_trades == 4
    assert m.winning_trades == 2
    assert m.losing_trades == 2
    assert m.gross_profit == pytest.approx(300.0)
    assert m.gross_loss   == pytest.approx(150.0)


# ── largest_win / largest_loss edge cases ─────────────────────────────────────

def test_largest_win_zero_when_all_losers():
    """Regression: max(profits) returned the smallest-magnitude loss (still negative)
    when every trade was a loser — now largest_win = 0.0 when no winners."""
    trades = [_trade(-100.0), _trade(-200.0), _trade(-50.0)]
    m = calculate_metrics(trades, "$")
    assert m.largest_win == pytest.approx(0.0), (
        f"Expected 0.0 but got {m.largest_win} — likely using max(all profits) including losers"
    )


def test_largest_loss_zero_when_all_winners():
    """Regression: abs(min(profits)) returned the smallest win when every trade was
    a winner — now largest_loss = 0.0 when no losers."""
    trades = [_trade(100.0), _trade(200.0), _trade(50.0)]
    m = calculate_metrics(trades, "$")
    assert m.largest_loss == pytest.approx(0.0), (
        f"Expected 0.0 but got {m.largest_loss} — likely using abs(min(all profits)) including winners"
    )


def test_largest_win_correct_value():
    trades = [_trade(100.0), _trade(300.0), _trade(-50.0)]
    m = calculate_metrics(trades, "$")
    assert m.largest_win == pytest.approx(300.0)


def test_largest_loss_correct_value():
    trades = [_trade(100.0), _trade(-50.0), _trade(-200.0)]
    m = calculate_metrics(trades, "$")
    assert m.largest_loss == pytest.approx(200.0)
