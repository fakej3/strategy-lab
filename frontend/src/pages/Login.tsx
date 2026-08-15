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
      <div className="w-full max-w-[320px]">
        {/* Logo */}
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <CandlestickChart size={16} className="text-accent" strokeWidth={2} />
          <div>
            <div className="text-[14px] font-bold text-text leading-none">EdgeLab</div>
            <div className="text-[9px] text-muted uppercase tracking-widest leading-none mt-0.5">Research Terminal</div>
          </div>
        </div>

        {/* Form */}
        <div className="border border-border bg-surface p-5">
          {error && (
            <div className="mb-4 px-3 py-2 border border-red/25 bg-red/8 text-red text-[10px]">
              {error}
            </div>
          )}

          <form onSubmit={submit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="field-label">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                required
                placeholder="admin"
                className="field-input"
              />
            </div>

            <div className="flex flex-col gap-1">
              <label className="field-label">Password</label>
              <input
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
              className="mt-1 bg-accent text-bg font-semibold text-[11px] px-4 py-2 hover:bg-accent-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        </div>

        <p className="text-center text-[9px] text-muted2 mt-3">
          Default: admin / admin
        </p>
      </div>
    </div>
  )
}
