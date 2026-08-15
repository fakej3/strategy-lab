import { api } from './client'
import type { Report } from '../types'

export const reportsApi = {
  list:   ()             => api.get<Report[]>('/api/reports'),
  delete: (name: string) => api.delete<{ deleted: string }>(`/api/reports/${name}`),
  viewUrl:    (name: string) => `/reports/view/${name}`,
  downloadUrl:(name: string) => `/reports/download/${name}`,
}
