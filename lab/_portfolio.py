"""Portfolio facade — wraps the portfolio layer for external consumers."""
from __future__ import annotations

import pandas as pd

from shared.errors import ResearchError


class Portfolio:
    """High-level interface for capital-aware backtest execution.

    The Trading Bot (and any other external consumer) should use this class
    instead of importing from ``portfolio`` directly.

    Example
    -------
    >>> from portfolio import PortfolioConfig, SizingMode
    >>> from engine import EngineConfig
    >>> cfg = PortfolioConfig(starting_capital=100_000.0)
    >>> engine_cfg = EngineConfig(fee_rate=0.001, slippage_pct=0.0005)
    >>> result = Portfolio(cfg).run(bars, strategy, engine_cfg)
    """

    def __init__(self, config=None) -> None:
        """
        Args:
            config: PortfolioConfig instance; uses defaults when None.
        """
        self._config = config

    def run(self, bars: pd.DataFrame, strategy, engine_config=None):
        """Execute a strategy against OHLCV bars with position sizing.

        Args:
            bars:          OHLCV DataFrame with DatetimeIndex.
            strategy:      StrategyBase instance.
            engine_config: EngineConfig controlling fees and slippage.

        Returns:
            PortfolioResult with equity_curve, trades, drawdown_curve, etc.

        Raises:
            ResearchError: if execution fails.
        """
        try:
            from portfolio.engine import PortfolioEngine
            from engine.models import EngineConfig
            cfg = engine_config or EngineConfig()
            return PortfolioEngine(self._config).run(bars, strategy, cfg)
        except Exception as exc:
            raise ResearchError(f"Portfolio execution failed: {exc}") from exc

    def build_equity_curve(
        self,
        bars: pd.DataFrame,
        trades: list,
        starting_capital: float,
    ) -> pd.Series:
        """Build an equity curve from a completed trade list.

        Returns:
            pd.Series named "equity" aligned to bars.index.
        """
        try:
            from portfolio.engine import build_equity_curve
            return build_equity_curve(bars, trades, starting_capital)
        except Exception as exc:
            raise ResearchError(f"Failed to build equity curve: {exc}") from exc

    def build_drawdown_curve(self, equity_curve: pd.Series) -> pd.Series:
        """Build a drawdown curve from an equity curve.

        Returns:
            pd.Series named "drawdown" with values in (−1, 0].
        """
        try:
            from portfolio.engine import build_drawdown_curve
            return build_drawdown_curve(equity_curve)
        except Exception as exc:
            raise ResearchError(f"Failed to build drawdown curve: {exc}") from exc
