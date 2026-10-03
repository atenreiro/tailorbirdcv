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
    <section className="animate-rise flex flex-col gap-2.5 rounded-xl border border-rule bg-sheet px-[18px] py-4 text-[13px]" style={{ animationDelay: '120ms' }}>
      <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-muted">Teach AutoCV your style</p>
      <p className="text-muted">
        You changed {app.edits} claim{app.edits === 1 ? '' : 's'} from the AI draft{guidance ? ' and gave guidance' : ''}.
        AutoCV can turn that into style preferences for future roles. Nothing is applied until you approve it.
      </p>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {proposals === null ? (
        <button className="btn self-start px-3.5 py-1.5 text-[13px]" disabled={busy} onClick={suggest}>{busy ? <><Spinner /> Studying your edits…</> : 'Suggest preferences'}</button>
      ) : (
        <ul className="flex flex-col gap-2">
          {proposals.map((p) => <ProposalRow key={p.id} p={p} onDecide={decide} />)}
          {note && <li className="text-muted">{note}</li>}
        </ul>
      )}
      <Link to="/profile?tab=prefs" className="self-start text-xs text-muted hover:text-accent">Manage all preferences →</Link>
    </section>
  )
}

function ProposalRow({ p, onDecide }: { p: Preference; onDecide: (p: Preference, s: Preference['status'], text?: string) => void }) {
  const [text, setText] = useState(p.text)
  const active = p.status === 'active'
  return (
    <li className={cx('flex flex-col gap-1.5 rounded-lg border p-2.5', active ? 'border-ok/35 bg-[#eef7f2]' : 'border-rule bg-sheet')}>
      {active ? (
        <p className="text-ink">{text}</p>
      ) : (
        <textarea aria-label="Preference" title="Edit the wording before approving" rows={Math.max(2, Math.ceil(text.length / 36))}
          className="field resize-none border-transparent bg-transparent px-1.5 py-1 text-[13px] leading-[1.4] text-ink hover:border-rule focus:border-accent"
          value={text} onChange={(e) => setText(e.target.value)} />
      )}
      {p.rationale && <p className="text-[11px] text-faint">{p.rationale}</p>}
      {active ? (
        <p className="text-xs text-ok">✓ Active. Applied to future drafts.</p>
      ) : (
        <div className="flex gap-1.5">
          <button className="btn btn-primary px-2.5 py-[3px] text-xs font-medium" disabled={!text.trim()} onClick={() => onDecide(p, 'active', text.trim())}>Approve</button>
          <button className="btn px-2.5 py-[3px] text-xs" onClick={() => onDecide(p, 'dismissed')}>Dismiss</button>
        </div>
      )}
    </li>
  )
}
