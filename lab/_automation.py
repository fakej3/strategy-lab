"""Automation facade — wraps automation.pipeline for external consumers."""
from __future__ import annotations

from shared.errors import AutomationError


class Automation:
    """High-level interface for the automated research pipeline.

    The Trading Bot (and any other external consumer) should use this class
    instead of importing from ``automation`` directly.

    Example
    -------
    >>> from shared.config import PipelineConfig
    >>> cfg = PipelineConfig(symbols=["BTCUSDT"], intervals=["1h"])
    >>> run = Automation(cfg).run_pipeline()
    >>> print(f"{run.n_passed} strategies passed the quality gate")
    """

    def __init__(self, config=None) -> None:
        """
        Args:
            config: PipelineConfig instance; uses defaults when None.
        """
        self._config = config

    def run_pipeline(self):
        """Execute the full 8-step automated research pipeline.

        Steps:
          1. Update market data
          2. Discover strategy classes
          3. Generate parameter combinations
          4. Run parallel backtests
          5. Walk-forward + Monte Carlo on survivors
          6. Filter / reject via quality gate
          7. Persist to SQLite
          8. Generate reports

        Returns:
            PipelineRun with session_id, n_passed, n_rejected, report_paths, etc.

        Raises:
            AutomationError: if a fatal pipeline error occurs.
        """
        try:
            from automation.pipeline import ResearchPipeline
            return ResearchPipeline(self._config).execute()
        except Exception as exc:
            raise AutomationError(f"Pipeline execution failed: {exc}") from exc
