import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Knowledge, type KnowledgeAnswer, type Preference } from '../api'
import { cx, fmtDate } from '../ui'
import { setUnsaved } from '../unsaved'

/** Answers & style preferences (knowledge.yaml), edited locally and saved by the page's save dock. */
export function useKnowledge() {
  const [saved, setSaved] = useState<Knowledge | null>(null)
  const [k, setK] = useState<Knowledge | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = () => api.knowledge().then((x) => { setSaved(x); setK(structuredClone(x)) }).catch((e) => setError(e.message))
  useEffect(() => { void load() }, [])
  const dirty = !!k && JSON.stringify(k) !== JSON.stringify(saved)
  useEffect(() => { setUnsaved('knowledge', dirty) }, [dirty])
  useEffect(() => () => setUnsaved('knowledge', false), [])
  /** Returns false (with `error` set) when the save failed. */
  const save = async () => {
    setError(null)
    try {
      const x = await api.saveKnowledge(k!); setSaved(x); setK(structuredClone(x))
      return true
    } catch (e) {
      const conflict = (e as { status?: number }).status === 409
      setError(conflict ? 'Your answers/preferences changed elsewhere since this page loaded. Reload to get the latest, then re-apply your edit.' : (e as Error).message)
      if (conflict && window.confirm('Reload the latest answers/preferences now? Unsaved edits here will be discarded.')) void load()
      return false
    }
  }
  return { k, setK, dirty, save, load, error, setError, discard: () => setK(structuredClone(saved)) }
}

type KnowledgeEdit = { k: Knowledge; setK: (k: Knowledge) => void }

const label = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-accent'

