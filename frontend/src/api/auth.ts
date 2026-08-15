import { api } from './client'
import type { AuthUser } from '../types'

export const authApi = {
  me:     ()                               => api.get<AuthUser>('/api/auth/me'),
  login:  (username: string, password: string) =>
            api.post<{ ok: boolean }>('/api/auth/login', { username, password }),
  logout: ()                               => api.post<{ ok: boolean }>('/api/auth/logout'),
}
