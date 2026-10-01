import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Knowledge, type KnowledgeAnswer, type Preference } from '../api'
import { cx, ErrorNote, fmtDate, Spinner } from '../ui'
import { setUnsaved } from '../unsaved'

function useKnowledge() {
  const [saved, setSaved] = useState<Knowledge | null>(null)
  const [k, setK] = useState<Knowledge | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.knowledge().then((x) => { setSaved(x); setK(structuredClone(x)) }).catch((e) => setError(e.message))
  }, [])
  const dirty = JSON.stringify(k) !== JSON.stringify(saved)
  useEffect(() => { setUnsaved('knowledge', dirty) }, [dirty])
  useEffect(() => () => setUnsaved('knowledge', false), [])
  const reload = () => api.knowledge().then((x) => { setSaved(x); setK(structuredClone(x)) })
  const save = async () => {
    setBusy(true); setError(null)
    try {
      const x = await api.saveKnowledge(k!); setSaved(x); setK(structuredClone(x))
    } catch (e) {
      const conflict = (e as { status?: number }).status === 409
      setError(conflict ? 'Your answers/preferences changed elsewhere since this page loaded. Reload the page to get the latest, then re-apply your edit.' : (e as Error).message)
      if (conflict && window.confirm('Reload the latest answers/preferences now? Unsaved edits here will be discarded.')) void reload()
    } finally { setBusy(false) }
  }
  return { k, setK, dirty, save, busy, error, setError, discard: () => setK(structuredClone(saved)) }
}

function SaveBar({ dirty, busy, save, discard }: { dirty: boolean; busy: boolean; save: () => void; discard: () => void }) {
  if (!dirty) return null
  return (
    <div className="sticky bottom-4 z-10 flex justify-end gap-2">
      <div className="sheet flex gap-2 rounded p-2">
        <button className="btn" onClick={discard}>Discard</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? <><Spinner /> Saving…</> : 'Save changes'}</button>
      </div>
    </div>
  )
}

