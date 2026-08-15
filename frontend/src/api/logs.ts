import { api } from './client'

export const logsApi = {
  get: (lines = 200) => api.get<{ lines: string[] }>(`/api/logs?lines=${lines}`),
}
