#!/usr/bin/env python3
"""
Strategy Research Lab — Milestone 1 Pipeline

Evaluates a TradingView Strategy Tester backtest and answers:
"Should I continue researching this strategy or reject it?"

Usage
─────
  python run.py trades.csv
  python run.py trades.csv --format json
  python run.py trades.csv --format markdown
  python run.py trades.csv --format all --output ./results/
  python run.py trades.csv --format json --output report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline import (
    ParseError,
    calculate_metrics,
    evaluate_gate,
    parse_tradingview_csv,
    render_json,
    render_markdown,
    render_terminal,
)


def _write(content: str, output: str | None) -> None:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Saved: {path}", file=sys.stderr)
    else:
        print(content)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Strategy Research Lab — evaluate a TradingView backtest CSV and "
            "produce a structured verdict."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "csv",
        help="Path to the TradingView Strategy Tester 'List of Trades' CSV export.",
    )
    parser.add_argument(
        "--format",
        choices=["terminal", "json", "markdown", "all"],
        default="terminal",
        help="Output format (default: terminal). Use 'all' to write all three formats.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Output file path. For --format all, provide a directory — "
            "report.txt, report.json, and report.md will be written there. "
            "Defaults to stdout."
        ),
    )

    args = parser.parse_args()

    # ── Parse ──────────────────────────────────────────────────────────────
    try:
        trades, profit_unit = parse_tradingview_csv(args.csv)
    except ParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1

    # ── Calculate metrics ──────────────────────────────────────────────────
    try:
        metrics = calculate_metrics(trades, profit_unit)
    except ParseError as e:
        print(f"Metrics error: {e}", file=sys.stderr)
        return 1

    # ── Evaluate quality gate ──────────────────────────────────────────────
    gate = evaluate_gate(metrics)

    # ── Render and output ──────────────────────────────────────────────────
    fmt = args.format

    if fmt == "terminal":
        _write(render_terminal(metrics, gate), args.output)

    elif fmt == "json":
        _write(json.dumps(render_json(metrics, gate), indent=2), args.output)

    elif fmt == "markdown":
        _write(render_markdown(metrics, gate), args.output)

    elif fmt == "all":
        base = Path(args.output) if args.output else Path(".")
        base.mkdir(parents=True, exist_ok=True)

        terminal_text = render_terminal(metrics, gate)
        print(terminal_text)  # always print terminal to stdout for 'all'

        (base / "report.txt").write_text(terminal_text, encoding="utf-8")
        (base / "report.json").write_text(
            json.dumps(render_json(metrics, gate), indent=2), encoding="utf-8"
        )
        (base / "report.md").write_text(render_markdown(metrics, gate), encoding="utf-8")

        print(f"\nAll formats saved to: {base.resolve()}/", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
