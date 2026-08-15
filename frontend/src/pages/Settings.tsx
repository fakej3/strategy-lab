import { useEffect, useState } from 'react'
import { settingsApi } from '../api/settings'
import { LoadingState } from '../components/ui/EmptyState'
import type { Settings as SettingsType } from '../types'

export function Settings() {
  const [s, setS]       = useState<SettingsType | null>(null)
  const [loading, setL] = useState(true)

  useEffect(() => {
    settingsApi.get().then(setS).finally(() => setL(false))
  }, [])

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Settings</h1>
      <p className="text-[12px] text-muted mb-5">Server configuration and environment</p>

      {loading && <LoadingState />}
      {!loading && s && (
        <>
          {s.using_default_creds && (
            <div className="px-3 py-2.5 mb-5 bg-amber/10 border border-amber/30 rounded-md text-amber text-[11px]">
              Default credentials in use. Generate a password hash and set{' '}
              <code className="font-mono">EDGELAB_PASSWORD_HASH</code>.
            </div>
          )}

          <h2 className="text-[13px] font-semibold text-text mb-3">Paths</h2>
          <div className="bg-surface border border-border rounded-md overflow-hidden mb-5">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">Setting</th>
                  <th className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">Value</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['Database',        s.db_path],
                  ['Reports Dir',     s.reports_dir],
                  ['Market Data Dir', s.data_dir],
                  ['Log File',        s.log_path],
                ].map(([k, v]) => (
                  <tr key={k} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 text-muted">{k}</td>
                    <td className="px-3 py-2 font-mono text-text">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 className="text-[13px] font-semibold text-text mb-3">Environment Variables</h2>
          {Object.keys(s.env_vars).length === 0 ? (
            <p className="text-muted text-[12px]">No EDGELAB_ environment variables are set.</p>
          ) : (
            <div className="bg-surface border border-border rounded-md overflow-hidden">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">Variable</th>
                    <th className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(s.env_vars).map(([k, v]) => (
                    <tr key={k} className="border-b border-border last:border-0">
                      <td className="px-3 py-2 font-mono">{k}</td>
                      <td className="px-3 py-2 font-mono text-muted">
                        {/HASH|SECRET|PASSWORD/i.test(k) ? '*** (hidden)' : v}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 className="text-[13px] font-semibold text-text mt-6 mb-3">Set a Password</h2>
          <div className="bg-surface border border-border rounded-md p-4 text-[11px] text-muted space-y-2">
            <p><strong className="text-text">1. Generate a hash:</strong></p>
            <pre className="bg-bg rounded p-2 text-[10px] overflow-x-auto font-mono">
              {'python -c "from server.auth import hash_password; print(hash_password(\'yourpassword\'))"'}
            </pre>
            <p><strong className="text-text">2. Set before starting:</strong></p>
            <pre className="bg-bg rounded p-2 text-[10px] overflow-x-auto font-mono">
              {'export EDGELAB_USERNAME=admin\nexport EDGELAB_PASSWORD_HASH=<hash>\npython serve.py'}
            </pre>
          </div>
        </>
      )}
    </div>
  )
}
