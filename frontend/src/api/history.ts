import { api } from './client'
import type { Session } from '../types'

export const historyApi = {
  list: (limit = 50) => api.get<Session[]>(`/api/history?limit=${limit}`),
}
