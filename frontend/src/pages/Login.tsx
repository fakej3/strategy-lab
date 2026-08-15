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

  const inputClass = "bg-bg border border-border rounded-md px-3 py-2 text-[12px] text-text placeholder:text-muted2 focus:outline-none focus:border-accent transition-colors w-full"

  return (
    <div className="flex h-full items-center justify-center bg-bg">
      <div className="w-full max-w-[340px]">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3 mb-7">
          <div className="w-10 h-10 rounded-lg bg-accent flex items-center justify-center shadow-sm">
            <CandlestickChart size={20} className="text-white" strokeWidth={2.5} />
          </div>
          <div className="text-center">
            <div className="text-[16px] font-bold text-text tracking-tight">EdgeLab</div>
            <div className="text-[11px] text-muted">Research Terminal</div>
          </div>
        </div>

        {/* Card */}
        <div className="bg-surface border border-border rounded-lg p-6 shadow-sm">
          <h1 className="text-[13px] font-semibold text-text mb-5">Sign in to your workspace</h1>

          {error && (
            <div className="mb-4 px-3 py-2 bg-red/10 border border-red/20 rounded-md text-red text-[11px]">
              {error}
            </div>
          )}

          <form onSubmit={submit} className="flex flex-col gap-3.5">
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                required
                placeholder="admin"
                className={inputClass}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                placeholder="••••••••"
                className={inputClass}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-1 bg-accent text-white font-semibold text-[12px] px-4 py-2 rounded-md hover:bg-accent-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="text-center text-[10px] text-muted2 mt-4">
          Default: admin / admin
        </p>
      </div>
    </div>
  )
}
