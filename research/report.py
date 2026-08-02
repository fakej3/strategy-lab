"""Research report — JSON/CSV-exportable summary of a backtest."""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from portfolio.models import PortfolioResult
from research.metrics import InstitutionalMetrics, calculate_research_metrics


@dataclass
class ResearchReport:
    """Structured backtest report exportable to JSON and CSV.

    Attributes
    ----------
    strategy_name  : Human-readable strategy identifier.
    symbol         : Ticker or instrument name (e.g. ``"BTCUSDT"``).
    start_date     : First bar timestamp as ISO string.
    end_date       : Last bar timestamp as ISO string.
    bars_per_year  : Annualisation factor used for metrics.
    portfolio      : Summary dict of capital and return fields.
    metrics        : :class:`~research.metrics.InstitutionalMetrics` instance.
    trades_summary : Aggregated trade statistics dict.
    """

    strategy_name : str
    symbol        : str
    start_date    : str
    end_date      : str
    bars_per_year : int
    portfolio     : dict[str, float]
    metrics       : InstitutionalMetrics
    trades_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the report to a plain dict (JSON-serialisable).

        Returns:
            Nested dict with ``portfolio``, ``metrics``, and
            ``trades_summary`` sections.
        """
        d: dict[str, Any] = {
            "strategy_name" : self.strategy_name,
            "symbol"        : self.symbol,
            "start_date"    : self.start_date,
            "end_date"      : self.end_date,
            "bars_per_year" : self.bars_per_year,
            "portfolio"     : self.portfolio,
            "metrics"       : asdict(self.metrics),
            "trades_summary": self.trades_summary,
        }
        return d

    def to_json(self, indent: int = 2) -> str:
        """Serialise to a JSON string.

        Args:
            indent: JSON indentation level (default 2).

        Returns:
            JSON string.  ``nan`` and ``inf`` metric values are serialised
            as ``null`` — valid JSON that downstream tools can handle.

        Usage example
        -------------
        >>> report = build_report(result, "EMA_Crossover", "BTCUSDT")
        >>> print(report.to_json())
        """
        return json.dumps(_sanitize_floats(self.to_dict()), indent=indent, default=str)

    def to_csv(self) -> str:
        """Serialise to a flat CSV string (one row per key-value pair).

        All nested structures are flattened with dot-notation keys.
        Useful for persisting results to a spreadsheet.

        Returns:
            CSV text with two columns: ``key`` and ``value``.

        Usage example
        -------------
        >>> csv_text = report.to_csv()
        >>> with open("report.csv", "w") as f:
        ...     f.write(csv_text)
        """
        flat = _flatten(self.to_dict())
        buf  = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["key", "value"])
        for k, v in flat.items():
            writer.writerow([k, v])
        return buf.getvalue()


def build_report(
    portfolio_result: PortfolioResult,
    strategy_name   : str             = "Strategy",
    symbol          : str             = "",
    bars_per_year   : int             = 252,
    risk_free_rate  : float           = 0.0,
    benchmark_returns: pd.Series | None = None,
) -> ResearchReport:
    """Build a :class:`ResearchReport` from a portfolio backtest result.

    Args:
        portfolio_result:  Output of :class:`~portfolio.PortfolioEngine`.
        strategy_name:     Label for the strategy (default ``"Strategy"``).
        symbol:            Instrument ticker (default empty string).
        bars_per_year:     Annualisation factor (default 252).
        risk_free_rate:    Annual risk-free rate (default 0).
        benchmark_returns: Optional per-bar benchmark returns for
                           :attr:`~research.metrics.InstitutionalMetrics.information_ratio`.

    Returns:
        :class:`ResearchReport` ready for export.

    Usage example
    -------------
    >>> from research import build_report
    >>> report = build_report(result, "EMA10_30", "AAPL", bars_per_year=252)
    >>> print(report.to_json())
    """
    ec    = portfolio_result.equity_curve
    start = str(ec.index[0])  if len(ec) > 0 else ""
    end   = str(ec.index[-1]) if len(ec) > 0 else ""

    metrics = calculate_research_metrics(
        equity_curve      = ec,
        trades            = portfolio_result.trades,
        bars_per_year     = bars_per_year,
        risk_free_rate    = risk_free_rate,
        benchmark_returns = benchmark_returns,
    )

    portfolio_dict = {
        "starting_capital" : portfolio_result.starting_capital,
        "ending_equity"    : portfolio_result.ending_equity,
        "peak_equity"      : portfolio_result.peak_equity,
        "net_profit"       : portfolio_result.net_profit,
        "total_return"     : portfolio_result.total_return,
        "max_drawdown_pct" : portfolio_result.max_drawdown_pct,
        "max_drawdown_abs" : portfolio_result.max_drawdown_abs,
        "exposure_pct"     : portfolio_result.exposure_pct,
    }

    trades     = portfolio_result.trades
    n_trades   = len(trades)
    winners    = [t for t in trades if t.is_winner]
    losers     = [t for t in trades if t.is_loser]

    trades_summary: dict[str, Any] = {
        "total_trades" : n_trades,
        "winners"      : len(winners),
        "losers"       : len(losers),
        "breakeven"    : n_trades - len(winners) - len(losers),
        "gross_profit" : sum(t.net_pnl for t in winners),
        "gross_loss"   : sum(t.net_pnl for t in losers),
        "largest_win"  : max((t.net_pnl for t in winners), default=0.0),
        "largest_loss" : min((t.net_pnl for t in losers),  default=0.0),
        "avg_win"      : (
            sum(t.net_pnl for t in winners) / len(winners) if winners else 0.0
        ),
        "avg_loss"     : (
            sum(t.net_pnl for t in losers)  / len(losers)  if losers  else 0.0
        ),
    }

    return ResearchReport(
        strategy_name  = strategy_name,
        symbol         = symbol,
        start_date     = start,
        end_date       = end,
        bars_per_year  = bars_per_year,
        portfolio      = portfolio_dict,
        metrics        = metrics,
        trades_summary = trades_summary,
    )


def _sanitize_floats(obj: Any) -> Any:
    """Replace float nan/inf with None so json.dumps produces valid JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict to dot-notation keys."""
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, full_key))
    else:
        out[prefix] = d
    return out
