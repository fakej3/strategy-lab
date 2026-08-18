"""Regression tests: HTML report generator must escape all user-supplied values.

XSS injection vector: strategy_class, symbol, interval, params, and regime keys
all come from the database (originally from user-supplied API inputs) and must
be HTML-escaped before being embedded in the report HTML.

The script-injection string "</script><script>alert(1)</script>" is used because
it exploits the </script> tag break-out and is the canonical browser-validated
XSS vector for this context.
"""
from __future__ import annotations

import json

import pytest

from reports.html import generate_html_report
from research_db.models import StrategyResult


XSS = '<script>alert(1)</script>'
BREAK = '</script><script>alert(1)</script>'


def _result(**kwargs) -> StrategyResult:
    defaults = dict(
        session_id     = "sess-xss-test",
        strategy_class = "SafeStrategy",
        strategy_name  = "SafeStrategy",
        params         = '{"fast": 10}',
        symbol         = "BTCUSDT",
        interval       = "1h",
        start_date     = "2024-01-01",
        end_date       = "2024-12-31",
        gate_decision  = "PROMISING",
        sharpe_ratio   = 1.5,
        cagr           = 0.20,
        max_drawdown_pct = 0.10,
        win_rate       = 0.55,
        profit_factor  = 1.8,
        total_trades   = 50,
    )
    defaults.update(kwargs)
    return StrategyResult(**defaults)


def _html(**kwargs) -> str:
    r = _result(**kwargs)
    return generate_html_report(
        session_id  = r.session_id,
        symbol      = r.symbol,
        interval    = r.interval,
        start_date  = r.start_date,
        end_date    = r.end_date,
        results     = [r],
        n_tested    = 1,
        elapsed_secs= 1.0,
    )


class TestStrategyTableEscaping:
    def test_strategy_class_escaped(self):
        html = _html(strategy_class=XSS)
        assert XSS not in html

    def test_symbol_escaped(self):
        html = _html(symbol=f"BTC{XSS}USDT")
        assert XSS not in html

    def test_params_escaped(self):
        html = _html(params=f'{{"key": "{XSS}"}}')
        assert XSS not in html


class TestMcSectionEscaping:
    def test_strategy_class_in_mc_section(self):
        html = _html(
            strategy_class  = XSS,
            mc_median_return= 0.10,
            mc_pct5_return  = 0.01,
            mc_pct95_return = 0.20,
            mc_prob_positive= 0.65,
        )
        assert XSS not in html


class TestDegradationSectionEscaping:
    def test_strategy_class_in_degradation_section(self):
        deg = json.dumps({
            "degradation_score": 80.0,
            "first_half_sharpe": 1.5,
            "second_half_sharpe": 1.2,
        })
        html = _html(
            strategy_class   = XSS,
            degradation_json = deg,
            degradation_score= 80.0,
        )
        assert XSS not in html


class TestRobustnessSectionEscaping:
    def test_strategy_class_in_robustness_section(self):
        rob = json.dumps({
            "robustness_score": 70.0,
            "stability_score":  65.0,
            "n_neighbors":      4,
            "n_profitable":     3,
            "focal_sharpe":     1.5,
        })
        html = _html(
            strategy_class  = XSS,
            robustness_json = rob,
            robustness_score= 70.0,
        )
        assert XSS not in html


class TestBootstrapSectionEscaping:
    def test_strategy_class_in_bootstrap_heading(self):
        bs = json.dumps({
            "n_simulations": 500,
            "n_trades":      50,
            "total_return": {"pct_5": 0.01, "pct_50": 0.10, "pct_95": 0.25},
        })
        html = _html(
            strategy_class = XSS,
            bootstrap_json = bs,
        )
        assert XSS not in html


class TestRegimeSectionEscaping:
    def test_regime_key_escaped(self):
        regime_data = json.dumps({
            "regime_stats": {
                XSS: {"n_trades": 5, "win_rate": 0.6, "profit_factor": 1.5,
                      "avg_pnl": 10.0, "total_pnl": 50.0},
            }
        })
        html = _html(
            strategy_class = "SafeStrategy",
            regime_json    = regime_data,
        )
        assert XSS not in html

    def test_strategy_class_in_regime_heading(self):
        regime_data = json.dumps({
            "regime_stats": {
                "bull": {"n_trades": 5, "win_rate": 0.6, "profit_factor": 1.5,
                         "avg_pnl": 10.0, "total_pnl": 50.0},
            }
        })
        html = _html(
            strategy_class = XSS,
            regime_json    = regime_data,
        )
        assert XSS not in html


class TestWfSectionEscaping:
    def test_strategy_class_in_wf_section(self):
        html = _html(
            strategy_class      = XSS,
            walk_forward_return = 0.15,
        )
        assert XSS not in html


class TestStatsGridEscaping:
    def test_symbol_in_stats_tile(self):
        html = _html(symbol=f"BTC{XSS}USDT")
        assert XSS not in html

    def test_interval_in_stats_tile(self):
        html = _html(interval=f"1h{XSS}")
        assert XSS not in html


class TestChartSectionScriptInjection:
    def test_script_breakout_in_chart_data(self):
        """Label strings containing </script> must not break out of the script block."""
        html = _html(
            strategy_class  = f"Strat{BREAK}",
            gate_decision   = "PROMISING",
            equity_curve_json = json.dumps([100.0, 110.0, 105.0]),
        )
        # The raw break-out string must not appear literally in the HTML
        assert BREAK not in html

    def test_angle_brackets_unicode_escaped_in_script(self):
        """< and > inside strategy labels embedded in <script> must be \\u003c/\\u003e."""
        html = _html(
            strategy_class    = "Strat<Compare>",
            gate_decision     = "PROMISING",
            equity_curve_json = json.dumps([100.0, 110.0]),
        )
        assert "eqCanvas" in html, "Expected chart section for PROMISING + equity data"
        script_start = html.find("const datasets =")
        script_end   = html.find("</script>", script_start)
        assert script_start != -1, "Could not find 'const datasets =' in HTML"
        assert script_end   != -1, "Could not find closing </script> after datasets"
        data_block = html[script_start:script_end]
        # Literal angle brackets from the strategy name must not appear in the JS block
        assert "<Compare>" not in data_block, (
            "Literal angle brackets found in script data block — "
            "JSON must be escaped with .replace('<','\\u003c').replace('>','\\u003e')"
        )
        # The unicode-escaped form must be present in the data block
        assert "\\u003c" in data_block, (
            "Expected '\\u003c' encoding for '<' in script data block"
        )

    def test_xss_payload_in_equity_label_escaped(self):
        """Strategy name containing XSS embedded in chart label must be escaped."""
        html = _html(
            strategy_class    = XSS,
            gate_decision     = "PROMISING",
            equity_curve_json = json.dumps([100.0, 110.0, 120.0]),
        )
        assert XSS not in html
