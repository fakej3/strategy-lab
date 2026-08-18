from .ema_crossover import EMACrossover
from .rsi_mean_reversion import RSIMeanReversion
from .bollinger_band import BollingerBand
from .macd_crossover import MACDCrossover
from .donchian_breakout import DonchianBreakout
from .registry import registry, StrategyRegistry

registry.register(EMACrossover)
registry.register(RSIMeanReversion)
registry.register(BollingerBand)
registry.register(MACDCrossover)
registry.register(DonchianBreakout)

__all__ = [
    "EMACrossover",
    "RSIMeanReversion",
    "BollingerBand",
    "MACDCrossover",
    "DonchianBreakout",
    "registry",
    "StrategyRegistry",
]
