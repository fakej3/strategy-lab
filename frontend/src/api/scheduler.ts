import { api } from './client'
import type { Schedule } from '../types'

export const schedulerApi = {
  list:   ()                         => api.get<Schedule[]>('/api/scheduler'),
  create: (body: Partial<Schedule>)  => api.post<Schedule>('/api/scheduler', body),
  delete: (id: string)               => api.delete<{ deleted: string }>(`/api/scheduler/${id}`),
  toggle: (id: string)               => api.post<Schedule>(`/api/scheduler/${id}/toggle`),
  runNow: (id: string)               => api.post<{ job_id: string }>(`/api/scheduler/${id}/run-now`),
}
