"""Strategy registry — maps name → strategy class for data-driven configuration.

How to add a new strategy
--------------------------
1. Create your strategy class in ``strategies/my_strategy.py``::

       from engine.strategy import Signal, StrategyBase
       import pandas as pd

       class MyStrategy(StrategyBase):
           name = "my_strategy"                  # registry lookup key
           default_params = {"period": 14}       # merged with caller-supplied params

           def __init__(self, period: int = 14) -> None:
               self.period = period

           def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
               ...

2. Register it in ``strategies/__init__.py``::

       from .registry import registry
       from .my_strategy import MyStrategy

       registry.register(MyStrategy)

3. Use it by name anywhere::

       from strategies import registry
       strategy = registry.create("my_strategy", {"period": 20})

The registry is a module-level singleton.  Strategies are registered under
their ``name`` class attribute; if no ``name`` is defined the class ``__name__``
is used as the key.  Caller-supplied ``params`` are merged with the class's
``default_params`` (if any), with caller values taking precedence.
"""
from __future__ import annotations

import logging
from typing import Any, Type

from engine.strategy import StrategyBase

log = logging.getLogger("strategy_lab.strategies.registry")


class StrategyRegistry:
    """Maps strategy names to strategy classes.

    Usage::

        registry = StrategyRegistry()
        registry.register(EMACrossover)
        strategy = registry.create("EMACrossover", {"fast": 10, "slow": 30})
        names = registry.list_strategies()   # ["EMACrossover"]

    The ``register`` method doubles as a class decorator::

        @registry.register
        class MyStrategy(StrategyBase):
            name = "my_strategy"
            default_params = {"period": 14}
    """

    def __init__(self) -> None:
        self._registry: dict[str, Type[StrategyBase]] = {}

    def register(self, strategy_class: Type[StrategyBase]) -> Type[StrategyBase]:
        """Register *strategy_class* and return it unchanged (decorator-safe).

        The registry key is the class's ``name`` attribute; if undefined the
        class ``__name__`` is used.  Registering a second class under the same
        name logs a WARNING and replaces the previous entry.
        """
        name = getattr(strategy_class, "name", strategy_class.__name__)
        if name in self._registry and self._registry[name] is not strategy_class:
            log.warning(
                "Strategy %r already registered as %s; overwriting with %s",
                name, self._registry[name].__name__, strategy_class.__name__,
            )
        self._registry[name] = strategy_class
        log.debug("Registered strategy %r → %s", name, strategy_class.__name__)
        return strategy_class

    def create(self, name: str, params: dict[str, Any] | None = None) -> StrategyBase:
        """Return a new instance of the strategy registered under *name*.

        ``default_params`` from the class (if defined) are merged with *params*;
        caller-supplied *params* take precedence over defaults.

        Args:
            name:   Registry key (strategy ``name`` attribute or class name).
            params: Optional constructor kwargs merged with ``default_params``.

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._registry:
            available = self.list_strategies()
            raise KeyError(
                f"Unknown strategy {name!r}. "
                f"Available: {available or ['(none registered)']}"
            )
        cls = self._registry[name]
        default_params = dict(getattr(cls, "default_params", {}))
        merged = {**default_params, **(params or {})}
        return cls(**merged)

    def get_class(self, name: str) -> Type[StrategyBase]:
        """Return the class registered under *name* without instantiating it.

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._registry:
            raise KeyError(f"Unknown strategy {name!r}")
        return self._registry[name]

    def list_strategies(self) -> list[str]:
        """Return a sorted list of registered strategy names."""
        return sorted(self._registry)

    def is_registered(self, name: str) -> bool:
        """Return True if *name* is registered."""
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        return f"StrategyRegistry({self.list_strategies()})"


# Module-level singleton shared across the application.
registry = StrategyRegistry()
