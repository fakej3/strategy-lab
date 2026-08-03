# Strategy Research Lab — Architecture

## Overview

The Strategy Research Lab is a modular, multi-layer Python system for automated
strategy research and backtesting. It is designed to be extended by a **Trading
Bot** that imports exclusively through the `lab/` facade layer.

---

## System Diagram

```
┌─────────────────────────────────────────────────────┐
│                   Entry Points                       │
│   run.py  research.py  scheduler.py  serve.py        │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│                    server/                           │
│         FastAPI web API + WebSocket + auth           │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│                 automation/                          │
│        8-step automated research pipeline            │
└──┬───────────────────────────────────────────────┬──┘
   │                                               │
   ▼                                               ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
│  jobs/   │  │research/ │  │  data/   │  │  reports/    │
│backtest  │  │ metrics  │  │ fetcher  │  │  html/dash   │
│walk-fwd  │  │optimizer │  │  store   │  │              │
│montecarlo│  │integrity │  │  api     │  └──────────────┘
│optimise  │  │ regime   │  └──────────┘
└──┬───────┘  └──────────┘
   │
   ▼
┌──────────────────────────────────────────────────────┐
│                   portfolio/                         │
│     PortfolioEngine — capital-aware execution        │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│                    engine/                           │
│  BacktestExecutor — bar-by-bar simulation engine     │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│                  pipeline/                           │
│   TradingView CSV parser, metrics, quality gate      │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                  research_db/                        │
│         SQLite storage — sessions, results           │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                    shared/                           │
│  errors · logging · config                           │
│  (no internal Lab dependencies)                      │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                     lab/  ◄── Trading Bot entry      │
│  MarketData · ResearchLab · Portfolio · Validation   │
│  Reports · Automation                                │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                     bot/  (placeholder)              │
│  Interfaces: ExecutionEngine · OrderManager          │
│  PositionManager · ExchangeAdapter · RiskEngine      │
│  NotificationEngine · StrategyRuntime · Monitoring   │
└──────────────────────────────────────────────────────┘
```

---

## Module Responsibilities

| Package | Responsibility |
|---|---|
| `engine/` | Stateless bar-by-bar backtest executor. Signal at T fills at T+1 open. SL/TP handled intrabar. No capital awareness. |
| `portfolio/` | Wraps the engine with position sizing (FIXED_UNITS, PCT_OF_EQUITY, FIXED_DOLLAR, FRACTIONAL). Builds equity/balance/drawdown curves. |
| `pipeline/` | Parses TradingView CSV exports. Computes basic performance metrics. Applies quality gate rules. |
| `research/` | Institutional-grade analytics: CAGR, Sharpe, Sortino, Calmar, walk-forward, optimisation, regime analysis, confidence scoring, stress tests, overfitting detection. |
| `data/` | Market data layer. Fetches OHLCV from Binance and Yahoo Finance. Caches to Parquet. Lazy integrity audit on load. |
| `jobs/` | Async-ready job wrappers for backtest, walk-forward, Monte Carlo, and optimisation. Used by the pipeline runner. |
| `automation/` | Orchestrates the full 8-step research pipeline. Manages multiprocessing, storage, and progress notifications. |
| `research_db/` | SQLite persistence. 50+ column schema for strategy results, sessions, monitoring events, and job queue. |
| `reports/` | HTML report generation. Standalone dashboard (FastAPI, no auth). |
| `server/` | Full authenticated web server. Jinja2 templates, session cookies, REST API, WebSocket progress streaming. |
| `strategies/` | Bundled strategy implementations. Currently: `EMACrossover`. |
| `verify/` | Verification framework. 20 golden scenarios, 9 financial invariants, 1000 property-based tests. |
| `shared/` | Zero-dependency utilities: error hierarchy, centralised logging, config re-exports. |
| `lab/` | Public facade layer — the ONLY interface for the Trading Bot and external consumers. |
| `bot/` | Trading Bot placeholder. Abstract interfaces only. No implementation. |

---

## Dependency Graph

**Dependency layers (bottom = no internal deps):**

