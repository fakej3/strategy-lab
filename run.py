#!/usr/bin/env python3
"""Strategy Research Lab — interactive backtest runner.

Usage:
    python run.py

No arguments, no editing, no imports required.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime
from pathlib import Path


# ── Strategy registry ─────────────────────────────────────────────────────────
# Add new strategies here — no other file needs to change.
#
# Each entry is a tuple:
#   (display_name, strategy_class, params)
#
# Each param is a tuple:
#   (name, type, default, description)
#   type must be int | float | str

def _build_registry() -> list[tuple]:
    from strategies import EMACrossover
    return [
        (
            "EMA Crossover",
            EMACrossover,
            [
                ("fast", int,   20,  "Fast EMA period (bars)"),
                ("slow", int,   50,  "Slow EMA period (bars)"),
            ],
        ),
    ]


# ── Bars-per-year table ───────────────────────────────────────────────────────

_BARS_PER_YEAR: dict[str, int] = {
    "1m":  525_600,
    "3m":  175_200,
    "5m":  105_120,
    "15m":  35_040,
    "30m":  17_520,
    "1h":    8_760,
    "2h":    4_380,
    "4h":    2_190,
    "6h":    1_460,
    "8h":    1_095,
    "12h":     730,
    "1d":      365,
    "3d":      121,
    "1w":       52,
}

_VALID_INTERVALS = set(_BARS_PER_YEAR)

# ── Terminal constants ────────────────────────────────────────────────────────

_W    = 62
_SEP  = "=" * _W
_DASH = "─" * _W


# ── Low-level prompt helpers ──────────────────────────────────────────────────

def _ask(label: str, default: str | None = None, hint: str = "") -> str:
    """Read a line from stdin, returning default on empty input."""
    suffix = f" [{default}]" if default is not None else ""
    if hint:
        suffix += f"  ({hint})"
    try:
        val = input(f"  {label}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        raise
    return val if val else (default or "")


def _ask_int(label: str, default: int, *, lo: int = 1, hi: int | None = None) -> int:
    while True:
        raw = _ask(label, str(default))
        try:
            n = int(raw)
        except ValueError:
            print("    ✗  Enter a whole number.")
            continue
        if n < lo:
            print(f"    ✗  Must be ≥ {lo}.")
            continue
        if hi is not None and n > hi:
            print(f"    ✗  Must be ≤ {hi}.")
            continue
        return n


def _ask_float(label: str, default: float, *, lo: float | None = None, hi: float | None = None) -> float:
    while True:
        raw = _ask(label, str(default))
        try:
            v = float(raw)
        except ValueError:
            print("    ✗  Enter a number.")
            continue
        if lo is not None and v < lo:
            print(f"    ✗  Must be ≥ {lo}.")
            continue
        if hi is not None and v > hi:
            print(f"    ✗  Must be ≤ {hi}.")
            continue
        return v


def _ask_date(label: str, default: str) -> date:
    while True:
        raw = _ask(label, default, hint="YYYY-MM-DD")
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print("    ✗  Use YYYY-MM-DD format.")


def _ask_optional_pct(label: str) -> float | None:
    """Ask for an optional percentage (e.g. '2' = 2%) and return as a fraction or None."""
    while True:
        raw = _ask(label, hint="e.g. 2 for 2%, blank = disable").strip()
        if not raw:
            return None
        try:
            v = float(raw)
        except ValueError:
            print("    ✗  Enter a number or leave blank.")
            continue
        if v <= 0 or v >= 100:
            print("    ✗  Enter a value between 0 and 100.")
            continue
        return v / 100.0


# ── Interactive menu ──────────────────────────────────────────────────────────

def collect_inputs() -> dict:
    """Walk the user through all backtest settings and return a config dict."""
    print()
    print(_SEP)
    print("  Strategy Research Lab — Interactive Backtest Runner")
    print(_SEP)

    # ── Instrument ────────────────────────────────────────────────────────────
    print()
    print("  ── Instrument ──────────────────────────────────────────────")
    symbol = _ask("Symbol", "BTCUSDT", hint="e.g. ETHUSDT, BNBUSDT").upper() or "BTCUSDT"

    valid_list = "  " + ", ".join(_BARS_PER_YEAR)
    while True:
        tf = _ask("Timeframe", "1h").lower().strip()
        if tf in _VALID_INTERVALS:
            break
        print(f"    ✗  Unsupported timeframe.  Valid values:\n{valid_list}")

    # ── Date range ────────────────────────────────────────────────────────────
    print()
    print("  ── Date range ──────────────────────────────────────────────")
    year = datetime.now().year
    start_date = _ask_date("Start date", f"{year - 1}-01-01")
    end_date   = _ask_date("End date",   f"{year - 1}-12-31")
    while end_date < start_date:
        print("    ✗  End date must be on or after start date.")
        end_date = _ask_date("End date", f"{year - 1}-12-31")

    # ── Capital ───────────────────────────────────────────────────────────────
    print()
    print("  ── Capital ─────────────────────────────────────────────────")
    starting_capital = _ask_float("Starting capital ($)", 100_000.0, lo=1.0)

    # ── Strategy ──────────────────────────────────────────────────────────────
    print()
    print("  ── Strategy ────────────────────────────────────────────────")
    registry = _build_registry()
    for i, (name, _, _) in enumerate(registry, 1):
        print(f"    {i}.  {name}")
    strat_idx = _ask_int("  Strategy #", 1, lo=1, hi=len(registry))
    strat_name, strat_cls, param_defs = registry[strat_idx - 1]

    params: dict = {}
    if param_defs:
        print()
        print(f"  ── Parameters: {strat_name} ─────────────────────────────")
        for pname, ptype, pdefault, pdesc in param_defs:
            if ptype is int:
                params[pname] = _ask_int(f"  {pname}  ({pdesc})", pdefault)
            elif ptype is float:
                params[pname] = _ask_float(f"  {pname}  ({pdesc})", pdefault)
            else:
                params[pname] = _ask(f"  {pname}  ({pdesc})", str(pdefault))

    # ── Engine settings ───────────────────────────────────────────────────────
    print()
    print("  ── Engine settings (Enter = use default) ───────────────────")
    fee_rate        = _ask_float("  Fee rate",     0.001,  lo=0.0, hi=0.1)
    slippage_pct    = _ask_float("  Slippage",     0.0005, lo=0.0, hi=0.1)
    stop_loss_pct   = _ask_optional_pct("  Stop loss %")
    take_profit_pct = _ask_optional_pct("  Take profit %")

    return {
        "symbol"          : symbol,
        "interval"        : tf,
        "start_date"      : start_date,
        "end_date"        : end_date,
        "starting_capital": starting_capital,
        "strat_name"      : strat_name,
        "strat_cls"       : strat_cls,
        "params"          : params,
        "fee_rate"        : fee_rate,
        "slippage_pct"    : slippage_pct,
        "stop_loss_pct"   : stop_loss_pct,
        "take_profit_pct" : take_profit_pct,
        "bars_per_year"   : _BARS_PER_YEAR[tf],
    }


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(cfg: dict):
    """Execute the full backtest pipeline.  Returns a result tuple or None on error."""

    from data import get_bars
    from engine.models import EngineConfig
    from pipeline.gate import evaluate_gate
    from pipeline.metrics import calculate_metrics as _gate_metrics
    from portfolio.engine import PortfolioEngine
    from portfolio.models import PortfolioConfig
    from research.metrics import calculate_research_metrics
    from research.report import build_report
    from research.validation import validate_bars_extended

    bpy = cfg["bars_per_year"]

    print()
    print(_SEP)
    print("  Backtest Pipeline")
    print(_SEP)
    print()

    # ── Step 1: fetch / cache ─────────────────────────────────────────────────
    _step("1/6", "Fetching market data")
    try:
        bars = get_bars(cfg["symbol"], cfg["interval"], cfg["start_date"], cfg["end_date"])
    except Exception as exc:
        _fail(str(exc))
        return None

    if bars.empty:
        _fail(
            f"No data returned for {cfg['symbol']} {cfg['interval']} "
            f"{cfg['start_date']} – {cfg['end_date']}.\n"
            "       Check the symbol name and date range, then try again."
        )
        return None
    _ok(f"{len(bars):,} bars  "
        f"({bars.index[0].strftime('%Y-%m-%d')} → {bars.index[-1].strftime('%Y-%m-%d')})")

    # ── Step 2: validate ──────────────────────────────────────────────────────
    _step("2/6", "Validating bars")
    try:
        val_warnings = validate_bars_extended(bars)
    except ValueError as exc:
        _fail(str(exc))
        return None

    if val_warnings:
        _warn(f"{len(val_warnings)} issue(s) found")
        for w in val_warnings:
            print(f"         {w}")
    else:
        _ok("clean")

    # ── Step 3: backtest ──────────────────────────────────────────────────────
    _step("3/6", "Running backtest")
    try:
        strategy = cfg["strat_cls"](**cfg["params"])
    except Exception as exc:
        _fail(f"Invalid strategy parameters: {exc}")
        return None

    try:
        eng_cfg = EngineConfig(
            fee_rate        = cfg["fee_rate"],
            slippage_pct    = cfg["slippage_pct"],
            stop_loss_pct   = cfg["stop_loss_pct"],
            take_profit_pct = cfg["take_profit_pct"],
        )
    except ValueError as exc:
        _fail(f"Invalid engine config: {exc}")
        return None

    port_cfg = PortfolioConfig(starting_capital=cfg["starting_capital"])
    result   = PortfolioEngine(port_cfg).run(bars, strategy, eng_cfg)
    _ok(f"{len(result.trades)} trade(s)")

    # ── Step 4: institutional metrics ─────────────────────────────────────────
    _step("4/6", "Computing metrics")
    research_metrics = calculate_research_metrics(
        equity_curve  = result.equity_curve,
        trades        = result.trades,
        bars_per_year = bpy,
    )
    report = build_report(
        result,
        strategy_name = cfg["strat_name"],
        symbol        = cfg["symbol"],
        bars_per_year = bpy,
    )
    _ok()

    # ── Step 5: quality gate ──────────────────────────────────────────────────
    _step("5/6", "Quality Gate")
    gate = None
    if result.trades:
        try:
            pipeline_metrics = _gate_metrics(result.trades, "$")
            gate = evaluate_gate(pipeline_metrics)
            _ok(gate.decision.value)
        except Exception as exc:
            _warn(f"skipped — {exc}")
    else:
        _warn("no trades — skipped")

    # ── Step 6: save reports ──────────────────────────────────────────────────
    _step("6/6", "Saving reports")
    try:
        json_path, md_path = save_reports(result, research_metrics, report, gate, cfg)
        _ok()
    except Exception as exc:
        _warn(f"could not save — {exc}")
        json_path = md_path = None

    return result, research_metrics, report, gate, json_path, md_path


# ── Terminal summary ──────────────────────────────────────────────────────────

def print_summary(result, research_metrics, report, gate, cfg, json_path, md_path):
    m = research_metrics
    r = result

    def kv(label: str, value: str) -> None:
        print(f"  {label:<26} {value}")

    def _f(v: float) -> str:
        if math.isnan(v):
            return "N/A"
        if math.isinf(v):
            return "∞" if v > 0 else "-∞"
        return f"{v:.4f}"

    def _pct(v: float) -> str:
        if math.isnan(v):
            return "N/A"
        return f"{v:>+14.2%}"

    # ── Config recap ──────────────────────────────────────────────────────────
    print()
    print(_DASH)
    print("  CONFIGURATION")
    print(_DASH)
    kv("Symbol",          cfg["symbol"])
    kv("Timeframe",       cfg["interval"])
    kv("Period",          f"{cfg['start_date']}  →  {cfg['end_date']}")
    kv("Strategy",        cfg["strat_name"])
    for k, v in cfg["params"].items():
        kv(f"  {k}", str(v))
    kv("Starting capital", f"${cfg['starting_capital']:,.2f}")
    kv("Fee rate",         f"{cfg['fee_rate'] * 100:.3f}%")
    kv("Slippage",         f"{cfg['slippage_pct'] * 100:.4f}%")
    if cfg.get("stop_loss_pct"):
        kv("Stop loss",    f"{cfg['stop_loss_pct'] * 100:.1f}%")
    if cfg.get("take_profit_pct"):
        kv("Take profit",  f"{cfg['take_profit_pct'] * 100:.1f}%")

    # ── Portfolio results ─────────────────────────────────────────────────────
    print()
    print(_DASH)
    print("  PORTFOLIO RESULTS")
    print(_DASH)
    kv("Starting capital", f"${r.starting_capital:>15,.2f}")
    kv("Ending equity",    f"${r.ending_equity:>15,.2f}")
    kv("Net profit",       f"${r.net_profit:>+15,.2f}")
    kv("Total return",     f"{r.total_return:>+14.2%}")
    kv("Max drawdown",     f"{r.max_drawdown_pct:>14.2%}")
    kv("Peak equity",      f"${r.peak_equity:>15,.2f}")
    kv("Market exposure",  f"{r.exposure_pct:>14.2%}")
    kv("Total trades",     f"{len(r.trades):>14,}")

    # ── Institutional metrics ─────────────────────────────────────────────────
    print()
    print(_DASH)
    print("  INSTITUTIONAL METRICS")
    print(_DASH)
    kv("CAGR",                f"{_pct(m.cagr):>14}")
    kv("Sharpe ratio",        f"{_f(m.sharpe_ratio):>14}")
    kv("Sortino ratio",       f"{_f(m.sortino_ratio):>14}")
    kv("Calmar ratio",        f"{_f(m.calmar_ratio):>14}")
    kv("Win rate",            f"{m.win_rate:>14.2%}")
    kv("Profit factor",       f"{_f(m.profit_factor):>14}")
    kv("Payoff ratio",        f"{_f(m.payoff_ratio):>14}")
    kv("Kelly fraction",      f"{m.kelly_fraction:>14.4f}")
    kv("Recovery factor",     f"{_f(m.recovery_factor):>14}")
    kv("Avg trade PnL",       f"${m.avg_trade_pnl:>15,.2f}")
    kv("Avg holding (bars)",  f"{m.avg_holding_period:>14.1f}")
    kv("Downside vol (ann)",  f"{m.downside_volatility:>14.4f}")
    kv("Skewness",            f"{m.skewness:>14.4f}")
    kv("Kurtosis",            f"{m.kurtosis:>14.4f}")

    # ── Quality gate ──────────────────────────────────────────────────────────
    print()
    print(_DASH)
    print("  QUALITY GATE")
    print(_DASH)

    if gate is None:
        print()
        print("  – No trades were generated; Quality Gate skipped.")
        print("  Adjust strategy parameters or extend the date range.")
    else:
        _BADGE = {
            "PROMISING":         "🟢  PROMISING",
            "NEEDS IMPROVEMENT": "🟡  NEEDS IMPROVEMENT",
            "REJECT":            "🔴  REJECT",
        }
        badge = _BADGE.get(gate.decision.value, gate.decision.value)
        print()
        print(f"  Decision  :  {badge}")
        print(f"  Score     :  {gate.overall_score:.0f} / 100")
        print()
        _SYM = {"PASS": "✓", "WARNING": "⚠", "FAIL": "✗"}
        for cat in gate.categories:
            print(f"  [{cat.name}]  {cat.score:.0f}/100")
            for rule in cat.rules:
                sym = _SYM.get(rule.status.value, "?")
                print(f"    {sym} {rule.name}: {rule.detail}")
        if gate.primary_failure:
            print()
            print(f"  Primary issue:  {gate.primary_failure}")
            print()
            _wrap("  Next experiment:", gate.next_experiment)
            print()
            _wrap("  Goal:", gate.expected_goal)

    # ── Reports ───────────────────────────────────────────────────────────────
    print()
    print(_DASH)
    print("  REPORTS SAVED")
    print(_DASH)
    if json_path:
        print(f"  JSON : {json_path}")
    if md_path:
        print(f"  MD   : {md_path}")
    if not json_path and not md_path:
        print("  (none saved — see error above)")

    print()
    print(_SEP)
    print()


def _wrap(prefix: str, text: str, width: int = _W) -> None:
    indent = " " * len(prefix)
    words  = text.split()
    line   = prefix + " "
    for word in words:
        if len(line) + len(word) + 1 > width and line.strip() not in (prefix.strip(), ""):
            print(line.rstrip())
            line = indent + word + " "
        else:
            line += word + " "
    if line.strip():
        print(line.rstrip())


# ── Report writers ────────────────────────────────────────────────────────────

def save_reports(result, research_metrics, report, gate, cfg) -> tuple[Path, Path]:
    """Write JSON and Markdown reports to reports/ and return their paths."""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    slug = (
        f"{cfg['symbol']}_{cfg['interval']}"
        f"_{cfg['start_date']}_{cfg['end_date']}"
        f"_{cfg['strat_name'].replace(' ', '_')}"
    )
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = reports_dir / f"{slug}_{ts}"

    json_path = Path(str(base) + ".json")
    md_path   = Path(str(base) + ".md")

    json_path.write_text(_build_json(result, research_metrics, report, gate, cfg), encoding="utf-8")
    md_path.write_text(  _build_md(result, research_metrics, report, gate, cfg),   encoding="utf-8")

    return json_path, md_path


def _build_json(result, research_metrics, report, gate, cfg) -> str:
    def _sf(v):
        if isinstance(v, float) and math.isinf(v):
            return "Infinity"
        return v

    gate_dict = None
    if gate is not None:
        gate_dict = {
            "decision"        : gate.decision.value,
            "overall_score"   : gate.overall_score,
            "categories"      : [
                {
                    "name"  : c.name,
                    "score" : c.score,
                    "weight": c.weight,
                    "rules" : [
                        {
                            "name"  : r.name,
                            "status": r.status.value,
                            "score" : r.score,
                            "detail": r.detail,
                        }
                        for r in c.rules
                    ],
                }
                for c in gate.categories
            ],
            "primary_failure" : gate.primary_failure,
            "next_experiment" : gate.next_experiment,
            "expected_goal"   : gate.expected_goal,
        }

    doc = {
        "generated_at": datetime.now().isoformat(),
        "config": {
            "symbol"          : cfg["symbol"],
            "interval"        : cfg["interval"],
            "start_date"      : str(cfg["start_date"]),
            "end_date"        : str(cfg["end_date"]),
            "starting_capital": cfg["starting_capital"],
            "strategy"        : cfg["strat_name"],
            "params"          : cfg["params"],
            "fee_rate"        : cfg["fee_rate"],
            "slippage_pct"    : cfg["slippage_pct"],
            "stop_loss_pct"   : cfg.get("stop_loss_pct"),
            "take_profit_pct" : cfg.get("take_profit_pct"),
            "bars_per_year"   : cfg["bars_per_year"],
        },
        "portfolio": {
            "starting_capital": result.starting_capital,
            "ending_equity"   : result.ending_equity,
            "net_profit"      : result.net_profit,
            "total_return"    : result.total_return,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_abs": result.max_drawdown_abs,
            "peak_equity"     : result.peak_equity,
            "exposure_pct"    : result.exposure_pct,
            "total_trades"    : len(result.trades),
        },
        "metrics": {k: _sf(v) for k, v in report.to_dict()["metrics"].items()},
        "quality_gate": gate_dict,
    }

    return json.dumps(doc, indent=2, default=str)


def _build_md(result, research_metrics, report, gate, cfg) -> str:
    m = research_metrics
    r = result

    def pct(v: float) -> str:
        return f"{v:.2%}"

    def f2(v: float) -> str:
        return "∞" if math.isinf(v) else f"{v:.4f}"

    lines: list[str] = []
    a = lines.append

    a(f"# Backtest Report: {cfg['strat_name']} on {cfg['symbol']}")
    a("")
    a(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    a("")

    # Configuration
    a("## Configuration")
    a("")
    a("| Setting | Value |")
    a("|---|---|")
    a(f"| Symbol | `{cfg['symbol']}` |")
    a(f"| Timeframe | `{cfg['interval']}` |")
    a(f"| Period | {cfg['start_date']} → {cfg['end_date']} |")
    a(f"| Strategy | {cfg['strat_name']} |")
    for k, v in cfg["params"].items():
        a(f"| {k} | {v} |")
    a(f"| Starting capital | ${cfg['starting_capital']:,.2f} |")
    a(f"| Fee rate | {cfg['fee_rate'] * 100:.3f}% |")
    a(f"| Slippage | {cfg['slippage_pct'] * 100:.4f}% |")
    if cfg.get("stop_loss_pct"):
        a(f"| Stop loss | {cfg['stop_loss_pct'] * 100:.1f}% |")
    if cfg.get("take_profit_pct"):
        a(f"| Take profit | {cfg['take_profit_pct'] * 100:.1f}% |")
    a("")

    # Portfolio
    a("## Portfolio Results")
    a("")
    a("| Metric | Value |")
    a("|---|---|")
    a(f"| Starting capital | ${r.starting_capital:,.2f} |")
    a(f"| Ending equity | ${r.ending_equity:,.2f} |")
    a(f"| Net profit | ${r.net_profit:+,.2f} |")
    a(f"| Total return | {pct(r.total_return)} |")
    a(f"| Max drawdown | {pct(r.max_drawdown_pct)} |")
    a(f"| Peak equity | ${r.peak_equity:,.2f} |")
    a(f"| Market exposure | {pct(r.exposure_pct)} |")
    a(f"| Total trades | {len(r.trades)} |")
    a("")

    # Institutional metrics
    a("## Institutional Metrics")
    a("")
    a("| Metric | Value |")
    a("|---|---|")
    a(f"| CAGR | {m.cagr:+.2%} |")
    a(f"| Sharpe ratio | {f2(m.sharpe_ratio)} |")
    a(f"| Sortino ratio | {f2(m.sortino_ratio)} |")
    a(f"| Calmar ratio | {f2(m.calmar_ratio)} |")
    a(f"| Win rate | {m.win_rate:.2%} |")
    a(f"| Profit factor | {f2(m.profit_factor)} |")
    a(f"| Payoff ratio | {f2(m.payoff_ratio)} |")
    a(f"| Kelly fraction | {m.kelly_fraction:.4f} |")
    a(f"| Recovery factor | {f2(m.recovery_factor)} |")
    a(f"| Avg trade PnL | ${m.avg_trade_pnl:,.2f} |")
    a(f"| Avg holding (bars) | {m.avg_holding_period:.1f} |")
    a(f"| Downside volatility (ann.) | {m.downside_volatility:.4f} |")
    a(f"| Skewness | {m.skewness:.4f} |")
    a(f"| Kurtosis | {m.kurtosis:.4f} |")
    a("")

    # Quality gate
    if gate is not None:
        _BADGE = {
            "PROMISING":         "🟢 PROMISING",
            "NEEDS IMPROVEMENT": "🟡 NEEDS IMPROVEMENT",
            "REJECT":            "🔴 REJECT",
        }
        badge = _BADGE.get(gate.decision.value, gate.decision.value)
        a(f"## Quality Gate: {badge}")
        a("")
        a(f"**Overall score:** {gate.overall_score:.0f} / 100")
        a("")
        _SYM_MD = {"PASS": "✓", "WARNING": "⚠", "FAIL": "✗"}
        for cat in gate.categories:
            a(f"### {cat.name} — {cat.score:.0f}/100")
            a("")
            for rule in cat.rules:
                sym = _SYM_MD.get(rule.status.value, "?")
                a(f"- {sym} **{rule.name}:** {rule.detail}")
            a("")
        if gate.primary_failure:
            a(f"**Primary issue:** `{gate.primary_failure}`")
            a("")
            a("**Next experiment:**")
            a("")
            a(gate.next_experiment)
            a("")
            a("**Expected goal:**")
            a("")
            a(gate.expected_goal)
            a("")
    else:
        a("## Quality Gate")
        a("")
        a("*No trades were generated; Quality Gate skipped.*")
        a("")

    return "\n".join(lines)


# ── Progress indicators ───────────────────────────────────────────────────────

def _step(n: str, label: str) -> None:
    print(f"  [{n}] {label} …", end="", flush=True)

def _ok(detail: str = "") -> None:
    msg = f" ✓  {detail}" if detail else " ✓"
    print(msg)

def _warn(detail: str = "") -> None:
    msg = f" ⚠  {detail}" if detail else " ⚠"
    print(msg)

def _fail(detail: str = "") -> None:
    msg = f" ✗  {detail}" if detail else " ✗"
    print(msg)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    try:
        cfg = collect_inputs()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.\n")
        return 0

    pipeline_output = run_pipeline(cfg)
    if pipeline_output is None:
        return 1

    result, research_metrics, report, gate, json_path, md_path = pipeline_output

    print_summary(result, research_metrics, report, gate, cfg, json_path, md_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
