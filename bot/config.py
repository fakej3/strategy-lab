"""Bot configuration — all settings for the paper trading bot."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FeedConfig:
    """Live market data feed settings."""

    symbols: list[str]   = field(default_factory=lambda: ["BTCUSDT"])
    intervals: list[str] = field(default_factory=lambda: ["1h"])

    # Binance public endpoints — no API key required
    ws_base_url: str   = "wss://stream.binance.com:9443/stream"
    rest_base_url: str = "https://api.binance.com/api/v3"

    backfill_bars: int       = 300    # candles to fetch via REST on (re)connect
    reconnect_delay_s: float = 5.0    # initial back-off before reconnecting
    max_reconnect_delay_s: float = 60.0
    heartbeat_interval_s: int = 30
    ping_timeout_s: int       = 20    # websockets ping timeout
    ws_open_timeout_s: int    = 30    # websockets connection open timeout
    rest_timeout_s: int       = 30    # aiohttp REST request timeout


@dataclass
class RiskConfig:
    """Risk limits applied before every simulated order."""

    max_risk_pct: float           = 0.01     # 1% of equity at risk per trade
    max_position_size_usd: float  = 20.0     # max notional per position
    max_daily_loss_usd: float     = 1.25     # 5% of 25 USDT starting capital
    max_drawdown_pct: float       = 0.20     # halt if drawdown exceeds 20%
    max_leverage: float           = 1.0      # no leverage
    max_open_positions: int       = 1
    trading_cooldown_s: float     = 0.0      # minimum seconds between trades
    max_daily_trades: int         = 50


@dataclass
class BotConfig:
    """Master configuration for the paper trading bot."""

    # ── Capital ──────────────────────────────────────────────────────────────
    paper_capital: float  = 25.0
    fee_rate: float       = 0.001      # Binance taker fee (0.1%)
    slippage_pct: float   = 0.0005     # 0.05% simulated slippage per side
    maker_fee_rate: float = 0.0009     # cheaper for limit orders

    # ── Strategy ─────────────────────────────────────────────────────────────
    strategy_name: str               = "EMACrossover"
    strategy_params: dict[str, Any]  = field(
        default_factory=lambda: {"fast": 20, "slow": 50}
    )

    # ── Sub-configs ───────────────────────────────────────────────────────────
    feed: FeedConfig = field(default_factory=FeedConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    # ── Sizing ───────────────────────────────────────────────────────────────
    equity_fraction: float = 0.10   # 10% of current equity per trade
    qty_precision: int     = 5      # decimal places for order quantity (BTC = 5)

    # ── Signal ───────────────────────────────────────────────────────────────
    min_signal_bars: int = 60       # minimum buffer length before signalling
    buffer_size: int     = 500      # rolling candle buffer per (symbol, interval)

    # ── Persistence ──────────────────────────────────────────────────────────
    db_path: str      = "bot.db"
    reports_dir: str  = "reports/bot"
    log_path: str     = "logs/bot.log"

    # ── Scheduling ───────────────────────────────────────────────────────────
    daily_report_hour_utc: int  = 0     # midnight UTC
    monitor_interval_s: int     = 60    # snapshot interval
    snapshot_interval_s: int    = 300   # equity snapshot interval

    # ── Recovery ─────────────────────────────────────────────────────────────
    recover_on_restart: bool = True

    def __post_init__(self) -> None:
        if self.paper_capital <= 0:
            raise ValueError(f"paper_capital must be > 0, got {self.paper_capital!r}")
        if not (0.0 < self.equity_fraction <= 1.0):
            raise ValueError(f"equity_fraction must be in (0, 1], got {self.equity_fraction!r}")
        if self.fee_rate < 0:
            raise ValueError(f"fee_rate must be >= 0")
        # Create output directories
        Path(self.reports_dir).mkdir(parents=True, exist_ok=True)
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Build a config from environment variables (useful for Docker/systemd)."""
        capital = float(os.environ.get("BOT_CAPITAL", "25"))
        return cls(
            paper_capital    = capital,
            fee_rate         = float(os.environ.get("BOT_FEE_RATE", "0.001")),
            slippage_pct     = float(os.environ.get("BOT_SLIPPAGE", "0.0005")),
            strategy_name    = os.environ.get("BOT_STRATEGY", "EMACrossover"),
            db_path          = os.environ.get("BOT_DB", "bot.db"),
            reports_dir      = os.environ.get("BOT_REPORTS_DIR", "reports/bot"),
            log_path         = os.environ.get("BOT_LOG_PATH", "logs/bot.log"),
            feed             = FeedConfig(
                symbols           = os.environ.get("BOT_SYMBOLS", "BTCUSDT").split(","),
                intervals         = os.environ.get("BOT_INTERVALS", "1h").split(","),
                ws_open_timeout_s = int(os.environ.get("BOT_WS_OPEN_TIMEOUT", "30")),
                rest_timeout_s    = int(os.environ.get("BOT_REST_TIMEOUT", "30")),
            ),
            min_signal_bars  = int(os.environ.get("BOT_MIN_SIGNAL_BARS", "60")),
            buffer_size      = int(os.environ.get("BOT_BUFFER_SIZE", "500")),
            qty_precision    = int(os.environ.get("BOT_QTY_PRECISION", "5")),
            risk             = RiskConfig(
                max_risk_pct          = float(os.environ.get("BOT_MAX_RISK_PCT", "0.01")),
                max_position_size_usd = float(os.environ.get("BOT_MAX_POSITION_USD", "20")),
                max_daily_loss_usd    = float(
                    os.environ.get("BOT_MAX_DAILY_LOSS", str(capital * 0.05))
                ),
            ),
        )
