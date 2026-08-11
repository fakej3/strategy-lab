"""Tests for strategy discovery — now via StrategyRegistry (single source of truth).

The old _discover_strategies() used a pkgutil module scan duplicating the
StrategyRegistry.  It has been removed.  These tests verify the canonical
registry-based mechanism behaves identically to what the old tests required.
"""
from __future__ import annotations

import pytest

from bot_trade import _load_strategy
from bot.config import BotConfig
from engine.strategy import StrategyBase
from strategies import registry, StrategyRegistry


class TestStrategyRegistryDiscovery:
    def test_finds_ema_crossover(self):
        assert registry.is_registered("EMACrossover")

    def test_all_registered_are_strategy_base_subclasses(self):
        names = registry.list_strategies()
        assert len(names) > 0
        for name in names:
            cls = registry.get_class(name)
            assert issubclass(cls, StrategyBase), f"{name} is not a StrategyBase subclass"

    def test_ema_crossover_maps_to_correct_class(self):
        from strategies.ema_crossover import EMACrossover
        assert registry.get_class("EMACrossover") is EMACrossover

    def test_list_strategies_returns_sorted_list(self):
        names = registry.list_strategies()
        assert isinstance(names, list)
        assert names == sorted(names)


class TestLoadStrategy:
    def test_loads_ema_crossover_by_name(self):
        cfg = BotConfig(strategy_name="EMACrossover", strategy_params={"fast": 20, "slow": 50})
        strategy = _load_strategy(cfg)
        assert strategy is not None
        assert hasattr(strategy, "generate_signals")

    def test_unknown_strategy_raises_value_error(self):
        cfg = BotConfig(strategy_name="NoSuchStrategy", strategy_params={})
        with pytest.raises(ValueError, match="NoSuchStrategy"):
            _load_strategy(cfg)

    def test_error_message_lists_available_strategies(self):
        cfg = BotConfig(strategy_name="Bogus", strategy_params={})
        with pytest.raises(ValueError, match="EMACrossover"):
            _load_strategy(cfg)

    def test_strategy_params_passed_through(self):
        cfg = BotConfig(strategy_name="EMACrossover", strategy_params={"fast": 10, "slow": 30})
        strategy = _load_strategy(cfg)
        assert strategy.fast == 10
        assert strategy.slow == 30

    def test_each_call_returns_independent_instance(self):
        """Registry must return a fresh instance on each call — no shared state."""
        cfg = BotConfig(strategy_name="EMACrossover", strategy_params={"fast": 20, "slow": 50})
        s1 = _load_strategy(cfg)
        s2 = _load_strategy(cfg)
        assert s1 is not s2