```
Layer 0  pipeline, engine, research_db
Layer 1  strategies, data, portfolio         ← depends on Layer 0
Layer 2  research                            ← depends on Layers 0-1
Layer 3  jobs, automation, reports, verify   ← depends on Layers 0-2
Layer 4  server                              ← depends on Layers 0-3
Layer 5  entry points (run.py, research.py, scheduler.py, serve.py)
```

**shared/** sits outside all layers — it has no internal Lab dependencies.

**lab/** sits above all layers — it wraps them but is not depended upon by any of them.

**bot/** depends only on `lab/` and `shared/`.

### Forbidden dependency directions

| What | Must NOT import from |
|---|---|
| `engine/` | `portfolio`, `research`, `jobs`, `automation`, `lab`, `bot` |
| `pipeline/` | `engine`, `portfolio`, `research`, `jobs`, `automation`, `lab`, `bot` |
| `portfolio/` | `research`, `jobs`, `automation`, `lab`, `bot` |
| `research/` | `jobs`, `automation`, `server`, `lab`, `bot` |
| `jobs/` | `automation`, `server`, `lab`, `bot` |
| `automation/` | `server`, `lab`, `bot` |
| `shared/` | Any internal Lab package |
| `lab/` | (may import all internal packages — it is the facade) |
| `bot/` | Any internal Lab package — must use `lab/` and `shared/` only |

---

## Public API (`lab/` facade)

The Trading Bot (and any future external consumer) imports **only** from `lab/`
and `shared/`. Never from internal packages.

### `lab.MarketData`

```python
from lab import MarketData
from datetime import date

md = MarketData()

# Fetch OHLCV bars
bars = md.get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 12, 31))

# Run integrity audit
report = md.audit(bars)           # returns DataIntegrityReport
print(report.integrity_score)     # 0 – 100
```

### `lab.Validation`

```python
from lab import Validation
from shared.errors import IntegrityError

v = Validation()

try:
    v.assert_integrity(bars, min_score=80.0)   # raises on hard failures or low score
except IntegrityError as e:
    print(e)

warnings = v.validate(bars)    # returns list[ValidationWarning]
```

### `lab.ResearchLab`

```python
from lab import ResearchLab
from datetime import date

result = ResearchLab().evaluate(
    bars=bars,
    strategy_class=MyStrategy,
    params={"fast": 10, "slow": 50},
    symbol="BTCUSDT",
    interval="1h",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    starting_capital=100_000.0,
    fee_rate=0.001,
    slippage_pct=0.0005,
)
# result is a dict: metrics, gate_result, portfolio_result, …

metrics = ResearchLab().calculate_metrics(
    equity_curve=result["portfolio_result"].equity_curve,
    trades=result["portfolio_result"].trades,
    bars_per_year=8760,
)
```

### `lab.Portfolio`

```python
from lab import Portfolio
from shared.config import PortfolioConfig, SizingMode

cfg = PortfolioConfig(
    starting_capital=100_000.0,
    sizing_mode=SizingMode.PCT_OF_EQUITY,
    equity_fraction=0.10,
)
result = Portfolio(cfg).run(bars, strategy_instance, engine_config)
```

### `lab.Reports`

```python
from lab import Reports

report = Reports().generate(
    portfolio_result=result,
    bars=bars,
    strategy_name="EMACrossover",
    symbol="BTCUSDT",
    bars_per_year=8760,
)
print(report.to_json())
```

### `lab.Automation`

```python
from lab import Automation
from shared.config import PipelineConfig

cfg = PipelineConfig(
    symbols=["BTCUSDT"],
    intervals=["1h"],
    starting_capital=100_000.0,
)
run = Automation(cfg).run_pipeline()
print(f"{run.n_passed} strategies passed the quality gate")
```

---

## Error Hierarchy (`shared.errors`)

All exceptions raised by any Lab subsystem descend from `LabError`:

```
LabError
├── DataError          — market data fetch / store failures
├── IntegrityError     — OHLCV data quality failures (audit_bars)
├── ResearchError      — backtesting / analysis failures
├── ValidationError    — parameter or input validation failures
├── AutomationError    — pipeline orchestration failures
└── ConfigurationError — bad or missing configuration values
```

Catch all Lab errors with a single `except LabError` clause.

---

## Configuration (`shared.config`)

All configs are importable from `shared.config`:

| Class | Purpose | Canonical source |
|---|---|---|
| `EngineConfig` | Backtest engine parameters (fees, slippage, SL/TP) | `engine.models` |
| `PortfolioConfig` | Capital, sizing mode, equity fraction | `portfolio.models` |
| `SizingMode` | Enum: FIXED_UNITS / PCT_OF_EQUITY / FIXED_DOLLAR / FRACTIONAL | `portfolio.models` |
| `PipelineConfig` | Automated pipeline settings (symbols, dates, workers, …) | `automation.pipeline` |
| `DataConfig` | Data layer settings (cache dir, provider, timeout) | `shared.config` |
| `ResearchConfig` | Research layer settings (bars_per_year, benchmark) | `shared.config` |
| `ServerConfig` | Web server settings (host, port, debug) | `shared.config` |
| `TradingBotConfig` | Bot settings (exchange, dry_run, risk_per_trade) | `shared.config` |

---

## Architecture Rules

1. **The Trading Bot imports only `lab/` and `shared/`.** Never `engine`, `portfolio`, `research`, `jobs`, `automation`, `data`, `pipeline`, or `server`.

2. **Internal packages never import from `lab/`.** This would create circular dependencies.

3. **`shared/` has no internal Lab dependencies.** It may only use the Python standard library.

4. **Dependency always flows downward** (toward lower-numbered layers). A module in layer N may import from layers 0…N-1, never from N+1 or above.

5. **All public exceptions are `LabError` subclasses** (from `shared.errors`). Facade methods catch internal exceptions and re-raise as the appropriate `LabError` subclass so callers never see internal exception types.

6. **Financial calculations are never changed without a regression test.** Any fix to metrics, gate scoring, or fill logic requires a deterministic test that would have caught the bug.

7. **New strategies go in `strategies/`.** They must subclass `engine.StrategyBase` and implement `generate_signals(bars) -> pd.Series`.

8. **Research engine internals are not redesigned.** The existing package structure (engine → portfolio → research → jobs → automation) is stable. Architecture changes must not alter financial calculations or behaviour.

---

## Trading Bot Integration Guide

The Trading Bot is not yet implemented. This section defines the integration
contract for when development begins.

### Step 1: Import from `lab/` only

```python
# bot/trading_bot.py
from lab import MarketData, ResearchLab, Portfolio, Validation
from shared.config import TradingBotConfig, PortfolioConfig
from shared.errors import LabError
from shared.logging import get_logger

log = get_logger(__name__)
```

### Step 2: Implement the abstract interfaces

The interfaces in `bot/interfaces.py` define the contract:

- `ExecutionEngine` — submit/cancel/query orders on the exchange
- `OrderManager` — lifecycle tracking of open orders
- `PositionManager` — open position tracking and closing
- `ExchangeAdapter` — normalize exchange REST/WebSocket APIs; start with `PaperTrading`
- `RiskEngine` — pre-trade risk checks
- `NotificationEngine` — alerts to Slack/Telegram/email
- `StrategyRuntime` — bar-by-bar live event loop
- `Monitoring` — health check and metrics endpoint

### Step 3: Strategy selection

Strategies validated by the Research Lab (available via `ResearchLab.evaluate()`)
can be promoted to live trading via `StrategyRuntime`. The bot receives the same
`StrategyBase` subclass, the same `EngineConfig`, and the same `PortfolioConfig`
— the live fills replace the simulated fills from the backtest engine.

### Step 4: Paper trading first

Always start with `PaperTrading` (implements `ExchangeAdapter` against a local
order book simulation). Promote to `LiveTrading` only after paper results match
backtest expectations within tolerance.

---

## Regression Test Coverage

Architecture regression tests live in `tests/test_architecture.py`.
They verify on every CI run:

- `lab/` exports all six facade classes with correct method signatures
- `shared/` exports the full error hierarchy and logging helpers
- The error hierarchy is correct (all errors descend from `LabError`)
- `shared.config` re-exports all canonical config classes
- `bot/` is importable and defines all abstract interfaces
- Facades delegate to internal packages (smoke test with real bars)
- No internal package imports from `lab/` (circular dependency prevention)
