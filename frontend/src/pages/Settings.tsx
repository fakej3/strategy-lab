import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
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
      <div className="page-header">
        <span className="page-title">Settings</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 max-w-2xl">
        {loading && <LoadingState />}
        {!loading && s && (
          <div className="flex flex-col gap-5">
            {s.using_default_creds && (
              <div className="flex items-start gap-3 px-4 py-3 border border-amber/25 bg-amber/5 rounded-lg text-amber text-sm">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <span>
                  Default credentials in use — set <code className="font-mono text-amber bg-amber/10 px-1 rounded">EDGELAB_PASSWORD_HASH</code> to secure your instance.
                </span>
              </div>
            )}

            <SettingsCard title="Paths">
              {[
                ['Database',        s.db_path],
                ['Reports Dir',     s.reports_dir],
                ['Market Data Dir', s.data_dir],
                ['Log File',        s.log_path],
              ].map(([k, v]) => (
                <SettingsRow key={k} label={k} value={v ?? '—'} mono />
              ))}
            </SettingsCard>

            {Object.keys(s.env_vars).length > 0 && (
              <SettingsCard title="Environment Variables">
                {Object.entries(s.env_vars).map(([k, v]) => (
                  <SettingsRow
                    key={k}
                    label={k}
                    value={/HASH|SECRET|PASSWORD/i.test(k) ? '*** (hidden)' : String(v ?? '—')}
                    mono
                    labelMono
                  />
                ))}
              </SettingsCard>
            )}

            <SettingsCard title="Set a Password">
              <div className="flex flex-col gap-3 text-sm text-muted">
                <div>
                  <div className="text-text font-medium mb-1.5">1. Generate a hash</div>
                  <pre className="bg-bg border border-border rounded-md p-3 text-xs overflow-x-auto font-mono text-muted2">
                    {'python -c "from server.auth import hash_password; print(hash_password(\'yourpassword\'))"'}
                  </pre>
                </div>
                <div>
                  <div className="text-text font-medium mb-1.5">2. Set before starting</div>
                  <pre className="bg-bg border border-border rounded-md p-3 text-xs overflow-x-auto font-mono text-muted2">
                    {'export EDGELAB_USERNAME=admin\nexport EDGELAB_PASSWORD_HASH=<hash>\npython serve.py'}
                  </pre>
                </div>
              </div>
            </SettingsCard>
          </div>
        )}
      </div>
    </div>
  )
}

function SettingsCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border">
        <span className="text-xs font-semibold text-muted">{title}</span>
      </div>
      <div className="divide-y divide-border">
        {children}
      </div>
    </div>
  )
}

function SettingsRow({ label, value, mono, labelMono }: {
  label: string; value: string; mono?: boolean; labelMono?: boolean
}) {
  return (
    <div className="flex items-baseline gap-4 px-4 py-2.5">
      <span className={`text-xs text-muted w-36 shrink-0 ${labelMono ? 'font-mono' : ''}`}>{label}</span>
      <span className={`text-sm text-text break-all ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}
