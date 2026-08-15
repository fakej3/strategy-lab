import { api } from './client'
import type { Job } from '../types'

export const jobsApi = {
  list:    ()          => api.get<Job[]>('/api/jobs'),
  get:     (id: string) => api.get<Job>(`/api/research/status/${id}`),
  cancel:  (id: string) => api.post<{ cancelled: boolean }>(`/api/jobs/${id}/cancel`),
  restart: (id: string) => api.post<{ job_id: string }>(`/api/jobs/${id}/restart`),
  submit:  (body: Record<string, unknown>) => api.post<{ job_id: string }>('/api/research/run', body),
}
