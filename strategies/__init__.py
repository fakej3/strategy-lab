from .ema_crossover import EMACrossover
from .registry import registry, StrategyRegistry

registry.register(EMACrossover)

__all__ = ["EMACrossover", "registry", "StrategyRegistry"]
