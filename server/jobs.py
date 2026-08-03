"""Strategy discovery and job submission helpers."""
from __future__ import annotations

import importlib
import inspect
import pkgutil

from engine.strategy import StrategyBase


def get_available_strategies() -> list[dict]:
    """Return [{name, params}] for every StrategyBase subclass in strategies/."""
    import strategies as strategies_pkg
    from automation.pipeline import STRATEGY_PARAMETER_SPACES

    result: list[dict] = []
    for _, mod_name, _ in pkgutil.iter_modules(strategies_pkg.__path__):
        try:
            mod = importlib.import_module(f"strategies.{mod_name}")
        except Exception:
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, StrategyBase)
                and cls is not StrategyBase
                and cls.__name__ not in [s["name"] for s in result]
            ):
                param_space = STRATEGY_PARAMETER_SPACES.get(cls.__name__, {})
                result.append({"name": cls.__name__, "param_space": param_space})

    return result


def get_strategy_names() -> list[str]:
    return [s["name"] for s in get_available_strategies()]
