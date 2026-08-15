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
    <div className="flex flex-col h-full">
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Settings</span>
          <span className="ml-3 text-[10px] text-muted">Server configuration and environment</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-5 max-w-2xl">
        {loading && <LoadingState />}
        {!loading && s && (
          <>
            {s.using_default_creds && (
              <div className="px-3 py-2 mb-4 border border-amber/25 bg-amber/5 text-amber text-[10px]">
                Default credentials in use — set <code className="font-mono">EDGELAB_PASSWORD_HASH</code> to secure your instance.
              </div>
            )}

            <div className="mb-5">
              <div className="px-3 py-1.5 border-b border-border bg-surface">
                <span className="section-label">Paths</span>
              </div>
              <table className="w-full table-dense border border-border border-t-0">
                <tbody>
                  {[
                    ['Database',        s.db_path],
                    ['Reports Dir',     s.reports_dir],
                    ['Market Data Dir', s.data_dir],
                    ['Log File',        s.log_path],
                  ].map(([k, v]) => (
                    <tr key={k}>
                      <td className="text-muted w-36">{k}</td>
                      <td className="font-mono text-text">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {Object.keys(s.env_vars).length > 0 && (
              <div className="mb-5">
                <div className="px-3 py-1.5 border-b border-border bg-surface">
                  <span className="section-label">Environment Variables</span>
                </div>
                <table className="w-full table-dense border border-border border-t-0">
                  <tbody>
                    {Object.entries(s.env_vars).map(([k, v]) => (
                      <tr key={k}>
                        <td className="font-mono text-muted">{k}</td>
                        <td className="font-mono text-text">
                          {/HASH|SECRET|PASSWORD/i.test(k) ? '*** (hidden)' : v}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div>
              <div className="px-3 py-1.5 border-b border-border bg-surface">
                <span className="section-label">Set a Password</span>
              </div>
              <div className="p-3 border border-border border-t-0 text-[10px] text-muted space-y-2">
                <p><span className="text-text font-semibold">1. Generate a hash:</span></p>
                <pre className="bg-bg p-2 text-[9px] overflow-x-auto font-mono text-muted">
                  {'python -c "from server.auth import hash_password; print(hash_password(\'yourpassword\'))"'}
                </pre>
                <p><span className="text-text font-semibold">2. Set before starting:</span></p>
                <pre className="bg-bg p-2 text-[9px] overflow-x-auto font-mono text-muted">
                  {'export EDGELAB_USERNAME=admin\nexport EDGELAB_PASSWORD_HASH=<hash>\npython serve.py'}
                </pre>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
