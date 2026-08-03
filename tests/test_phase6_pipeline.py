"""Phase 6 integration tests — trade_pnls in backtest result, MC without re-run."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from jobs.backtest_job import BacktestJob, BacktestParams


def _make_bars(n: int = 500) -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC", name="open_time")
    closes = [100.0 + i * 0.1 for i in range(n)]
    highs  = [c * 1.002 for c in closes]
    lows   = [c * 0.998 for c in closes]
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": 100.0},
        index=idx,
    )


class TestBacktestJobTradePnls:
    def test_trade_pnls_present_in_result(self):
        """BacktestJob.execute() must include 'trade_pnls' in its return dict."""
        from strategies.ema_crossover import EMACrossover

        bars = _make_bars(600)
        bp = BacktestParams(
            bars=bars,
            strategy_class=EMACrossover,
            params={"fast": 5, "slow": 30},
            symbol="TTEST",
            interval="1h",
            start_date=date(2022, 1, 1),
            end_date=date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success, result.error
        assert "trade_pnls" in result.data
        assert isinstance(result.data["trade_pnls"], list)

    def test_trade_pnls_sum_matches_net_profit_approx(self):
        """Sum of trade_pnls should be close to net_profit."""
        from strategies.ema_crossover import EMACrossover

        bars = _make_bars(600)
        bp = BacktestParams(
            bars=bars,
            strategy_class=EMACrossover,
            params={"fast": 5, "slow": 30},
            symbol="TTEST",
            interval="1h",
            start_date=date(2022, 1, 1),
            end_date=date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success
        d = result.data
        if d["trade_pnls"]:
            assert abs(sum(d["trade_pnls"]) - d["net_profit"]) < 1e-6


class TestMCNodoublRun:
    """Verify MC runs from stored trade_pnls, not from a second backtest."""

    def test_step5_augment_uses_stored_pnls(self, tmp_path):
        """MC augmentation uses data['trade_pnls'] without calling PortfolioEngine."""
        from automation.pipeline import PipelineConfig, ResearchPipeline
        from strategies.ema_crossover import EMACrossover

        cfg = PipelineConfig(
            db_path=str(tmp_path / "r.db"),
            reports_dir=str(tmp_path / "reports"),
            run_walk_forward=False,
            run_monte_carlo=True,
            mc_simulations=50,
            run_robustness=False,   # isolate MC test from robustness backtests
            verbose=False,
        )
        pipeline = ResearchPipeline(cfg)

        combos = [{"cls": EMACrossover, "module": "strategies.ema_crossover",
                   "combos": [{"fast": 5, "slow": 30}]}]
        data = {
            "strategy_class": "EMACrossover",
            "strategy_name" : "EMACrossover",
            "params"        : '{"fast": 5, "slow": 30}',
            "symbol"        : "TTEST",
            "interval"      : "1h",
            "trade_pnls"    : [10.0, -5.0, 8.0, -2.0, 15.0],
        }

        bars = _make_bars(200)

        with patch("portfolio.engine.PortfolioEngine.run") as mock_run:
            result = pipeline._step5_augment(bars, data, combos)

        # MC should run from stored pnls — PortfolioEngine.run must NOT be called
        mock_run.assert_not_called()
        assert "mc_median_return" in result
        assert result["mc_median_return"] is not None

    def test_step5_augment_skips_mc_when_no_pnls(self, tmp_path):
        """If trade_pnls is absent or empty, MC is silently skipped."""
        from automation.pipeline import PipelineConfig, ResearchPipeline
        from strategies.ema_crossover import EMACrossover

        cfg = PipelineConfig(
            db_path=str(tmp_path / "r.db"),
            reports_dir=str(tmp_path / "reports"),
            run_walk_forward=False,
            run_monte_carlo=True,
            mc_simulations=50,
            run_robustness=False,
            verbose=False,
        )
        pipeline = ResearchPipeline(cfg)

        combos = [{"cls": EMACrossover, "module": "strategies.ema_crossover",
                   "combos": [{"fast": 5, "slow": 30}]}]
        data = {
            "strategy_class": "EMACrossover",
            "params"        : '{"fast": 5, "slow": 30}',
            "trade_pnls"    : [],   # empty list
        }

        bars = _make_bars(200)
        result = pipeline._step5_augment(bars, data, combos)

        assert result.get("mc_median_return") is None
