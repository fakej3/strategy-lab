import { useState } from 'react'
import { Modal } from '../../components/ui/Modal'
import { Button } from '../../components/ui/Button'
import { botApi } from '../../api/bot'

interface Props {
  onClose: () => void
  onStopped: () => void
}

export function StopModal({ onClose, onStopped }: Props) {
  const [loading, setL] = useState(false)
  const [err, setErr]   = useState('')

  async function confirm() {
    setErr('')
    setL(true)
    try {
      await botApi.stop()
      onStopped()
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex))
      setL(false)
    }
  }

  return (
    <Modal open title="Stop Bot" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <p className="text-[12px] text-muted">
          This will stop the paper-trading bot. Open positions will remain in the database
          and can be recovered on the next start if <strong className="text-text">Recover</strong> is enabled.
        </p>
        {err && (
          <div className="px-3 py-2 bg-red/10 border border-red/30 rounded text-red text-[11px]">{err}</div>
        )}
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={loading}>Cancel</Button>
          <Button variant="danger"    size="sm" onClick={confirm} loading={loading}>Stop Bot</Button>
        </div>
      </div>
    </Modal>
  )
}
