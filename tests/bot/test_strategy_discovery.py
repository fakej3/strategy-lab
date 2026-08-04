"""Regression tests for automatic strategy discovery."""
from __future__ import annotations

import pytest

from bot_trade import _discover_strategies, _load_strategy
from bot.config import BotConfig
from engine.strategy import StrategyBase


class TestDiscoverStrategies:
    def test_finds_ema_crossover(self):
        registry = _discover_strategies()
        assert "EMACrossover" in registry

    def test_all_found_are_strategy_base_subclasses(self):
        registry = _discover_strategies()
        assert len(registry) > 0
        for name, cls in registry.items():
            assert issubclass(cls, StrategyBase), f"{name} is not a StrategyBase subclass"

    def test_ema_crossover_maps_to_correct_class(self):
        from strategies.ema_crossover import EMACrossover
        registry = _discover_strategies()
        assert registry["EMACrossover"] is EMACrossover

    def test_returns_dict(self):
        registry = _discover_strategies()
        assert isinstance(registry, dict)


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
