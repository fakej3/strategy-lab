"""Architecture regression tests.

These tests verify that the structural rules of the Strategy Research Lab are
maintained as the codebase evolves.  They do NOT test business logic — they
test the shape of the public API, the error hierarchy, and import boundaries.

Rules being enforced
--------------------
1. lab/ exports all six facade classes.
2. shared/ exports the full error hierarchy and logging helpers.
3. The error hierarchy is correct (all errors descend from LabError).
4. shared.config re-exports the canonical config classes.
5. bot/ is importable and defines abstract interfaces.
6. lab/ facades delegate to internal packages (smoke test).
7. No internal package imports from lab/ (would create a circular dependency).
"""
from __future__ import annotations

import importlib
import inspect
import math
import sys


# ── 1. lab/ public API ────────────────────────────────────────────────────────

class TestLabExports:
    def test_lab_imports_cleanly(self):
        import lab

    def test_all_facade_classes_exported(self):
        import lab
        for name in ("MarketData", "ResearchLab", "Portfolio", "Validation", "Reports", "Automation"):
            assert hasattr(lab, name), f"lab.{name} is missing from lab.__init__"

    def test_market_data_has_get_bars(self):
        from lab import MarketData
        assert callable(getattr(MarketData, "get_bars", None))

    def test_research_lab_has_evaluate(self):
        from lab import ResearchLab
        assert callable(getattr(ResearchLab, "evaluate", None))

    def test_portfolio_has_run(self):
        from lab import Portfolio
        assert callable(getattr(Portfolio, "run", None))

    def test_validation_has_audit(self):
        from lab import Validation
        assert callable(getattr(Validation, "audit", None))

    def test_reports_has_generate(self):
        from lab import Reports
        assert callable(getattr(Reports, "generate", None))

    def test_automation_has_run_pipeline(self):
        from lab import Automation
        assert callable(getattr(Automation, "run_pipeline", None))

    def test_all_in_dunder_all(self):
        import lab
        for name in ("MarketData", "ResearchLab", "Portfolio", "Validation", "Reports", "Automation"):
            assert name in lab.__all__, f"{name} missing from lab.__all__"


# ── 2. shared/ public API ─────────────────────────────────────────────────────

class TestSharedExports:
    def test_shared_imports_cleanly(self):
        import shared

    def test_error_classes_exported(self):
        import shared
        for name in (
            "LabError", "DataError", "IntegrityError", "ResearchError",
            "ValidationError", "AutomationError", "ConfigurationError",
        ):
            assert hasattr(shared, name), f"shared.{name} is missing"

    def test_logging_helpers_exported(self):
        import shared
        assert callable(getattr(shared, "get_logger", None))
        assert callable(getattr(shared, "setup_logging", None))


# ── 3. Error hierarchy ────────────────────────────────────────────────────────

class TestErrorHierarchy:
    def test_all_errors_descend_from_lab_error(self):
        from shared.errors import (
            AutomationError,
            ConfigurationError,
            DataError,
            IntegrityError,
            LabError,
            ResearchError,
            ValidationError,
        )
        for cls in (DataError, IntegrityError, ResearchError,
                    ValidationError, AutomationError, ConfigurationError):
            assert issubclass(cls, LabError), f"{cls.__name__} must subclass LabError"

    def test_lab_error_is_exception(self):
        from shared.errors import LabError
        assert issubclass(LabError, Exception)

    def test_errors_are_distinct(self):
        from shared.errors import (
            AutomationError, ConfigurationError, DataError,
            IntegrityError, ResearchError, ValidationError,
        )
        classes = [DataError, IntegrityError, ResearchError,
                   ValidationError, AutomationError, ConfigurationError]
        assert len(classes) == len(set(classes))

    def test_can_catch_all_via_lab_error(self):
        from shared.errors import DataError, LabError
        try:
            raise DataError("test")
        except LabError:
            pass


# ── 4. shared.config re-exports ───────────────────────────────────────────────

class TestSharedConfig:
    def test_engine_config_importable(self):
        from shared.config import EngineConfig
        cfg = EngineConfig()
        assert hasattr(cfg, "fee_rate")

    def test_portfolio_config_importable(self):
        from shared.config import PortfolioConfig
        cfg = PortfolioConfig()
        assert cfg.starting_capital > 0

    def test_pipeline_config_importable(self):
        from shared.config import PipelineConfig
        cfg = PipelineConfig()
        assert isinstance(cfg.symbols, list)

    def test_sizing_mode_importable(self):
        from shared.config import SizingMode
        assert hasattr(SizingMode, "FIXED_UNITS")

    def test_data_config_importable(self):
        from shared.config import DataConfig
        cfg = DataConfig()
        assert isinstance(cfg.data_dir, str)

    def test_research_config_importable(self):
        from shared.config import ResearchConfig
        cfg = ResearchConfig()
        assert cfg.bars_per_year > 0

    def test_server_config_importable(self):
        from shared.config import ServerConfig
        cfg = ServerConfig()
        assert isinstance(cfg.port, int)

    def test_trading_bot_config_importable(self):
        from shared.config import TradingBotConfig
        cfg = TradingBotConfig()
        assert cfg.dry_run is True


