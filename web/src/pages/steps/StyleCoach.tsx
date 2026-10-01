import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Application, type Preference } from '../../api'
import { cx, ErrorNote, Spinner } from '../../ui'

/** Turns this application's Review edits + guidance into proposed style preferences. */
export default function StyleCoach({ app }: { app: Application }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [proposals, setProposals] = useState<Preference[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const guidance = app.meta.guidance?.trim()

  if (!app.edits && !guidance) return null

  async function suggest() {
    setBusy(true); setError(null); setNote(null)
    try {
      const res = await api.suggestPreferences(app.id)
      setProposals(res.knowledge.preferences.filter((p) => p.status === 'proposed' && p.source_app === app.id))
      if (!res.proposed) setNote('Nothing new to learn from this one. Your edits were factual or already covered.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function decide(p: Preference, status: Preference['status'], text = p.text) {
    try {
      const k = await api.knowledge()
      const saved = await api.saveKnowledge({ ...k, preferences: k.preferences.map((x) => (x.id === p.id ? { ...x, status, text } : x)) })
      setProposals(saved.preferences.filter((x) => x.source_app === app.id && x.status !== 'dismissed'))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="sheet animate-rise rounded p-5 text-sm">
      <p className="eyebrow">Teach AutoCV your style</p>
      <p className="mt-2 text-muted">
        You changed {app.edits} claim{app.edits === 1 ? '' : 's'} from the AI draft{guidance ? ' and gave guidance' : ''}.
        AutoCV can turn that into style preferences for future roles. Nothing is applied until you approve it.
      </p>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {proposals === null ? (
        <button className="btn mt-3" disabled={busy} onClick={suggest}>{busy ? <><Spinner /> Studying your edits…</> : 'Suggest preferences'}</button>
      ) : (
        <ul className="mt-3 space-y-3">
          {proposals.map((p) => <ProposalRow key={p.id} p={p} onDecide={decide} />)}
          {note && <li className="text-muted">{note}</li>}
        </ul>
      )}
      <Link to="/profile?tab=prefs" className="mt-3 inline-block text-xs text-muted hover:text-rust">Manage all preferences →</Link>
    </div>
  )
}

function ProposalRow({ p, onDecide }: { p: Preference; onDecide: (p: Preference, s: Preference['status'], text?: string) => void }) {
  const [text, setText] = useState(p.text)
  const active = p.status === 'active'
  return (
    <li className={cx('rounded border p-3', active ? 'border-ok/40 bg-ok-soft/40' : 'border-rule')}>
      <input aria-label="Preference" className="field py-1 text-sm" disabled={active} value={text} onChange={(e) => setText(e.target.value)} />
      {p.rationale && <p className="mt-1 text-xs text-faint">{p.rationale}</p>}
      {active ? (
        <p className="mt-2 text-xs text-ok">✓ Active. Applied to future drafts.</p>
      ) : (
        <div className="mt-2 flex gap-2">
          <button className="btn btn-primary py-1" disabled={!text.trim()} onClick={() => onDecide(p, 'active', text.trim())}>Approve</button>
          <button className="btn py-1" onClick={() => onDecide(p, 'dismissed')}>Dismiss</button>
        </div>
      )}
    </li>
  )
}
