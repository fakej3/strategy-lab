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

__all__ = [
    # metrics
    "InstitutionalMetrics",
    "calculate_research_metrics",
    # curves
    "build_equity_curve",
    "build_drawdown_curve",
    "build_daily_returns",
    "build_monthly_returns",
    "build_rolling_metric",
    # walk-forward
    "WalkForwardTester",
    "WalkForwardConfig",
    "WalkForwardResult",
    # optimizer
    "GridSearchOptimizer",
    "RandomSearchOptimizer",
    "ParameterSpace",
    "OptimizationResult",
    # comparison
    "compare_strategies",
    "ComparisonResult",
    # benchmark
    "BuyAndHoldBenchmark",
    "BenchmarkResult",
    "compute_alpha_beta",
    # report
    "ResearchReport",
    "build_report",
    # validation
    "validate_bars_extended",
    "ValidationWarning",
    # visualization
    "build_visualization_data",
    "VisualizationData",
]