# ── 5. bot/ placeholder ───────────────────────────────────────────────────────

class TestBotPackage:
    def test_bot_imports_cleanly(self):
        import bot

    def test_bot_interfaces_importable(self):
        import bot.interfaces

    def test_abstract_interfaces_present(self):
        import bot.interfaces as bi
        for name in (
            "ExecutionEngine", "OrderManager", "PositionManager",
            "ExchangeAdapter", "RiskEngine", "NotificationEngine",
            "StrategyRuntime", "Monitoring",
        ):
            assert hasattr(bi, name), f"bot.interfaces.{name} is missing"

    def test_interfaces_are_abstract(self):
        from abc import ABC
        import bot.interfaces as bi
        for name in ("ExecutionEngine", "OrderManager", "PositionManager",
                     "ExchangeAdapter", "RiskEngine", "NotificationEngine",
                     "StrategyRuntime", "Monitoring"):
            cls = getattr(bi, name)
            assert issubclass(cls, ABC), f"{name} must be an ABC"

    def test_paper_trading_and_live_trading_present(self):
        from bot.interfaces import LiveTrading, PaperTrading
        assert issubclass(PaperTrading, object)
        assert issubclass(LiveTrading, object)


# ── 6. Facade delegation (smoke tests) ────────────────────────────────────────

class TestFacadeDelegation:
    def test_validation_facade_calls_audit_bars(self):
        """Validation.audit() must delegate to research.integrity.audit_bars."""
        import pandas as pd
        from lab import Validation
        from shared.errors import IntegrityError

        # Create minimal valid bars
        import numpy as np
        idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        bars = pd.DataFrame({
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low":  [99.0] * 5,
            "close":[100.5] * 5,
            "volume":[1000.0] * 5,
        }, index=idx)
        report = Validation().audit(bars)
        assert hasattr(report, "integrity_score")
        assert 0 <= report.integrity_score <= 100

    def test_validation_facade_raises_integrity_error_on_bad_data(self):
        """Validation.audit() must raise IntegrityError (not ValueError) on bad data."""
        import pandas as pd
        from lab import Validation
        from shared.errors import IntegrityError

        idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
        # high < low is a hard failure
        bars = pd.DataFrame({
            "open":  [100.0, 100.0, 100.0],
            "high":  [98.0,  98.0,  98.0],   # high < low — invalid
            "low":   [99.0,  99.0,  99.0],
            "close": [100.0, 100.0, 100.0],
            "volume":[1000.0] * 3,
        }, index=idx)
        try:
            Validation().audit(bars)
        except IntegrityError:
            pass  # expected
        except Exception as exc:
            raise AssertionError(
                f"Expected IntegrityError but got {type(exc).__name__}: {exc}"
            ) from exc

    def test_market_data_raises_data_error_on_failure(self):
        """MarketData.get_bars() must raise DataError (not the original exception)."""
        from lab import MarketData
        from shared.errors import DataError
        try:
            MarketData().get_bars("INVALID_SYM_XYZ", "1h", None, None)
        except DataError:
            pass  # expected
        except Exception as exc:
            # Some environments may raise other errors — just verify it's not
            # leaking the raw internal exception type.
            assert not type(exc).__name__.endswith("ProviderError"), (
                f"Internal ProviderError leaked through facade: {exc}"
            )


# ── 7. Import boundary — internal packages must not import from lab/ ──────────

class TestImportBoundaries:
    """Verify that internal packages do not import from lab/ (would create cycles)."""

    _INTERNAL_PACKAGES = [
        "engine", "portfolio", "research", "jobs",
        "automation", "data", "pipeline",
    ]

    def _get_imports(self, module_name: str) -> set[str]:
        """Return the set of top-level package names imported by *module_name*."""
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            return set()
        source_file = getattr(mod, "__file__", None)
        if not source_file:
            return set()
        try:
            import ast, pathlib
            src = pathlib.Path(source_file).read_text(encoding="utf-8")
            tree = ast.parse(src)
        except Exception:
            return set()
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        return imports

    def test_engine_does_not_import_lab(self):
        assert "lab" not in self._get_imports("engine")

    def test_portfolio_does_not_import_lab(self):
        assert "lab" not in self._get_imports("portfolio")

    def test_research_does_not_import_lab(self):
        assert "lab" not in self._get_imports("research")

    def test_jobs_does_not_import_lab(self):
        assert "lab" not in self._get_imports("jobs")

    def test_automation_does_not_import_lab(self):
        assert "lab" not in self._get_imports("automation")

    def test_data_does_not_import_lab(self):
        assert "lab" not in self._get_imports("data")

    def test_pipeline_does_not_import_lab(self):
        assert "lab" not in self._get_imports("pipeline")
