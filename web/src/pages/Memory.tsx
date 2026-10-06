import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Knowledge, KnowledgeAnswer, Preference } from '../api'
import { cx, fmtDate } from '../lib'

type KnowledgeEdit = { k: Knowledge; setK: (k: Knowledge) => void }

const soft = 'w-full rounded-lg border border-line bg-wash outline-none transition-[border-color,background-color,box-shadow] focus:border-accent focus:bg-sheet focus:shadow-[0_0_0_3px_rgb(200_67_29/0.15)]'
const label = 'font-mono text-[11px] uppercase tracking-[0.08em] text-muted'

export function AnswersPanel({ k, setK }: KnowledgeEdit) {
  const edit = (id: string, patch: Partial<KnowledgeAnswer>) =>
    setK({ ...k, answers: k.answers.map((a) => (a.id === id ? { ...a, ...patch } : a)) })
  const forget = (id: string) => setK({ ...k, answers: k.answers.filter((x) => x.id !== id) })
  const gaps = k.answers.filter((a) => a.kind === 'no_experience')
  const experience = k.answers.filter((a) => a.kind === 'experience')

  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-[760px] text-sm leading-[1.5] text-muted text-pretty">
        Everything you’ve answered on the Gaps step. Analysis reads this, so known gaps aren’t asked again and
        similar questions are pre-filled. These are <em>not</em> resume facts: only approved evidence in your profile can be cited.
      </p>
      {k.answers.length === 0 && (
        <div className="rounded-[14px] border border-rule bg-sheet px-6 py-10 text-center text-muted">No answers yet. They’ll appear here after your first Gaps step.</div>
      )}
      {gaps.length > 0 && (
        <section className="flex flex-col gap-2.5">
          <p className={label}>Known gaps · {gaps.length}</p>
          <ul className="overflow-hidden rounded-[14px] border border-rule bg-sheet">
            {gaps.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e9efeb] px-5 py-3.5 last:border-b-0">
                <div className="flex flex-col gap-0.5">
                  <p className="text-[15px] font-semibold text-ink">{a.topic}</p>
                  <p className="text-[13px] text-muted">No real experience · {a.company ?? 'unknown role'} · {fmtDate(a.date)}</p>
                </div>
                <button className="h-8 cursor-pointer rounded-lg border border-rule bg-sheet px-3 text-[13px] font-medium text-accent hover:border-accent" onClick={() => forget(a.id)}>No longer true. Forget it</button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {experience.length > 0 && (
        <section className="flex flex-col gap-2.5">
          <p className={label}>Experience answers · {experience.length}</p>
          {experience.map((a) => (
            <div key={a.id} className="flex flex-col gap-2 rounded-[14px] border border-rule bg-sheet px-5 py-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[15px] font-semibold text-ink">{a.topic}</span>
                <span className="text-[13px] text-muted">
                  {a.company ?? 'unknown role'} · {fmtDate(a.date)} ·{' '}
                  {a.evidence_id
                    ? <span className="font-mono text-xs text-ok">evidence {a.evidence_id}</span>
                    : <span className="font-mono text-xs text-[#7a4700]">not approved as evidence</span>}
                </span>
              </div>
              <p className="text-[13px] text-faint">{a.question}</p>
              <textarea className={cx(soft, 'min-h-[60px] resize-y px-3 py-2 text-sm leading-[1.45]')} rows={2} aria-label={`Answer ${a.id}`} value={a.answer} onChange={(e) => edit(a.id, { answer: e.target.value })} />
              <div className="flex justify-between gap-3 text-[13px]">
                {a.app_id ? <Link to={`/a/${a.app_id}`} className="text-muted hover:text-accent">Open application →</Link> : <span />}
                <button className="cursor-pointer text-faint hover:text-bad" onClick={() => forget(a.id)}>Forget</button>
              </div>
            </div>
          ))}
          <p className="text-[13px] text-faint">Editing an answer here changes pre-fills only. To change a resume fact, edit the evidence under Experience.</p>
        </section>
      )}
    </div>
  )
}

const STATUS_LABEL: Record<Preference['status'], [string, string]> = {
  proposed: ['Awaiting approval', 'text-[#7a4700]'], active: ['Active', 'text-ok'], dismissed: ['Dismissed', 'text-faint'],
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
  const action = 'btn h-8 px-3 py-0 text-[13px]'

  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-[760px] text-sm leading-[1.5] text-muted text-pretty">
        Writing-style rules applied to every new draft. TailorbirdCV proposes them from your Review edits and guidance
        (Export step → “Teach TailorbirdCV your style”). Only <strong>active</strong> ones are used, and they never override the fact rules.
      </p>
      {prefs.map((p) => (
        <div key={p.id} className={cx('flex flex-col gap-2.5 rounded-[14px] border border-rule bg-sheet px-5 py-4', p.status === 'dismissed' && 'opacity-50', p.status === 'proposed' && 'shadow-[inset_3px_0_0_#c47a00]')}>
          <div className="flex justify-between gap-3">
            <span className={cx('inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.06em]', STATUS_LABEL[p.status][1])}><span className="size-1.5 rounded-full bg-current" />{STATUS_LABEL[p.status][0]}</span>
            <span className="font-mono text-[11px] text-faint">{fmtDate(p.date)}</span>
          </div>
          <input className={cx(soft, 'h-10 px-3 text-[15px]')} aria-label={`Preference ${p.id}`} value={p.text} onChange={(e) => edit(p.id, { text: e.target.value })} />
          {p.rationale && <p className="text-[13px] text-faint">{p.rationale}</p>}
          <div className="flex flex-wrap gap-2">
            {p.status !== 'active' && <button className={cx(action, p.status === 'proposed' && 'border-accent bg-accent text-white hover:border-accent-strong hover:bg-accent-strong')} onClick={() => edit(p.id, { status: 'active' })}>Activate</button>}
            {p.status === 'active' && <button className={action} onClick={() => edit(p.id, { status: 'dismissed' })}>Deactivate</button>}
            {p.status === 'proposed' && <button className={action} onClick={() => edit(p.id, { status: 'dismissed' })}>Dismiss</button>}
            <button className={cx(action, 'text-faint hover:text-bad')} onClick={() => setK({ ...k, preferences: k.preferences.filter((x) => x.id !== p.id) })}>Delete</button>
          </div>
        </div>
      ))}
      {prefs.length === 0 && <div className="rounded-[14px] border border-rule bg-sheet px-6 py-10 text-center text-muted">No preferences yet.</div>}
      <div className="flex gap-2">
        <input className="field h-10 min-w-0 flex-1" placeholder="Add your own, e.g. “Prefer ‘led’ over ‘spearheaded’”" value={newText}
          onChange={(e) => setNewText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add() }} />
        <button className="btn btn-primary h-10 px-[18px] disabled:border-[#c0ccc5] disabled:bg-[#c0ccc5] disabled:opacity-100" disabled={!newText.trim()} onClick={add}>Add</button>
      </div>
    </div>
  )
}
