"""Reports facade — wraps research.report for external consumers."""
from __future__ import annotations

from typing import Any

import pandas as pd

from shared.errors import ResearchError


class Reports:
    """High-level interface for generating research reports.

    The Trading Bot (and any other external consumer) should use this class
    instead of importing from ``research.report`` directly.

    Example
    -------
    >>> rpt = Reports().generate(
    ...     portfolio_result=result,
    ...     bars=bars,
    ...     strategy_name="EMACrossover",
    ...     symbol="BTCUSDT",
    ...     bars_per_year=8760,
    ... )
    >>> print(rpt.to_json())
    """

    def generate(
        self,
        portfolio_result,
        bars: pd.DataFrame,
        strategy_name: str,
        symbol: str,
        bars_per_year: int = 252,
        benchmark_returns: pd.Series | None = None,
    ):
        """Build a ResearchReport from a completed PortfolioResult.

        Args:
            portfolio_result: PortfolioResult returned by Portfolio.run().
            bars:             The same OHLCV bars used in the backtest.
            strategy_name:    Human-readable strategy identifier.
            symbol:           Ticker / trading pair.
            bars_per_year:    Annualisation factor (8760 for hourly crypto, 252 for daily equities).
            benchmark_returns: Optional benchmark return series for alpha/beta.

        Returns:
            ResearchReport with to_dict(), to_json(), to_csv() methods.

        Raises:
            ResearchError: if the report generation fails.
        """
        try:
            from research.report import build_report
            return build_report(
                portfolio_result  = portfolio_result,
                bars              = bars,
                strategy_name     = strategy_name,
                symbol            = symbol,
                bars_per_year     = bars_per_year,
                benchmark_returns = benchmark_returns,
            )
        except Exception as exc:
            raise ResearchError(f"Report generation failed: {exc}") from exc

    def to_dict(self, report) -> dict[str, Any]:
        """Serialize a ResearchReport to a plain dict."""
        try:
            return report.to_dict()
        except Exception as exc:
            raise ResearchError(f"Report serialisation failed: {exc}") from exc

    def to_json(self, report, indent: int = 2) -> str:
        """Serialize a ResearchReport to a JSON string."""
        try:
            return report.to_json(indent=indent)
        except Exception as exc:
            raise ResearchError(f"JSON export failed: {exc}") from exc
