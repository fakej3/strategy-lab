"""Regression tests: API field name contract between frontend and dict_to_config.

Bug context: Research.tsx was sending the wrong key names (slippage, stop_loss,
take_profit, workers, train_bars, test_bars, n_simulations, neighbor_steps).
These tests pin the exact names dict_to_config must accept so the contract
cannot regress silently.
"""
from __future__ import annotations

import pytest

from server.background import dict_to_config


class TestFieldNameContract:
    """Each test verifies one previously-broken field name is now read correctly."""

    def test_slippage_pct(self):
        cfg = dict_to_config({"slippage_pct": "0.001"})
        assert cfg.slippage_pct == 0.001

    def test_stop_loss_pct(self):
        cfg = dict_to_config({"stop_loss_pct": "0.05"})
        assert cfg.stop_loss_pct == pytest.approx(0.05)

    def test_take_profit_pct(self):
        cfg = dict_to_config({"take_profit_pct": "0.10"})
        assert cfg.take_profit_pct == pytest.approx(0.10)

    def test_min_trades(self):
        cfg = dict_to_config({"min_trades": "25"})
        assert cfg.min_trades == 25

    def test_max_drawdown_threshold(self):
        cfg = dict_to_config({"max_drawdown_threshold": "0.20"})
        assert cfg.max_drawdown_threshold == pytest.approx(0.20)

    def test_n_workers(self):
        cfg = dict_to_config({"n_workers": "4"})
        assert cfg.n_workers == 4

    def test_wf_train_bars(self):
        cfg = dict_to_config({"wf_train_bars": "500"})
        assert cfg.wf_train_bars == 500

    def test_wf_test_bars(self):
        cfg = dict_to_config({"wf_test_bars": "100"})
        assert cfg.wf_test_bars == 100

    def test_mc_simulations(self):
        cfg = dict_to_config({"mc_simulations": "1000"})
        assert cfg.mc_simulations == 1000

    def test_robustness_steps(self):
        cfg = dict_to_config({"robustness_steps": "2"})
        assert cfg.robustness_steps == 2

    def test_run_walk_forward(self):
        cfg = dict_to_config({"run_walk_forward": True})
        assert cfg.run_walk_forward is True

    def test_run_monte_carlo(self):
        cfg = dict_to_config({"run_monte_carlo": False})
        assert cfg.run_monte_carlo is False

    def test_run_robustness(self):
        cfg = dict_to_config({"run_robustness": "on"})
        assert cfg.run_robustness is True

    def test_fast_mode(self):
        cfg = dict_to_config({"fast_mode": "on"})
        assert cfg.fast_mode is True

    def test_old_wrong_name_slippage_ignored(self):
        """Old key 'slippage' (without _pct) must NOT set slippage_pct."""
        default_cfg = dict_to_config({})
        cfg = dict_to_config({"slippage": "0.999"})
        assert cfg.slippage_pct == default_cfg.slippage_pct

    def test_old_wrong_name_workers_ignored(self):
        """Old key 'workers' must NOT set n_workers."""
        cfg_default = dict_to_config({})
        cfg = dict_to_config({"workers": "99"})
        assert cfg.n_workers == cfg_default.n_workers

    def test_old_wrong_name_train_bars_ignored(self):
        """Old key 'train_bars' must NOT set wf_train_bars."""
        default_cfg = dict_to_config({})
        cfg = dict_to_config({"train_bars": "9999"})
        assert cfg.wf_train_bars == default_cfg.wf_train_bars

    def test_old_wrong_name_test_bars_ignored(self):
        default_cfg = dict_to_config({})
        cfg = dict_to_config({"test_bars": "9999"})
        assert cfg.wf_test_bars == default_cfg.wf_test_bars

    def test_old_wrong_name_n_simulations_ignored(self):
        default_cfg = dict_to_config({})
        cfg = dict_to_config({"n_simulations": "9999"})
        assert cfg.mc_simulations == default_cfg.mc_simulations

    def test_old_wrong_name_neighbor_steps_ignored(self):
        default_cfg = dict_to_config({})
        cfg = dict_to_config({"neighbor_steps": "9999"})
        assert cfg.robustness_steps == default_cfg.robustness_steps


class TestStrategyFilter:
    """Strategy selection field must survive round-trip through dict_to_config."""

    def test_strategies_empty_by_default(self):
        cfg = dict_to_config({})
        assert cfg.strategies == []

    def test_strategies_list_preserved(self):
        cfg = dict_to_config({"strategies": ["EMACrossover", "RSIStrategy"]})
        assert cfg.strategies == ["EMACrossover", "RSIStrategy"]

    def test_strategies_empty_list(self):
        cfg = dict_to_config({"strategies": []})
        assert cfg.strategies == []

    def test_strategies_single_item(self):
        cfg = dict_to_config({"strategies": ["EMACrossover"]})
        assert cfg.strategies == ["EMACrossover"]
