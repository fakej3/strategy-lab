import { api } from './client'
import type { StrategyResult } from '../types'

export const strategiesApi = {
  list: (metric = 'sharpe_ratio', limit = 100) =>
    api.get<StrategyResult[]>(`/api/strategies?metric=${metric}&limit=${limit}`),
}
