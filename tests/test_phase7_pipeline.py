"""Phase 7 integration tests — statistical validation fields in pipeline results."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from automation.pipeline import PipelineConfig, ResearchPipeline


def _make_bars(n: int = 800) -> pd.DataFrame:
    np.random.seed(42)
    idx    = pd.date_range("2022-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    prices = 40000 + np.cumsum(np.random.randn(n) * 10 + 0.5)
    prices = np.maximum(prices, 1.0)
    noise  = np.random.uniform(-5, 5, n)
    return pd.DataFrame({
        "open":   prices + noise,
        "high":   prices + np.abs(noise) + 5,
        "low":    prices - np.abs(noise) - 5,
        "close":  prices,
        "volume": np.random.uniform(100, 1000, n),
    }, index=idx)


class TestBacktestJobPhase7:
    """BacktestJob now includes Phase 7 analysis in its output dict."""

    def test_regime_json_present_when_trades_exist(self):
        from strategies.ema_crossover import EMACrossover
        from jobs.backtest_job import BacktestJob, BacktestParams

        bars = _make_bars(600)
        bp   = BacktestParams(
            bars            = bars,
            strategy_class  = EMACrossover,
            params          = {"fast": 5, "slow": 30},
            symbol          = "TEST",
            interval        = "1h",
            start_date      = date(2022, 1, 1),
            end_date        = date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success, result.error
        d = result.data
        # regime_json is only populated when there are trades
        if d.get("total_trades", 0) > 0:
            assert d["regime_json"] is not None
            regime_data = json.loads(d["regime_json"])
            assert "regime_stats" in regime_data
            assert "labels" in regime_data

    def test_rolling_json_structure(self):
        from strategies.ema_crossover import EMACrossover
        from jobs.backtest_job import BacktestJob, BacktestParams

        bars = _make_bars(600)
        bp   = BacktestParams(
            bars            = bars,
            strategy_class  = EMACrossover,
            params          = {"fast": 5, "slow": 30},
            symbol          = "TEST",
            interval        = "1h",
            start_date      = date(2022, 1, 1),
            end_date        = date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success
        d = result.data
        if d.get("total_trades", 0) > 0 and d.get("rolling_json"):
            rolling = json.loads(d["rolling_json"])
            for k in ("window", "timestamps", "sharpe", "sortino", "drawdown"):
                assert k in rolling

    def test_degradation_json_structure(self):
        from strategies.ema_crossover import EMACrossover
        from jobs.backtest_job import BacktestJob, BacktestParams

        bars = _make_bars(600)
        bp   = BacktestParams(
            bars            = bars,
            strategy_class  = EMACrossover,
            params          = {"fast": 5, "slow": 30},
            symbol          = "TEST",
            interval        = "1h",
            start_date      = date(2022, 1, 1),
            end_date        = date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success
        d = result.data
        if d.get("total_trades", 0) > 0 and d.get("degradation_json"):
            deg = json.loads(d["degradation_json"])
            assert "degradation_score" in deg
            assert "first_half_sharpe" in deg

    def test_distribution_json_structure(self):
        from strategies.ema_crossover import EMACrossover
        from jobs.backtest_job import BacktestJob, BacktestParams

        bars = _make_bars(600)
        bp   = BacktestParams(
            bars            = bars,
            strategy_class  = EMACrossover,
            params          = {"fast": 5, "slow": 30},
            symbol          = "TEST",
            interval        = "1h",
            start_date      = date(2022, 1, 1),
            end_date        = date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success
        d = result.data
        if d.get("total_trades", 0) > 0 and d.get("distribution_json"):
            dist = json.loads(d["distribution_json"])
            assert "max_consec_wins" in dist
            assert "histogram" in dist
            assert "dd_durations" in dist

    def test_bootstrap_json_structure(self):
        from strategies.ema_crossover import EMACrossover
        from jobs.backtest_job import BacktestJob, BacktestParams

        bars = _make_bars(600)
        bp   = BacktestParams(
            bars            = bars,
            strategy_class  = EMACrossover,
            params          = {"fast": 5, "slow": 30},
            symbol          = "TEST",
            interval        = "1h",
            start_date      = date(2022, 1, 1),
            end_date        = date(2022, 12, 31),
        )
        result = BacktestJob(bp).run()
        assert result.success
        d = result.data
        if d.get("total_trades", 0) > 0 and d.get("bootstrap_json"):
            bs = json.loads(d["bootstrap_json"])
            for m in ("total_return", "win_rate", "profit_factor"):
                assert m in bs
                ci = bs[m]
                if ci.get("pct_5") is not None:
                    assert ci["pct_5"] <= ci["pct_50"] <= ci["pct_95"]


class TestPipelinePhase7Fields:
    """Full pipeline run — Phase 7 fields reach DB via StrategyResult."""

    def test_strategy_result_has_phase7_fields(self, tmp_path):
        bars = _make_bars(800)
        with patch("automation.pipeline.get_bars", return_value=bars):
            cfg = PipelineConfig(
                symbols            = ["BTCUSDT"],
                intervals          = ["1h"],
                start_date         = date(2022, 1, 1),
                end_date           = date(2022, 2, 28),
                db_path            = str(tmp_path / "r.db"),
                reports_dir        = str(tmp_path / "reports"),
                run_walk_forward   = False,
                run_monte_carlo    = False,
                run_robustness     = False,   # keep test fast
                mc_simulations     = 50,
                n_workers          = 1,
                verbose            = False,
                log_path           = str(tmp_path / "r.log"),
            )
            run = ResearchPipeline(cfg).execute()

        assert run.n_errors == 0
        # At least some strategies should have been tested
        results_with_trades = [r for r in run.strategy_results if r.total_trades > 0]
        if results_with_trades:
            r = results_with_trades[0]
            # degradation_json should be set for strategies with enough trades
            if r.total_trades >= 6:
                assert r.degradation_json is not None

    def test_robustness_fields_populated_when_enabled(self, tmp_path):
        bars = _make_bars(800)
        with patch("automation.pipeline.get_bars", return_value=bars):
            cfg = PipelineConfig(
                symbols            = ["BTCUSDT"],
                intervals          = ["1h"],
                start_date         = date(2022, 1, 1),
                end_date           = date(2022, 2, 28),
                db_path            = str(tmp_path / "r.db"),
                reports_dir        = str(tmp_path / "reports"),
                run_walk_forward   = False,
                run_monte_carlo    = False,
                run_robustness     = True,
                mc_simulations     = 50,
                n_workers          = 1,
                verbose            = False,
                log_path           = str(tmp_path / "r.log"),
            )
            run = ResearchPipeline(cfg).execute()

        assert run.n_errors == 0
        # At least one result should have robustness data
        with_rob = [r for r in run.strategy_results if r.robustness_score is not None]
        assert len(with_rob) > 0

    def test_wf_consistency_populated(self, tmp_path):
        bars = _make_bars(800)
        with patch("automation.pipeline.get_bars", return_value=bars):
            cfg = PipelineConfig(
                symbols            = ["BTCUSDT"],
                intervals          = ["1h"],
                start_date         = date(2022, 1, 1),
                end_date           = date(2022, 2, 28),
                db_path            = str(tmp_path / "r.db"),
                reports_dir        = str(tmp_path / "reports"),
                run_walk_forward   = True,
                run_monte_carlo    = False,
                run_robustness     = False,
                wf_train_bars      = 200,
                wf_test_bars       = 50,
                n_workers          = 1,
                verbose            = False,
                log_path           = str(tmp_path / "r.log"),
            )
            run = ResearchPipeline(cfg).execute()

        assert run.n_errors == 0
        # Strategies with WF should have consistency data
        with_wf = [r for r in run.strategy_results if r.walk_forward_return is not None]
        for r in with_wf:
            if r.wf_n_folds and r.wf_n_folds > 0:
                assert r.wf_consistency is not None
                assert 0.0 <= r.wf_consistency <= 100.0
