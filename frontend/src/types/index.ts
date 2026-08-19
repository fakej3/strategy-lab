// ── Auth ──────────────────────────────────────────────────────────────────────
export interface AuthUser {
  username: string
}

// ── Stats ─────────────────────────────────────────────────────────────────────
export interface Stats {
  total?: number
  promising?: number
  needs_imp?: number
  rejected?: number
  best_sharpe?: number
  avg_sharpe?: number
}

// ── Jobs ──────────────────────────────────────────────────────────────────────
export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Job {
  job_id: string
  status: JobStatus
  started_at: string | null
  finished_at: string | null
  n_passed: number
  n_tested: number
  n_rejected?: number
  elapsed_secs: number | null
  progress_pct?: number
  current_stage?: string
  session_id?: string
  error?: string
  config?: Record<string, unknown>
}

// Job WebSocket message types
export type JobWsMessage =
  | { type: 'step';    n: number; label: string; pct: number }
  | { type: 'section'; label: string }
  | { type: 'ok';      message: string }
  | { type: 'info';    message: string }
  | { type: 'warn';    message: string }
  | { type: 'error';   message: string }
  | { type: 'done';    success: boolean; cancelled?: boolean; n_passed?: number; n_tested?: number; n_rejected?: number; elapsed_secs?: number; error?: string }
  | { type: 'ping' }

// ── Research ──────────────────────────────────────────────────────────────────
export interface AvailableStrategy {
  name: string
  param_space?: Record<string, unknown[]>
  params?: StrategyParam[]
}

export interface StrategyParam {
  name: string
  default: unknown
  type: string
}

// ── Reports ───────────────────────────────────────────────────────────────────
export interface Report {
  name: string
  size_kb: number
  modified: string
  symbol?: string
  interval?: string
  n_passed?: number
  sharpe?: number
}

// ── History ───────────────────────────────────────────────────────────────────
export interface Session {
  session_id: string
  started_at: string | null
  status: string
  n_strategies_run: number
  n_passed: number
  elapsed_secs: number | null
}

// ── Strategies ────────────────────────────────────────────────────────────────
export type GateDecision = 'PROMISING' | 'NEEDS IMPROVEMENT' | 'REJECT'

export interface StrategyResult {
  id: number
  strategy_class: string
  params: string
  symbol: string
  interval: string
  sharpe_ratio: number | null
  cagr: number | null
  max_drawdown_pct: number | null
  win_rate: number | null
  profit_factor: number | null
  total_trades: number
  gate_decision: GateDecision
}

// ── Bot ───────────────────────────────────────────────────────────────────────
export interface OpenPosition {
  symbol: string
  direction: 'long' | 'short'
  size: number
  entry_price: number
  notional: number
  opened_at: string
}

export interface Fill {
  id?: number
  symbol: string
  side: string
  fill_price: number
  size: number
  fee?: number
  timestamp?: number | string
  pnl?: number
}

export interface BotStatus {
  running: boolean
  status: 'idle' | 'running' | 'stopped' | 'failed'
  started_at: string | null
  stopped_at: string | null
  error: string
  symbols: string[]
  intervals: string[]
  interval: string
  strategy: string
  capital: number
  cash: number
  equity: number
  unrealized_pnl: number
  realized_pnl: number
  drawdown: number
  open_positions: OpenPosition[]
  recent_trades: Fill[]
  log_tail: string[]
  mark_prices: Record<string, number>
}

export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// Bot WebSocket message types
// All event-bus messages carry `ts` (ISO string) from the backend bridge.
export type BotWsMessage =
  | { type: 'candle';       symbol: string; interval: string; time: number; open: number; high: number; low: number; close: number; volume: number; ts?: string }
  | { type: 'tick';         symbol: string; interval: string; close: number; change: number; ts?: string }
  | { type: 'signal';       symbol: string; interval: string; signal: string; price?: number; strategy?: string; ts?: string }
  | { type: 'fill';         symbol: string; side: string; fill_price: number; size: number; fee?: number; timestamp?: string; pnl?: number; ts?: string }
  | { type: 'order';        symbol: string; side?: string; order_id?: string; ts?: string; [key: string]: unknown }
  | { type: 'position';     symbol: string; direction: string; size: number; entry_price: number; ts?: string }
  | { type: 'rejected';     symbol: string; reason: string; ts?: string }
  | { type: 'risk_rejected'; symbol: string; reason: string; ts?: string }
  | { type: 'error';        source?: string; message: string; ts?: string }
  | { type: 'log';          message: string; ts?: string }
  | { type: 'status';       [key: string]: unknown }
  | { type: 'disconnect';   symbol: string; reason: string; ts?: string }
  | { type: 'reconnect';    symbol: string; backfilled?: number; attempt?: number; ts?: string }
  | { type: 'ping' }

// ── Scheduler ─────────────────────────────────────────────────────────────────
export interface Schedule {
  id: string
  name: string
  frequency: 'daily' | 'weekly' | 'monthly'
  hour: number
  minute: number
  day_of_week?: number
  day_of_month?: number
  enabled: boolean
  last_run: string | null
  config: Record<string, unknown>
}

// ── Settings ──────────────────────────────────────────────────────────────────
export interface Settings {
  db_path: string
  reports_dir: string
  data_dir: string
  log_path: string
  env_vars: Record<string, string>
  using_default_creds: boolean
}

// ── Notifications ─────────────────────────────────────────────────────────────
export interface Notification {
  id: string
  message: string
  level: 'info' | 'warn' | 'error'
  timestamp: string
}
