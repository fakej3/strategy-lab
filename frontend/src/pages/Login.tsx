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
      setError('Invalid username or password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-bg">
      <div className="w-full max-w-sm px-4">
        {/* Wordmark */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-accent/10 border border-accent/20 mb-5">
            <span className="text-accent font-bold text-2xl font-mono leading-none">E</span>
          </div>
          <h1 className="text-xl font-bold text-text tracking-tight">EdgeLab</h1>
          <p className="text-sm text-muted mt-1">Research &amp; Paper Trading</p>
        </div>

        {/* Card */}
        <div className="bg-surface border border-border rounded-xl p-6">
          {error && (
            <div className="mb-4 px-3 py-2.5 border border-red/20 bg-red/8 rounded-lg text-red text-sm">
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
              className="mt-1 flex items-center justify-center gap-2 bg-accent text-bg font-semibold text-sm px-4 py-2.5 rounded-md hover:bg-accent-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading && (
                <span className="inline-block w-4 h-4 border-2 border-bg border-t-transparent rounded-full animate-spin" />
              )}
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-muted2 mt-4">Default credentials: admin / admin</p>
      </div>
    </div>
  )
}
