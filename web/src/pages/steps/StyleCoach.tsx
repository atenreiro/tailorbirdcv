import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Application, type Preference } from '../../api'
import { cx } from '../../lib'
import { ErrorNote, Spinner } from '../../ui'

/** Turns this application's edits (resume and cover letter) + guidance into proposed style
 *  preferences. Marking the application applied does this by itself in the background; the
 *  button does it on demand. Nothing is used until the user approves it. */
export default function StyleCoach({ app }: { app: Application }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [proposals, setProposals] = useState<Preference[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [learning, setLearning] = useState(!!app.learning_style)
  const guidance = app.meta.guidance?.trim()
  const mine = (ps: Preference[]) => ps.filter((p) => p.source_app === app.id && p.status !== 'dismissed')

  // Suggestions already made for this application (e.g. when it was marked applied) show up by themselves.
  useEffect(() => {
    let live = true
    api.knowledge().then((k) => { if (live && mine(k.preferences).length) setProposals(mine(k.preferences)) }).catch(() => {})
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.id])

  // Learning in the background: check back until it's done, then show what it suggested.
  useEffect(() => { setLearning(!!app.learning_style) }, [app.learning_style])
  useEffect(() => {
    if (!learning) return
    const timer = window.setInterval(async () => {
      try {
        if ((await api.get(app.id)).learning_style) return
        setLearning(false)
        const found = mine((await api.knowledge()).preferences)
        setProposals(found)
        if (!found.length) setNote('Nothing new to learn from this one. Your edits were factual or already covered.')
      } catch { /* try again on the next tick */ }
    }, 5000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [learning, app.id])

  if (!app.edits && !guidance && !proposals?.length && !learning) return null

  async function suggest() {
    setBusy(true); setError(null); setNote(null)
    try {
      const res = await api.suggestPreferences(app.id)
      setProposals(mine(res.knowledge.preferences))
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
      setProposals(mine(saved.preferences))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <section className="animate-rise flex flex-col gap-2.5 rounded-xl border border-rule bg-sheet px-[18px] py-4 text-[13px]" style={{ animationDelay: '120ms' }}>
      <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-muted">Teach TailorbirdCV your style</p>
      <p className="text-muted">
        {app.edits
          ? <>You changed {app.edits} line{app.edits === 1 ? '' : 's'} from the AI’s draft{guidance ? ' and gave guidance' : ''}. </>
          : guidance ? <>You gave guidance for this draft. </> : null}
        TailorbirdCV turns that into style preferences for future drafts. Nothing is applied until you approve it.
      </p>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {learning && proposals === null ? (
        <p className="flex items-center gap-2 text-muted"><Spinner /> Studying what you changed before sending…</p>
      ) : proposals === null ? (
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
