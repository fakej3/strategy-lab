"""Research layer — institutional-quality analysis tools for strategy evaluation."""
from .benchmark import BenchmarkResult, BuyAndHoldBenchmark, compute_alpha_beta
from .comparison import ComparisonResult, compare_strategies
from .curves import (
    build_daily_returns,
    build_drawdown_curve,
    build_equity_curve,
    build_monthly_returns,
    build_rolling_metric,
)
from .metrics import InstitutionalMetrics, calculate_research_metrics
from .optimizer import (
    GridSearchOptimizer,
    OptimizationResult,
    ParameterSpace,
    RandomSearchOptimizer,
)
from .report import ResearchReport, build_report
from .validation import ValidationWarning, validate_bars_extended
from .visualization import VisualizationData, build_visualization_data
from .walk_forward import WalkForwardConfig, WalkForwardResult, WalkForwardTester
from .bootstrap import bootstrap_confidence_intervals
from .monte_carlo import MonteCarloResult, simulate_trade_paths
from .sensitivity import ParameterSensitivity, SensitivityResult, analyze_sensitivity

__all__ = [
    "InstitutionalMetrics", "calculate_research_metrics",
    "build_equity_curve", "build_drawdown_curve", "build_daily_returns",
    "build_monthly_returns", "build_rolling_metric",
    "WalkForwardTester", "WalkForwardConfig", "WalkForwardResult",
    "GridSearchOptimizer", "RandomSearchOptimizer", "ParameterSpace", "OptimizationResult",
    "compare_strategies", "ComparisonResult",
    "BuyAndHoldBenchmark", "BenchmarkResult", "compute_alpha_beta",
    "ResearchReport", "build_report",
    "validate_bars_extended", "ValidationWarning",
    "build_visualization_data", "VisualizationData",
    "bootstrap_confidence_intervals", "MonteCarloResult", "simulate_trade_paths",
    "ParameterSensitivity", "SensitivityResult", "analyze_sensitivity",
]