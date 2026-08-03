"""Strategy Research Lab — public API for the Trading Bot and external consumers.

This package is the ONLY entry point external projects should import.  The
Trading Bot must never import from internal packages (engine, portfolio,
research, jobs, automation, data, pipeline, server) directly.

Quick start
-----------
    from lab import MarketData, ResearchLab, Portfolio, Validation, Reports, Automation
    from shared.config import PipelineConfig, PortfolioConfig

    # 1. Fetch data
    bars = MarketData().get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 12, 31))

    # 2. Validate data quality
    Validation().assert_integrity(bars)

    # 3. Run a backtest
    result = ResearchLab().evaluate(
        bars=bars, strategy_class=MyStrategy, params={"fast": 10, "slow": 50},
        symbol="BTCUSDT", interval="1h",
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
    )

    # 4. Build a report
    report = Reports().generate(
        result["portfolio_result"], bars, "MyStrategy", "BTCUSDT", bars_per_year=8760
    )

    # 5. Run the full automated pipeline
    run = Automation(PipelineConfig(symbols=["BTCUSDT"])).run_pipeline()

Architecture rules
------------------
- Bot imports only lab/
- lab/ wraps internal packages — never leaks implementation details
- shared/ is the only package imported by both lab/ and internal packages
- Internal packages (engine, portfolio, research …) never import from lab/
"""
from ._automation import Automation
from ._market_data import MarketData
from ._portfolio import Portfolio
from ._reports import Reports
from ._research import ResearchLab
from ._validation import Validation

__all__ = [
    "MarketData",
    "ResearchLab",
    "Portfolio",
    "Validation",
    "Reports",
    "Automation",
]