export function AnswersPanel({ k, setK }: KnowledgeEdit) {
  const edit = (id: string, patch: Partial<KnowledgeAnswer>) =>
    setK({ ...k, answers: k.answers.map((a) => (a.id === id ? { ...a, ...patch } : a)) })
  const forget = (id: string) => setK({ ...k, answers: k.answers.filter((x) => x.id !== id) })
  const gaps = k.answers.filter((a) => a.kind === 'no_experience')
  const experience = k.answers.filter((a) => a.kind === 'experience')

  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-[720px] text-[13px] text-muted text-pretty">
        Everything you’ve answered on the Gaps step. Analysis reads this, so known gaps aren’t asked again and
        similar questions are pre-filled. These are <em>not</em> resume facts: only approved evidence in your profile can be cited.
      </p>
      {k.answers.length === 0 && (
        <div className="sheet rounded-lg px-8 py-10 text-center text-muted">No answers yet. They’ll appear here after your first Gaps step.</div>
      )}
      {gaps.length > 0 && (
        <section className="flex flex-col gap-2">
          <p className={label}>Known gaps · {gaps.length}</p>
          <ul className="rounded-lg border border-rule bg-sheet">
            {gaps.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-rule/70 px-[18px] py-3 last:border-b-0">
                <div>
                  <p className="text-ink">{a.topic}</p>
                  <p className="text-xs text-muted">No real experience · {a.company ?? 'unknown role'} · {fmtDate(a.date)}</p>
                </div>
                <button className="btn btn-ghost px-2 py-1 text-[13px] text-accent" onClick={() => forget(a.id)}>No longer true. Forget it</button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {experience.length > 0 && (
        <section className="flex flex-col gap-2.5">
          <p className={label}>Experience answers · {experience.length}</p>
          {experience.map((a) => (
            <div key={a.id} className="flex flex-col gap-1.5 rounded-lg border border-rule bg-sheet px-4 py-3.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-ink">{a.topic}</span>
                <span className="text-xs text-muted">
                  {a.company ?? 'unknown role'} · {fmtDate(a.date)} ·{' '}
                  {a.evidence_id
                    ? <span className="font-mono text-ok">evidence {a.evidence_id}</span>
                    : <span className="font-mono text-warn">not approved as evidence</span>}
                </span>
              </div>
              <p className="text-xs text-faint">{a.question}</p>
              <textarea className="field min-h-[60px] text-[13px]" rows={2} aria-label={`Answer ${a.id}`} value={a.answer} onChange={(e) => edit(a.id, { answer: e.target.value })} />
              <div className="flex justify-between text-xs">
                {a.app_id ? <Link to={`/a/${a.app_id}`} className="text-muted hover:text-accent">Open application →</Link> : <span />}
                <button className="cursor-pointer text-faint hover:text-bad" onClick={() => forget(a.id)}>Forget</button>
              </div>
            </div>
          ))}
          <p className="text-xs text-faint">Editing an answer here changes pre-fills only. To change a resume fact, edit the evidence under Experience.</p>
        </section>
      )}
    </div>
  )
}

const STATUS_LABEL: Record<Preference['status'], [string, string]> = {
  proposed: ['Awaiting approval', 'text-warn'], active: ['Active', 'text-ok'], dismissed: ['Dismissed', 'text-faint'],
}

export function PreferencesPanel({ k, setK }: KnowledgeEdit) {
  const [newText, setNewText] = useState('')
  const edit = (id: string, patch: Partial<Preference>) =>
    setK({ ...k, preferences: k.preferences.map((p) => (p.id === id ? { ...p, ...patch } : p)) })
  const order = { proposed: 0, active: 1, dismissed: 2 }
  const prefs = [...k.preferences].sort((a, b) => order[a.status] - order[b.status])
  const add = () => {
    if (!newText.trim()) return
    const taken = new Set([...k.preferences.map((p) => p.id), ...(k.retired_ids ?? [])])
    let n = 1
    while (taken.has(`p${n}`)) n++
    setK({ ...k, preferences: [...k.preferences, { id: `p${n}`, text: newText.trim(), rationale: 'Added by you', status: 'active', date: new Date().toISOString().slice(0, 10) }] })
    setNewText('')
  }
  const action = 'btn px-3 py-1 text-[13px]'

  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-[720px] text-[13px] text-muted text-pretty">
        Writing-style rules applied to every new draft. AutoCV proposes them from your Review edits and guidance
        (Export step → “Teach AutoCV your style”). Only <strong>active</strong> ones are used, and they never override the fact rules.
      </p>
      {prefs.map((p) => (
        <div key={p.id} className={cx('flex flex-col gap-2 rounded-lg border border-rule bg-sheet px-4 py-3.5', p.status === 'dismissed' && 'opacity-50')}>
          <div className="flex justify-between gap-3">
            <span className={cx('text-[11px] font-semibold uppercase tracking-[0.08em]', STATUS_LABEL[p.status][1])}>{STATUS_LABEL[p.status][0]}</span>
            <span className="text-xs text-faint">{fmtDate(p.date)}</span>
          </div>
          <input className="field py-[7px] text-sm" aria-label={`Preference ${p.id}`} value={p.text} onChange={(e) => edit(p.id, { text: e.target.value })} />
          {p.rationale && <p className="text-xs text-faint">{p.rationale}</p>}
          <div className="flex flex-wrap gap-2">
            {p.status !== 'active' && <button className={action} onClick={() => edit(p.id, { status: 'active' })}>Activate</button>}
            {p.status === 'active' && <button className={action} onClick={() => edit(p.id, { status: 'dismissed' })}>Deactivate</button>}
            {p.status === 'proposed' && <button className={action} onClick={() => edit(p.id, { status: 'dismissed' })}>Dismiss</button>}
            <button className={cx(action, 'text-faint hover:text-bad')} onClick={() => setK({ ...k, preferences: k.preferences.filter((x) => x.id !== p.id) })}>Delete</button>
          </div>
        </div>
      ))}
      {prefs.length === 0 && <div className="sheet rounded-lg px-8 py-10 text-center text-muted">No preferences yet.</div>}
      <div className="flex gap-2">
        <input className="field flex-1" placeholder="Add your own, e.g. “Prefer ‘led’ over ‘spearheaded’”" value={newText}
          onChange={(e) => setNewText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add() }} />
        <button className="btn" disabled={!newText.trim()} onClick={add}>Add</button>
      </div>
    </div>
  )
}
