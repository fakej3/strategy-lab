import { api } from './client'
import type { BotStatus, Candle, AvailableStrategy, StrategyInstance, SentinelPortfolio, ScanRequest } from '../types'

export const botApi = {
  status:       ()                               => api.get<BotStatus>('/api/bot/status'),
  candles:      (symbol: string, interval: string, limit = 500) =>
                  api.get<Candle[]>(`/api/bot/candles?symbol=${symbol}&interval=${interval}&limit=${limit}`),
  setActivePair:(symbol: string, interval: string) =>
                  api.post<{ ok: boolean }>('/api/bot/active-pair', { symbol, interval }),
  start:        (body: {
                  capital: number
                  symbols: string[]
                  intervals: string[]
                  strategy: string
                  recover: boolean
                  result_id?: number
                }) => api.post<{ started: boolean }>('/api/bot/start', body),
  stop:         ()                               => api.post<{ stopped: boolean }>('/api/bot/stop'),
  availableStrategies: ()                        => api.get<AvailableStrategy[]>('/api/available-strategies'),

  // SENTINEL multi-instance API
  instances:       ()                            => api.get<StrategyInstance[]>('/api/bot/instances'),
  portfolio:       ()                            => api.get<SentinelPortfolio>('/api/bot/portfolio'),
  startInstances:  (body: { specs: { symbol: string; interval: string; strategy_name: string; strategy_params: Record<string, unknown>; instance_id?: string }[]; capital: number }) =>
                     api.post<{ started: boolean }>('/api/bot/instances/start', body),
  stopInstance:    (id: string)                  => api.post<{ ok: boolean }>(`/api/bot/instances/${encodeURIComponent(id)}/stop`, {}),
  restartInstance: (id: string)                  => api.post<{ ok: boolean }>(`/api/bot/instances/${encodeURIComponent(id)}/restart`, {}),
  scan:            (body: ScanRequest)           => api.post<{ jobs: { job_id: string; symbol: string; interval: string; strategy: string }[] }>('/api/research/scan', body),
}
