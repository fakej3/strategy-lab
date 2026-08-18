import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'

export function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const navigate = useNavigate()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await authApi.login(username, password)
      navigate('/', { replace: true })
    } catch {
      setError('Invalid credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-bg relative overflow-hidden">
      {/* Ambient grid */}
      <div className="absolute inset-0 opacity-[0.035]" aria-hidden>
        <svg width="100%" height="100%">
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#D4940C" strokeWidth="0.5"/>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
      </div>

      {/* Ambient glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] rounded-full bg-accent/5 blur-3xl pointer-events-none" aria-hidden />

      <div className="relative w-full max-w-sm px-4 animate-fade-in">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-accent/10 border border-accent/20 mb-5 shadow-lg shadow-accent/5">
            <span className="text-accent font-bold text-3xl font-mono leading-none tracking-tight">E</span>
          </div>
          <h1 className="text-2xl font-bold text-text tracking-tight">EdgeLab</h1>
          <p className="text-sm text-muted mt-1.5">Research smarter. Trade with evidence.</p>
        </div>

        {/* Card */}
        <div className="bg-surface border border-border rounded-2xl p-6 shadow-xl shadow-black/20">
          {error && (
            <div className="mb-4 flex items-center gap-2 px-3 py-2.5 border border-red/20 bg-red/8 rounded-lg text-red text-sm">
              <span className="w-1 h-1 rounded-full bg-red inline-block shrink-0" />
              {error}
            </div>
          )}

          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="field-label" htmlFor="username">Username</label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                placeholder="admin"
                className="field-input"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="field-label" htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                placeholder="••••••••"
                className="field-input"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-1 flex items-center justify-center gap-2 bg-accent text-bg font-bold text-sm px-4 py-3 rounded-xl hover:bg-accent-dim active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading && (
                <span className="inline-block w-4 h-4 border-2 border-bg/30 border-t-bg rounded-full animate-spin" />
              )}
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-muted2 mt-5">Default · admin / admin</p>
      </div>
    </div>
  )
}
