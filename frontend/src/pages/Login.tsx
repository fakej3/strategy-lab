import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { CandlestickChart } from 'lucide-react'

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
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-2 mb-8">
          <div className="w-10 h-10 rounded-lg bg-accent/15 flex items-center justify-center">
            <CandlestickChart size={20} className="text-accent" />
          </div>
          <div className="text-center">
            <div className="text-[15px] font-bold text-text">EdgeLab</div>
            <div className="text-[11px] text-muted">Research Engine</div>
          </div>
        </div>

        <form onSubmit={submit} className="bg-surface border border-border rounded-lg p-6 flex flex-col gap-4">
          <h1 className="text-[13px] font-semibold text-text">Sign in</h1>

          {error && (
            <div className="px-3 py-2 bg-red/10 border border-red/30 rounded text-red text-[11px]">
              {error}
            </div>
          )}

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
              required
              className="bg-bg border border-border rounded px-3 py-2 text-[12px] text-text placeholder:text-muted2 focus:outline-none focus:border-accent"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="bg-bg border border-border rounded px-3 py-2 text-[12px] text-text placeholder:text-muted2 focus:outline-none focus:border-accent"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="mt-1 bg-accent text-bg font-semibold text-[12px] px-4 py-2 rounded-md hover:bg-accent-dim transition-colors disabled:opacity-50"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-center text-[10px] text-muted mt-4">
          Default credentials: admin / admin
        </p>
      </div>
    </div>
  )
}
