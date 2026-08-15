import { api } from './client'
import type { Stats } from '../types'

export const statsApi = {
  get: () => api.get<Stats>('/api/stats'),
}