export function AnswersPanel() {
  const { k, setK, dirty, save, busy, error, setError, discard } = useKnowledge()
  if (!k) return error ? <ErrorNote error={error} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>
  const edit = (id: string, patch: Partial<KnowledgeAnswer>) =>
    setK({ ...k, answers: k.answers.map((a) => (a.id === id ? { ...a, ...patch } : a)) })
  const gaps = k.answers.filter((a) => a.kind === 'no_experience')
  const experience = k.answers.filter((a) => a.kind === 'experience')

  return (
    <div className="space-y-8">
      <p className="max-w-2xl text-sm text-muted">
        Everything you’ve answered on the Gaps step. Analysis reads this, so known gaps aren’t asked again and
        similar questions are pre-filled. These are <em>not</em> resume facts: only approved evidence in your profile can be cited.
      </p>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {k.answers.length === 0 && (
        <div className="sheet rounded px-8 py-10 text-center text-muted">No answers yet. They’ll appear here after your first Gaps step.</div>
      )}
      {gaps.length > 0 && (
        <section>
          <p className="eyebrow mb-2">Known gaps · {gaps.length}</p>
          <ul className="sheet divide-y divide-rule/70 rounded">
            {gaps.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <span>
                  <span className="text-ink">{a.topic}</span>
                  <span className="block text-xs text-muted">No real experience · {a.company ?? 'unknown role'} · {fmtDate(a.date)}</span>
                </span>
                <button className="btn btn-ghost text-sm text-rust" onClick={() => setK({ ...k, answers: k.answers.filter((x) => x.id !== a.id) })}>
                  No longer true. Forget it
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {experience.length > 0 && (
        <section>
          <p className="eyebrow mb-2">Experience answers · {experience.length}</p>
          <ul className="space-y-3">
            {experience.map((a) => (
              <li key={a.id} className="sheet rounded p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-ink">{a.topic}</span>
                  <span className="text-xs text-muted">
                    {a.company ?? 'unknown role'} · {fmtDate(a.date)} ·{' '}
                    {a.evidence_id ? <span className="font-mono text-ok">evidence {a.evidence_id}</span> : <span className="text-warn">not approved as evidence</span>}
                  </span>
                </div>
                <p className="mt-1 text-xs text-faint">{a.question}</p>
                <textarea className="field mt-2 min-h-[60px] text-sm" aria-label={`Answer ${a.id}`} value={a.answer} onChange={(e) => edit(a.id, { answer: e.target.value })} />
                <div className="mt-2 flex justify-between text-xs">
                  {a.app_id ? <Link to={`/a/${a.app_id}`} className="text-muted hover:text-rust">Open application →</Link> : <span />}
                  <button className="text-faint hover:text-bad" onClick={() => setK({ ...k, answers: k.answers.filter((x) => x.id !== a.id) })}>Forget</button>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-faint">Editing an answer here changes pre-fills only. To change a resume fact, edit the evidence in the Experience tab.</p>
        </section>
      )}
      <SaveBar dirty={dirty} busy={busy} save={save} discard={discard} />
    </div>
  )
}

const STATUS_LABEL: Record<Preference['status'], string> = { active: 'Active', proposed: 'Awaiting approval', dismissed: 'Dismissed' }

export function PreferencesPanel() {
  const { k, setK, dirty, save, busy, error, setError, discard } = useKnowledge()
  const [newText, setNewText] = useState('')
  if (!k) return error ? <ErrorNote error={error} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>
  const edit = (id: string, patch: Partial<Preference>) =>
    setK({ ...k, preferences: k.preferences.map((p) => (p.id === id ? { ...p, ...patch } : p)) })
  const order = { proposed: 0, active: 1, dismissed: 2 }
  const prefs = [...k.preferences].sort((a, b) => order[a.status] - order[b.status])
  const add = () => {
    const taken = new Set([...k.preferences.map((p) => p.id), ...(k.retired_ids ?? [])])
    let n = 1
    while (taken.has(`p${n}`)) n++
    setK({ ...k, preferences: [...k.preferences, { id: `p${n}`, text: newText.trim(), rationale: 'Added by you', status: 'active', date: new Date().toISOString().slice(0, 10) }] })
    setNewText('')
  }

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-muted">
        Writing-style rules applied to every new draft. AutoCV proposes them from your Review edits and guidance
        (Export step → “Teach AutoCV your style”). Only <strong>active</strong> ones are used, and they never override the fact rules.
      </p>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <ul className="space-y-3">
        {prefs.map((p) => (
          <li key={p.id} className={cx('sheet rounded p-4', p.status === 'dismissed' && 'opacity-50')}>
            <div className="flex items-center justify-between gap-3">
              <span className={cx('text-[11px] font-semibold uppercase tracking-wider', p.status === 'active' ? 'text-ok' : p.status === 'proposed' ? 'text-warn' : 'text-faint')}>
                {STATUS_LABEL[p.status]}
              </span>
              <span className="text-xs text-faint">{fmtDate(p.date)}</span>
            </div>
            <input className="field mt-2 text-sm" aria-label={`Preference ${p.id}`} value={p.text} onChange={(e) => edit(p.id, { text: e.target.value })} />
            {p.rationale && <p className="mt-1 text-xs text-faint">{p.rationale}</p>}
            <div className="mt-2 flex gap-2 text-sm">
              {p.status !== 'active' && <button className="btn py-1" onClick={() => edit(p.id, { status: 'active' })}>Activate</button>}
              {p.status === 'active' && <button className="btn py-1" onClick={() => edit(p.id, { status: 'dismissed' })}>Deactivate</button>}
              {p.status === 'proposed' && <button className="btn py-1" onClick={() => edit(p.id, { status: 'dismissed' })}>Dismiss</button>}
              <button className="btn btn-ghost py-1 text-faint hover:text-bad" onClick={() => setK({ ...k, preferences: k.preferences.filter((x) => x.id !== p.id) })}>Delete</button>
            </div>
          </li>
        ))}
        {prefs.length === 0 && <li className="sheet rounded px-8 py-10 text-center text-muted">No preferences yet.</li>}
      </ul>
      <div className="flex gap-2">
        <input className="field" placeholder="Add your own, e.g. “Prefer ‘led’ over ‘spearheaded’”" value={newText} onChange={(e) => setNewText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && newText.trim()) add() }} />
        <button className="btn" disabled={!newText.trim()} onClick={add}>Add</button>
      </div>
      <SaveBar dirty={dirty} busy={busy} save={save} discard={discard} />
    </div>
  )
}
