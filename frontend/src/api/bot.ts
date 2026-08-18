import { api } from './client'
import type { BotStatus, Candle, AvailableStrategy } from '../types'

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
}
