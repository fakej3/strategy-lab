import { Outlet, Navigate } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useEffect, useState } from 'react'
import { authApi } from '../../api/auth'

export function AppLayout() {
  const [state, setState] = useState<'checking' | 'authed' | 'unauthed'>('checking')

  useEffect(() => {
    authApi.me()
      .then(() => setState('authed'))
      .catch(() => setState('unauthed'))
  }, [])

  if (state === 'unauthed') return <Navigate to="/login" replace />
  if (state === 'checking') {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <span className="inline-block w-5 h-5 border border-muted/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex h-full bg-bg overflow-hidden">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-y-auto scrollbar-thin">
        <Outlet />
      </main>
    </div>
  )
}
