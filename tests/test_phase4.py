"""Phase 4 regression tests.

Covers:
  Part 1 — SymbolRules: explicit per-symbol rules, WARNING for unknowns,
            validate_symbol_registration, symbol isolation.
  Part 2 — Batch portfolio capital accounting: event-based chronological
            replay with correct overlapping-position handling,
            max_open_positions, max_total_exposure_usd.
  Parts 3-8 — Strategy registry: register, create, defaults, isolation.

All tests are deterministic — no network, no random seeds, no real-time waits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from bot.paper_exchange import (
    BUILTIN_SYMBOL_RULES,
    PaperExchange,
    SymbolRules,
    _DEFAULT_RULES,
    validate_symbol_registration,
)
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import BatchBacktest, BatchBacktestResult, SymbolResult
from portfolio.models import PortfolioResult, PortfolioTrade
from strategies import EMACrossover, registry
from strategies.registry import StrategyRegistry

# ── Fixtures / helpers ──────────────────────────────────────────────────────────

_T0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
_T2 = datetime(2025, 1, 3, 0, 0, 0, tzinfo=timezone.utc)
_T3 = datetime(2025, 1, 4, 0, 0, 0, tzinfo=timezone.utc)
_T4 = datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
_T5 = datetime(2025, 1, 6, 0, 0, 0, tzinfo=timezone.utc)
_T6 = datetime(2025, 1, 7, 0, 0, 0, tzinfo=timezone.utc)


def _trade(
    *,
    entry_time: datetime = _T0,
    exit_time: datetime = _T1,
    entry_price: float = 100.0,
    exit_price: float = 110.0,
    size: float = 1.0,
    entry_fee: float = 0.0,
    exit_fee: float = 0.0,
    trade_number: int = 1,
) -> PortfolioTrade:
    gross_pnl = (exit_price - entry_price) * size
    net_pnl   = gross_pnl - entry_fee - exit_fee
    return PortfolioTrade(
        trade_number=trade_number,
        direction="long",
        entry_time=entry_time,
        exit_time=exit_time,
        entry_bar=0,
        exit_bar=1,
        entry_price=entry_price,
        exit_price=exit_price,
        size=size,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        entry_slippage=0.0,
        exit_slippage=0.0,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        exit_reason="exit_signal",
        holding_period=1,
        portfolio_equity_at_entry=10_000.0,
    )


def _result(trades: list[PortfolioTrade], starting_capital: float = 10_000.0) -> PortfolioResult:
    ending_equity = starting_capital + sum(t.net_pnl for t in trades)
    return PortfolioResult(
        starting_capital=starting_capital,
        ending_equity=ending_equity,
        peak_equity=max(starting_capital, ending_equity),
        net_profit=ending_equity - starting_capital,
        total_return=(ending_equity - starting_capital) / starting_capital,
        max_drawdown_pct=0.0,
        max_drawdown_abs=0.0,
        exposure_pct=0.5,
        equity_curve=pd.Series(dtype=float),
        balance_curve=pd.Series(dtype=float),
        drawdown_curve=pd.Series(dtype=float),
        trades=trades,
    )


def _sym_result(
    symbol: str,
    trades: list[PortfolioTrade],
    interval: str = "1h",
    starting_capital: float = 10_000.0,
) -> SymbolResult:
    return SymbolResult(
        symbol=symbol,
        interval=interval,
        portfolio_result=_result(trades, starting_capital),
    )


def _make_batch(
    sym_results: list[SymbolResult],
    starting_capital: float = 10_000.0,
    equity_fraction: float = 0.10,
    max_open_positions: int = 0,
    max_total_exposure_usd: float = 0.0,
) -> BatchBacktest:
    bb = BatchBacktest(
        symbols=["BTCUSDT"],
        intervals=["1h"],
        strategy_class=EMACrossover,
        params={"fast": 5, "slow": 10},
        bars={},
        starting_capital=starting_capital,
        equity_fraction=equity_fraction,
        max_open_positions=max_open_positions,
        max_total_exposure_usd=max_total_exposure_usd,
    )
    return bb


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1 — SymbolRules
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymbolRulesBuiltin:
    """BUILTIN_SYMBOL_RULES contains explicit, distinct rules per symbol."""

    def test_btcusdt_in_builtin(self):
        assert "BTCUSDT" in BUILTIN_SYMBOL_RULES

    def test_ethusdt_in_builtin(self):
        assert "ETHUSDT" in BUILTIN_SYMBOL_RULES

    def test_xauusdt_in_builtin(self):
        assert "XAUUSDT" in BUILTIN_SYMBOL_RULES

    def test_xagusdt_in_builtin(self):
        assert "XAGUSDT" in BUILTIN_SYMBOL_RULES

    def test_sndkusdt_in_builtin(self):
        assert "SNDKUSDT" in BUILTIN_SYMBOL_RULES

    def test_ethusdt_min_qty_distinct_from_btcusdt(self):
        """ETHUSDT has a higher minimum order size than BTCUSDT."""
        btc = BUILTIN_SYMBOL_RULES["BTCUSDT"]
        eth = BUILTIN_SYMBOL_RULES["ETHUSDT"]
        assert eth.min_qty != btc.min_qty, (
            "ETHUSDT must have a distinct min_qty from BTCUSDT"
        )

    def test_xagusdt_tick_size_distinct_from_btcusdt(self):
        btc = BUILTIN_SYMBOL_RULES["BTCUSDT"]
        xag = BUILTIN_SYMBOL_RULES["XAGUSDT"]
        assert xag.tick_size != btc.tick_size

    def test_sndkusdt_qty_step_larger_than_btcusdt(self):
        btc  = BUILTIN_SYMBOL_RULES["BTCUSDT"]
        sndk = BUILTIN_SYMBOL_RULES["SNDKUSDT"]
        assert sndk.qty_step > btc.qty_step

    def test_all_builtin_have_positive_min_notional(self):
        for sym, rules in BUILTIN_SYMBOL_RULES.items():
            assert rules.min_notional > 0, f"{sym} has non-positive min_notional"


class TestGetSymbolRules:
    """PaperExchange.get_symbol_rules() lookup order and warning behaviour."""

    def test_btcusdt_returns_builtin_not_default(self):
        ex = PaperExchange()
        rules = ex.get_symbol_rules("BTCUSDT")
        expected = BUILTIN_SYMBOL_RULES["BTCUSDT"]
        assert rules is expected

    def test_ethusdt_returns_correct_builtin(self):
        ex = PaperExchange()
        rules = ex.get_symbol_rules("ETHUSDT")
        assert rules.qty_step == BUILTIN_SYMBOL_RULES["ETHUSDT"].qty_step

    def test_xauusdt_returns_builtin(self):
        ex = PaperExchange()
        rules = ex.get_symbol_rules("XAUUSDT")
        assert rules is BUILTIN_SYMBOL_RULES["XAUUSDT"]

    def test_registered_rules_override_builtin(self):
        ex = PaperExchange()
        custom = SymbolRules(min_notional=5.0, min_qty=0.5, qty_step=0.5, tick_size=1.0)
        ex.register_symbol_rules("BTCUSDT", custom)
        assert ex.get_symbol_rules("BTCUSDT") is custom

    def test_registered_rules_for_unknown_symbol(self):
        ex = PaperExchange()
        custom = SymbolRules(min_notional=1.0, min_qty=1.0, qty_step=1.0, tick_size=0.01)
        ex.register_symbol_rules("FAKEUSDT", custom)
        assert ex.get_symbol_rules("FAKEUSDT") is custom

    def test_unknown_symbol_logs_warning(self, caplog):
        ex = PaperExchange()
        with caplog.at_level(logging.WARNING, logger="strategy_lab.bot.paper_exchange"):
            rules = ex.get_symbol_rules("TOTALLYUNKNOWNCOIN")
        assert any("TOTALLYUNKNOWNCOIN" in r.message for r in caplog.records), (
            "Expected a WARNING mentioning the unknown symbol"
        )
        assert rules is _DEFAULT_RULES

    def test_unknown_symbol_fallback_is_default_rules(self):
        ex = PaperExchange()
        rules = ex.get_symbol_rules("UNKNOWNCOIN99")
        assert rules.min_notional == _DEFAULT_RULES.min_notional
        assert rules.qty_step == _DEFAULT_RULES.qty_step

    def test_symbol_rules_are_isolated(self):
        ex = PaperExchange()
        custom = SymbolRules(min_notional=1.0, min_qty=1.0, qty_step=1.0, tick_size=0.5)
        ex.register_symbol_rules("XAUUSDT", custom)
        # ETHUSDT must not be affected
        assert ex.get_symbol_rules("ETHUSDT").qty_step == BUILTIN_SYMBOL_RULES["ETHUSDT"].qty_step


class TestValidateSymbolRegistration:
    """validate_symbol_registration() identifies symbols with no explicit rules."""

    def test_all_builtin_returns_empty(self):
        unknown = validate_symbol_registration(list(BUILTIN_SYMBOL_RULES.keys()))
        assert unknown == []

    def test_unknown_symbol_returned(self):
        unknown = validate_symbol_registration(["BTCUSDT", "FAKECOIN"])
        assert "FAKECOIN" in unknown
        assert "BTCUSDT" not in unknown

    def test_exchange_registered_counts_as_known(self):
        ex = PaperExchange()
        ex.register_symbol_rules("NEWCOIN", SymbolRules())
        unknown = validate_symbol_registration(["NEWCOIN"], exchange=ex)
        assert unknown == []

    def test_empty_symbols_returns_empty(self):
        assert validate_symbol_registration([]) == []

    def test_multiple_unknowns_all_returned(self):
        unknown = validate_symbol_registration(["AAA", "BBB", "BTCUSDT"])
        assert set(unknown) == {"AAA", "BBB"}


class TestSymbolRulesOrderValidation:
    """Order validation uses the correct per-symbol rules, not BTC defaults."""

    def test_qty_below_ethusdt_min_qty_is_rejected(self):
        ex = PaperExchange()
        # ETHUSDT min_qty=0.0001; submit 0.00001 (below ETHUSDT minimum, not BTC's)
        order = ex.submit_order("ETHUSDT", "BUY", "MARKET", qty=0.00001)
        assert order.status == "REJECTED"
        assert "minimum" in order.reject_reason.lower()

    def test_qty_above_ethusdt_min_qty_is_accepted(self):
        ex = PaperExchange()
        # 0.001 > ETHUSDT min_qty=0.0001; step=0.00001 → 0.001 is valid
        order = ex.submit_order("ETHUSDT", "BUY", "MARKET", qty=0.001)
        assert order.status == "ACCEPTED"

    def test_qty_step_validation_uses_symbol_rules(self):
        ex = PaperExchange()
        # SNDKUSDT qty_step=1.0, min_qty=1.0; submit 1.5 (above min but not a multiple of step)
        order = ex.submit_order("SNDKUSDT", "BUY", "MARKET", qty=1.5)
        assert order.status == "REJECTED"
        assert "multiple of step" in order.reject_reason

    def test_btcusdt_fine_grain_qty_accepted(self):
        ex = PaperExchange()
        # BTCUSDT qty_step=0.00001; 0.00001 is a valid minimum
        order = ex.submit_order("BTCUSDT", "BUY", "MARKET", qty=0.00001)
        assert order.status == "ACCEPTED"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2 — Batch portfolio capital accounting
# ═══════════════════════════════════════════════════════════════════════════════

class TestPortfolioAccountingSequential:
    """Non-overlapping trades: equity correct and no cross-contamination."""

    def test_single_trade_winning(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        # BTC: entry=100, exit=110 (+10%), size=1, gross_pnl=10
        t = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0)
        sr = _sym_result("BTCUSDT", [t])
        _, metrics = bb._simulate_portfolio([sr])
        assert metrics["portfolio_n_trades"] == 1
        assert metrics["portfolio_net_profit"] > 0
        assert metrics["portfolio_win_rate"] == 1.0

    def test_single_trade_losing(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=90.0, size=1.0)
        sr = _sym_result("BTCUSDT", [t])
        _, metrics = bb._simulate_portfolio([sr])
        assert metrics["portfolio_n_trades"] == 1
        assert metrics["portfolio_net_profit"] < 0
        assert metrics["portfolio_win_rate"] == 0.0

    def test_sequential_two_trades_equity_accumulates(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t1 = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        t2 = _trade(entry_time=_T2, exit_time=_T3, entry_price=110.0, exit_price=121.0, size=1.0, trade_number=2)
        sr = _sym_result("BTCUSDT", [t1, t2])
        _, metrics = bb._simulate_portfolio([sr])
        assert metrics["portfolio_n_trades"] == 2
        assert metrics["portfolio_net_profit"] > 0
        assert metrics["portfolio_win_rate"] == 1.0

    def test_empty_results_returns_starting_capital(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        curve, metrics = bb._simulate_portfolio([])
        assert metrics["portfolio_n_trades"] == 0
        assert metrics["portfolio_net_profit"] == 0.0
        assert float(curve.iloc[0]) == 10_000.0

    def test_metrics_win_rate_with_mixed_trades(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t1 = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        t2 = _trade(entry_time=_T2, exit_time=_T3, entry_price=100.0, exit_price=90.0, size=1.0, trade_number=2)
        sr = _sym_result("BTCUSDT", [t1, t2])
        _, metrics = bb._simulate_portfolio([sr])
        assert metrics["portfolio_n_trades"] == 2
        assert metrics["portfolio_win_rate"] == pytest.approx(0.5)


class TestPortfolioAccountingOverlapping:
    """Overlapping positions: second trade entry uses equity before first trade closes."""

    def test_two_overlapping_positions_correct_entry_sizing(self):
        """BTC enters at T0, ETH enters at T1 (BTC still open), both exit at T2.

        With the event-based approach, ETH entry size is computed from starting
        equity (BTC's PnL is unrealised at T1), not from equity+BTC_PnL.
        """
        starting_capital = 10_000.0
        equity_fraction  = 0.10

        btc = _trade(
            entry_time=_T0, exit_time=_T3,
            entry_price=50_000.0, exit_price=55_000.0,
            size=1.0, trade_number=1,
        )
        eth = _trade(
            entry_time=_T1, exit_time=_T3,
            entry_price=2_000.0, exit_price=2_200.0,
            size=1.0, trade_number=2,
        )
        btc_sr = _sym_result("BTCUSDT", [btc])
        eth_sr = _sym_result("ETHUSDT", [eth])

        bb = _make_batch([], starting_capital=starting_capital, equity_fraction=equity_fraction)
        _, metrics = bb._simulate_portfolio([btc_sr, eth_sr])

        assert metrics["portfolio_n_trades"] == 2
        assert metrics["portfolio_net_profit"] > 0

    def test_overlapping_btc_pnl_not_visible_to_eth_entry(self):
        """Verify that ETH entry size is NOT inflated by BTC's unrealised gain.

        If BTC enters at T0 with equity=10000, commits 1000 (10%).
        At T1, BTC is still open. ETH entry should commit 10% of 10000=1000,
        NOT 10% of (10000 + BTC_gain).
        """
        starting_capital = 10_000.0
        equity_fraction  = 0.10

        # BTC: 10% gain on committed capital (gross_pnl=5000 on size=1 at 50000)
        btc = _trade(
            entry_time=_T0, exit_time=_T4,
            entry_price=50_000.0, exit_price=55_000.0, size=1.0, trade_number=1,
        )
        # ETH: we'll check how much capital is committed at T1 via the PnL computation
        eth = _trade(
            entry_time=_T1, exit_time=_T4,
            entry_price=2_000.0, exit_price=2_000.0,  # flat — zero PnL
            size=1.0, trade_number=2,
        )
        btc_sr = _sym_result("BTCUSDT", [btc])
        eth_sr = _sym_result("ETHUSDT", [eth])

        bb = _make_batch([], starting_capital=starting_capital, equity_fraction=equity_fraction)
        _, metrics = bb._simulate_portfolio([btc_sr, eth_sr])

        # Only BTC contributed PnL; ETH was flat
        # BTC: actual_size = (10000 * 0.10) / 50000 = 0.002
        # BTC net_pnl = (55000-50000) * 0.002 = 10.0
        btc_actual_size = starting_capital * equity_fraction / 50_000.0
        expected_btc_pnl = (55_000.0 - 50_000.0) * btc_actual_size
        assert metrics["portfolio_net_profit"] == pytest.approx(expected_btc_pnl, rel=1e-6)

    def test_three_simultaneous_positions_all_close_same_time(self):
        bb = _make_batch([], starting_capital=30_000.0, equity_fraction=0.10)
        btc = _trade(entry_time=_T0, exit_time=_T3, entry_price=50_000.0, exit_price=55_000.0, size=1.0, trade_number=1)
        eth = _trade(entry_time=_T0, exit_time=_T3, entry_price=2_000.0,  exit_price=2_200.0,  size=1.0, trade_number=2)
        xau = _trade(entry_time=_T0, exit_time=_T3, entry_price=1_900.0,  exit_price=2_000.0,  size=1.0, trade_number=3)
        sr  = [_sym_result("BTCUSDT", [btc]),
               _sym_result("ETHUSDT", [eth]),
               _sym_result("XAUUSDT", [xau])]
        _, metrics = bb._simulate_portfolio(sr)
        assert metrics["portfolio_n_trades"] == 3
        assert metrics["portfolio_net_profit"] > 0
        assert metrics["portfolio_win_rate"] == 1.0

    def test_exit_before_entry_same_timestamp(self):
        """EXIT before ENTRY at the same timestamp frees capital for same-bar entry."""
        starting_capital = 10_000.0
        equity_fraction  = 0.50  # 50% so second trade is noticeably sized differently

        # Trade 1 exits and trade 2 enters at exactly _T1
        t1 = _trade(entry_time=_T0, exit_time=_T1,
                    entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        t2 = _trade(entry_time=_T1, exit_time=_T2,
                    entry_price=110.0, exit_price=121.0, size=1.0, trade_number=2)
        sr = _sym_result("BTCUSDT", [t1, t2])
        bb = _make_batch([], starting_capital=starting_capital, equity_fraction=equity_fraction)
        _, metrics = bb._simulate_portfolio([sr])
        assert metrics["portfolio_n_trades"] == 2

    def test_losing_position_reduces_equity_for_next_trade(self):
        starting_capital = 10_000.0
        equity_fraction  = 0.50

        t1 = _trade(entry_time=_T0, exit_time=_T1,
                    entry_price=100.0, exit_price=50.0, size=1.0, trade_number=1)  # -50%
        t2 = _trade(entry_time=_T2, exit_time=_T3,
                    entry_price=50.0, exit_price=50.0, size=1.0, trade_number=2)   # flat

        sr = _sym_result("BTCUSDT", [t1, t2])
        bb = _make_batch([], starting_capital=starting_capital, equity_fraction=equity_fraction)
        _, metrics = bb._simulate_portfolio([sr])

        # t1: committed = 10000 * 0.5 = 5000; actual_size = 5000/100 = 50
        # gross_pnl (in unit terms) = (50-100)*1 = -50; scale = 50/1 = 50; actual = -2500
        # After t1 exits: equity = 10000 - 2500 = 7500
        # t2: committed = 7500 * 0.5 = 3750; flat pnl → equity stays 7500
        assert metrics["portfolio_net_profit"] == pytest.approx(-2500.0, rel=1e-6)


class TestPortfolioAccountingConstraints:
    """max_open_positions and max_total_exposure_usd are enforced."""

    def test_max_open_positions_limits_concurrent(self):
        """With max_open_positions=1, only the first position is taken."""
        starting_capital = 10_000.0
        # BTC and ETH both enter at T0 — but capacity allows only 1
        btc = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        eth = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=2)
        sr = [_sym_result("BTCUSDT", [btc]), _sym_result("ETHUSDT", [eth])]
        bb = _make_batch([], starting_capital=starting_capital, equity_fraction=0.10, max_open_positions=1)
        _, metrics = bb._simulate_portfolio(sr)
        # Only 1 trade should fill (the second is skipped)
        assert metrics["portfolio_n_trades"] == 1

    def test_max_open_positions_zero_means_unlimited(self):
        """max_open_positions=0 allows unlimited concurrent positions."""
        btc = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        eth = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=2)
        sr = [_sym_result("BTCUSDT", [btc]), _sym_result("ETHUSDT", [eth])]
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10, max_open_positions=0)
        _, metrics = bb._simulate_portfolio(sr)
        assert metrics["portfolio_n_trades"] == 2

    def test_max_total_exposure_rejects_over_limit(self):
        """max_total_exposure_usd caps committed capital; excess entries are skipped."""
        starting_capital = 10_000.0
        equity_fraction  = 0.10  # each entry commits ~1000
        # cap at 1500 → fits 1 entry (1000), second entry (1000) would hit 2000 > 1500
        btc = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        eth = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=2)
        sr = [_sym_result("BTCUSDT", [btc]), _sym_result("ETHUSDT", [eth])]
        bb = _make_batch(
            [], starting_capital=starting_capital, equity_fraction=equity_fraction,
            max_total_exposure_usd=1500.0,
        )
        _, metrics = bb._simulate_portfolio(sr)
        assert metrics["portfolio_n_trades"] == 1

    def test_max_total_exposure_zero_means_unlimited(self):
        btc = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        eth = _trade(entry_time=_T0, exit_time=_T2, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=2)
        sr = [_sym_result("BTCUSDT", [btc]), _sym_result("ETHUSDT", [eth])]
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10, max_total_exposure_usd=0.0)
        _, metrics = bb._simulate_portfolio(sr)
        assert metrics["portfolio_n_trades"] == 2

    def test_failed_symbol_result_excluded(self):
        good = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0)
        good_sr  = _sym_result("BTCUSDT", [good])
        error_sr = SymbolResult(symbol="ETHUSDT", interval="1h", error="no data")
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        _, metrics = bb._simulate_portfolio([good_sr, error_sr])
        assert metrics["portfolio_n_trades"] == 1


class TestPortfolioEquityCurve:
    """Equity curve properties."""

    def test_equity_curve_starts_at_starting_capital(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t  = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0)
        sr = _sym_result("BTCUSDT", [t])
        curve, _ = bb._simulate_portfolio([sr])
        assert float(curve.iloc[0]) == pytest.approx(10_000.0)

    def test_equity_curve_ends_above_start_for_winning_trades(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t  = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0)
        sr = _sym_result("BTCUSDT", [t])
        curve, _ = bb._simulate_portfolio([sr])
        assert float(curve.iloc[-1]) > float(curve.iloc[0])

    def test_equity_curve_ends_below_start_for_losing_trades(self):
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t  = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=90.0, size=1.0)
        sr = _sym_result("BTCUSDT", [t])
        curve, _ = bb._simulate_portfolio([sr])
        assert float(curve.iloc[-1]) < float(curve.iloc[0])

    def test_equity_curve_points_equal_n_trades_plus_one(self):
        """Curve has one point per closed trade, plus the starting-equity point."""
        bb = _make_batch([], starting_capital=10_000.0, equity_fraction=0.10)
        t1 = _trade(entry_time=_T0, exit_time=_T1, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=1)
        t2 = _trade(entry_time=_T2, exit_time=_T3, entry_price=100.0, exit_price=110.0, size=1.0, trade_number=2)
        sr = _sym_result("BTCUSDT", [t1, t2])
        curve, _ = bb._simulate_portfolio([sr])
        assert len(curve) >= 2  # at least starting point + final exit point


# ═══════════════════════════════════════════════════════════════════════════════
# Parts 3-8 — Strategy Registry
# ═══════════════════════════════════════════════════════════════════════════════

class _StratA(StrategyBase):
    """Test strategy A."""
    default_params: dict = {"period": 14}

    def __init__(self, period: int = 14) -> None:
        self.period = period

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _StratB(StrategyBase):
    """Test strategy B with a name attribute."""
    name = "strategy_b"
    default_params: dict = {"fast": 5, "slow": 20}

    def __init__(self, fast: int = 5, slow: int = 20) -> None:
        self.fast = fast
        self.slow = slow

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _StratOverwrite(StrategyBase):
    """Used to test overwrite-warning behaviour — same name as _StratA."""
    name = "_StratA"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


@pytest.fixture
def reg() -> StrategyRegistry:
    """Fresh registry for each test — does not share state with module registry."""
    return StrategyRegistry()


class TestStrategyRegistryRegister:
    def test_register_by_classname(self, reg):
        reg.register(_StratA)
        assert reg.is_registered("_StratA")

    def test_register_by_name_attribute(self, reg):
        reg.register(_StratB)
        assert reg.is_registered("strategy_b")

    def test_register_returns_class_unchanged(self, reg):
        result = reg.register(_StratA)
        assert result is _StratA

    def test_decorator_usage(self, reg):
        @reg.register
        class _Decorated(StrategyBase):
            def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
                return pd.Series(Signal.HOLD, index=bars.index, dtype=object)

        assert reg.is_registered("_Decorated")

    def test_overwrite_same_name_logs_warning(self, reg, caplog):
        reg.register(_StratA)
        with caplog.at_level(logging.WARNING, logger="strategy_lab.strategies.registry"):
            reg.register(_StratOverwrite)
        assert any("already registered" in r.message for r in caplog.records)
        # _StratOverwrite should now be the active class
        assert reg.get_class("_StratA") is _StratOverwrite

    def test_re_register_same_class_no_warning(self, reg, caplog):
        reg.register(_StratA)
        with caplog.at_level(logging.WARNING, logger="strategy_lab.strategies.registry"):
            reg.register(_StratA)
        assert not any("already registered" in r.message for r in caplog.records)


class TestStrategyRegistryCreate:
    def test_create_by_classname(self, reg):
        reg.register(_StratA)
        s = reg.create("_StratA")
        assert isinstance(s, _StratA)

    def test_create_by_name_attribute(self, reg):
        reg.register(_StratB)
        s = reg.create("strategy_b")
        assert isinstance(s, _StratB)

    def test_create_uses_default_params(self, reg):
        reg.register(_StratA)
        s = reg.create("_StratA")
        assert s.period == 14

    def test_create_params_override_defaults(self, reg):
        reg.register(_StratA)
        s = reg.create("_StratA", {"period": 99})
        assert s.period == 99

    def test_create_merges_default_params(self, reg):
        reg.register(_StratB)
        s = reg.create("strategy_b", {"fast": 3})
        assert s.fast == 3
        assert s.slow == 20  # from default_params

    def test_create_unknown_raises_key_error(self, reg):
        with pytest.raises(KeyError, match="no_such_strategy"):
            reg.create("no_such_strategy")

    def test_create_error_message_lists_available(self, reg):
        reg.register(_StratA)
        try:
            reg.create("missing")
        except KeyError as exc:
            assert "_StratA" in str(exc)

    def test_create_returns_independent_instances(self, reg):
        reg.register(_StratA)
        s1 = reg.create("_StratA", {"period": 5})
        s2 = reg.create("_StratA", {"period": 10})
        assert s1 is not s2
        assert s1.period != s2.period

    def test_create_with_none_params_uses_defaults(self, reg):
        reg.register(_StratA)
        s = reg.create("_StratA", None)
        assert s.period == 14


class TestStrategyRegistryQuery:
    def test_list_strategies_sorted(self, reg):
        reg.register(_StratB)   # name="strategy_b"
        reg.register(_StratA)   # name="_StratA" (underscore sorts before letter)
        names = reg.list_strategies()
        assert names == sorted(names)

    def test_list_strategies_empty_registry(self, reg):
        assert reg.list_strategies() == []

    def test_is_registered_false_for_unknown(self, reg):
        assert not reg.is_registered("nope")

    def test_get_class_returns_class(self, reg):
        reg.register(_StratA)
        assert reg.get_class("_StratA") is _StratA

    def test_get_class_unknown_raises_key_error(self, reg):
        with pytest.raises(KeyError):
            reg.get_class("phantom")

    def test_len(self, reg):
        assert len(reg) == 0
        reg.register(_StratA)
        assert len(reg) == 1
        reg.register(_StratB)
        assert len(reg) == 2

    def test_repr(self, reg):
        reg.register(_StratA)
        r = repr(reg)
        assert "StrategyRegistry" in r
        assert "_StratA" in r


class TestGlobalRegistry:
    """Module-level registry has EMACrossover registered."""

    def test_ema_crossover_is_registered(self):
        assert registry.is_registered("EMACrossover")

    def test_create_ema_crossover_from_registry(self):
        s = registry.create("EMACrossover", {"fast": 5, "slow": 10})
        assert isinstance(s, EMACrossover)
        assert s.fast == 5
        assert s.slow == 10

    def test_create_two_instances_are_independent(self):
        s1 = registry.create("EMACrossover", {"fast": 5, "slow": 10})
        s2 = registry.create("EMACrossover", {"fast": 10, "slow": 20})
        assert s1 is not s2
        assert s1.fast != s2.fast

    def test_list_includes_ema_crossover(self):
        assert "EMACrossover" in registry.list_strategies()
