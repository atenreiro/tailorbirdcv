import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type AppAnswer, type Knowledge, type Proposal } from '../../api'
import { cx, ErrorNote, Section, Spinner } from '../../ui'
import type { StepProps } from '../Workspace'

type Draft = Proposal & { state: 'pending' | 'approved' | 'rejected'; id?: string }
type Question = { id: string; requirement: string; question: string; prefill_from?: string }

const REOPENED = 'kg-' // question ids for known gaps the user asked to revisit

function fmt(date?: string) {
  return date ? new Date(date).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

export default function Gaps({ app, profile, setApp, reloadProfile, go, run }: StepProps) {
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null)
  const [answers, setAnswers] = useState<Record<string, AppAnswer>>(() =>
    Object.fromEntries(app.answers.map((a) => [a.question_id, a])))
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [drafting, setDrafting] = useState(false)
  const [guidance, setGuidance] = useState(app.meta.guidance ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<'idle' | 'saving' | 'saved'>('idle')
  const saveTimer = useRef<number | undefined>(undefined)

  useEffect(() => { api.knowledge().then(setKnowledge).catch(() => setKnowledge({ answers: [], preferences: [] })) }, [])

  const kById = useMemo(() => Object.fromEntries((knowledge?.answers ?? []).map((k) => [k.id, k])), [knowledge])
  const knownGaps = (app.analysis?.known_gaps ?? []).filter((g) => kById[g.knowledge_id])

  // Analysis questions + known gaps the user reopened (persisted in answers.yaml).
  const questions: Question[] = useMemo(() => [
    ...(app.analysis?.questions ?? []),
    ...Object.values(answers).filter((a) => a.question_id.startsWith(REOPENED))
      .map((a) => ({ id: a.question_id, requirement: a.requirement, question: a.question })),
  ], [app.analysis, answers])

  // Pre-fill from past answers once knowledge has loaded (never over a saved answer).
  useEffect(() => {
    if (!knowledge) return
    setAnswers((prev) => {
      const next = { ...prev }
      let changed = false
      for (const q of app.analysis?.questions ?? []) {
        const k = q.prefill_from ? kById[q.prefill_from] : undefined
        if (!k || next[q.id]) continue
        next[q.id] = {
          question_id: q.id, requirement: q.requirement, question: q.question, prefill_from: k.id,
          answer: k.kind === 'experience' ? k.answer : '', status: k.kind === 'no_experience' ? 'no_experience' : 'draft',
        }
        changed = true
      }
      return changed ? next : prev
    })
  }, [knowledge, kById, app.analysis])

  const persist = (next: Record<string, AppAnswer>, immediate = false) => {
    window.clearTimeout(saveTimer.current)
    const save = async () => {
      setSaved('saving')
      try {
        await api.saveAnswers(app.id, Object.values(next))
        setSaved('saved')
      } catch (e) {
        setError((e as Error).message)
        setSaved('idle')
      }
    }
    if (immediate) void save()
    else saveTimer.current = window.setTimeout(save, 700)
  }

  const update = (q: Question, patch: Partial<AppAnswer>, immediate = false) => {
    setAnswers((prev) => {
      const base: AppAnswer = prev[q.id] ?? { question_id: q.id, requirement: q.requirement, question: q.question, answer: '', status: 'draft' }
      const next = { ...prev, [q.id]: { ...base, ...patch } }
      persist(next, immediate)
      return next
    })
  }

  const reopen = (requirement: string, knowledgeId: string) => {
    const k = kById[knowledgeId]
    const q: Question = {
      id: `${REOPENED}${knowledgeId}`, requirement,
      question: `Earlier you said you had no real experience with “${k?.topic ?? requirement}” (${fmt(k?.date)}). Has that changed? If so, where and what?`,
    }
    update(q, {}, true)
  }

  const roles = profile.profile.roles
  const categories = profile.profile.skills.map((s) => s.category)
  const answered = questions.filter((q) => answers[q.id]?.answer.trim() && answers[q.id]?.status === 'draft')
  const pending = drafts.filter((d) => d.state === 'pending').length

  async function draftEvidence() {
    setDrafting(true)
    setError(null)
    try {
      const proposals = await api.proposals(app.id, answered.map((q) => ({ question_id: q.id, question: q.question, answer: answers[q.id].answer })))
      setDrafts(proposals.map((p) => ({ ...p, state: 'pending' })))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDrafting(false)
    }
  }

  const questionFor = (qid: string) => questions.find((x) => x.id === qid)

  async function approve(i: number) {
    const d = drafts[i]
    try {
      const q = questionFor(d.question_id)
      const res = await api.addEvidence({
        target: d.target, text: d.text, skills: d.skills,
        note: q ? `Q: ${q.question} A: ${answers[q.id]?.answer ?? ''}` : undefined,
      })
      setDrafts((prev) => prev.map((x, j) => (j === i ? { ...x, state: 'approved', id: res.id } : x)))
      if (q) update(q, { status: 'approved', evidence_id: res.id }, true)
      await reloadProfile()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  function reject(i: number) {
    const d = drafts[i]
    setDrafts((prev) => prev.map((x, j) => (j === i ? { ...x, state: 'rejected' } : x)))
    const q = questionFor(d.question_id)
    if (q) update(q, { status: 'rejected' }, true)
  }

  const patchDraft = (i: number, patch: Partial<Draft>) =>
    setDrafts((prev) => prev.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  const compose = () =>
    run('Composing your tailored resume', [
      'Choosing the headline and leading highlights…',
      'Reordering evidence by relevance to this role…',
      'Rephrasing in the job’s vocabulary — facts locked…',
      'Applying your approved style preferences…',
      'Running the fact-check and repairing any issues…',
    ], async () => {
      setApp(await api.compose(app.id, guidance))
      go('review')
    })

  return (
    <div className="space-y-10">
      <Section
        eyebrow="Gaps"
        title={questions.length ? 'A few questions before writing' : 'No new gaps to ask about'}
        aside={saved !== 'idle' && <span className="text-xs text-faint">{saved === 'saving' ? 'Saving…' : '✓ Answers saved'}</span>}
      >
        <p className="mb-6 max-w-2xl text-muted">
          {questions.length
            ? 'These requirements have weak or no evidence in your profile. Answer only with real experience; anything left blank or marked “No real experience” stays a gap. Your answers are saved and remembered for future roles.'
            : 'Your profile and past answers cover every must-have. You can go straight to composing.'}
        </p>
        <ol className="space-y-5">
          {questions.map((q, i) => {
            const ans = answers[q.id]
            const none = ans?.status === 'no_experience'
            const locked = ans?.status === 'approved'
            const prefill = ans?.prefill_from ? kById[ans.prefill_from] : undefined
            return (
              <li key={q.id} className="sheet animate-rise rounded p-5" style={{ animationDelay: `${i * 60}ms` }}>
                <p className="text-[11px] uppercase tracking-wider text-muted">{q.requirement}</p>
                <p className="mt-1 font-serif text-xl text-ink">{q.question}</p>
                {prefill && (
                  <p className="mt-2 rounded bg-wash px-3 py-1.5 text-xs text-muted">
                    ↺ Pre-filled from your answer{prefill.company ? ` for ${prefill.company}` : ''} on {fmt(prefill.date)}. Confirm or update it.
                  </p>
                )}
                <textarea
                  className={cx('field mt-3 min-h-[84px]', (none || locked) && 'opacity-50')}
                  disabled={none || locked}
                  placeholder="Where, what you did, the scale. Plain facts are best."
                  value={ans?.answer ?? ''}
                  onChange={(e) => update(q, { answer: e.target.value, status: 'draft', evidence_id: null })}
                />
                {locked ? (
                  <p className="mt-2 text-sm text-ok">✓ Saved to your profile as <span className="font-mono text-xs">{ans?.evidence_id}</span></p>
                ) : (
                  <label className="mt-2 inline-flex cursor-pointer items-center gap-2 text-sm text-muted">
                    <input type="checkbox" className="accent-rust" checked={none}
                      onChange={(e) => update(q, { status: e.target.checked ? 'no_experience' : 'draft' }, true)} />
                    No real experience. Keep it as a gap (remembered, so I won’t ask again).
                  </label>
                )}
              </li>
            )
          })}
        </ol>
        {questions.length > 0 && (
          <button className="btn mt-5" disabled={!answered.length || drafting} onClick={draftEvidence}>
            {drafting ? <><Spinner /> Drafting evidence…</> : `Draft evidence from ${answered.length} answer${answered.length === 1 ? '' : 's'}`}
          </button>
        )}
      </Section>

      {knownGaps.length > 0 && (
        <Section eyebrow="Remembered" title="Known gaps, not asked again">
          <ul className="divide-y divide-rule/70">
            {knownGaps.map((g) => {
              const k = kById[g.knowledge_id]
              const reopened = !!answers[`${REOPENED}${g.knowledge_id}`]
              return (
                <li key={g.knowledge_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span>
                    <span className="text-ink">{g.requirement}</span>
                    <span className="block text-xs text-muted">
                      You answered “no real experience”{k.company ? ` for ${k.company}` : ''} on {fmt(k.date)}.
                    </span>
                  </span>
                  <button className="btn btn-ghost text-sm text-rust" disabled={reopened} onClick={() => reopen(g.requirement, g.knowledge_id)}>
                    {reopened ? 'Asked above ↑' : 'This has changed. Ask me again'}
                  </button>
                </li>
              )
            })}
          </ul>
        </Section>
      )}

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {drafts.length > 0 && (
        <Section eyebrow="Your approval" title="Proposed additions to your master profile">
          <p className="mb-4 max-w-2xl text-sm text-muted">
            Edit the wording until it’s exactly true, then approve. Only approved items are saved, tagged as coming from you.
          </p>
          <div className="space-y-4">
            {drafts.map((d, i) => (
              <div key={i} className={cx('sheet rounded p-5 transition', d.state === 'approved' && 'border-ok/50 bg-ok-soft/40', d.state === 'rejected' && 'opacity-50')}>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <span className="text-muted">Belongs to</span>
                  <select className="field w-auto py-1" disabled={d.state !== 'pending'} value={d.target} onChange={(e) => patchDraft(i, { target: e.target.value })}>
                    {roles.map((r) => <option key={r.id} value={r.id}>{r.employer}</option>)}
                    <option value="general">General (not role-specific)</option>
                  </select>
                  {d.state === 'approved' && <span className="chip bg-ok-soft text-ok">saved as {d.id}</span>}
                </div>
                <textarea className="field mt-3 min-h-[64px] font-serif text-[16px]" disabled={d.state !== 'pending'} value={d.text} onChange={(e) => patchDraft(i, { text: e.target.value })} />
                {d.skills.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted">Skills to add:</span>
                    {d.skills.map((s, j) => (
                      <span key={j} className="chip">
                        {s.item}
                        <select
                          className="bg-transparent text-faint"
                          disabled={d.state !== 'pending'}
                          value={s.category}
                          onChange={(e) => patchDraft(i, { skills: d.skills.map((x, k) => (k === j ? { ...x, category: e.target.value } : x)) })}
                        >
                          {categories.map((c) => <option key={c}>{c}</option>)}
                        </select>
                        {d.state === 'pending' && (
                          <button onClick={() => patchDraft(i, { skills: d.skills.filter((_, k) => k !== j) })} aria-label={`Drop skill ${s.item}`}>×</button>
                        )}
                      </span>
                    ))}
                  </div>
                )}
                {d.state === 'pending' && (
                  <div className="mt-4 flex gap-2">
                    <button className="btn btn-primary" disabled={!d.text.trim()} onClick={() => approve(i)}>Approve & save</button>
                    <button className="btn" onClick={() => reject(i)}>Reject</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section eyebrow="Compose" title="Write the tailored resume">
        <label className="block text-sm text-muted" htmlFor="guidance">
          Optional guidance for this role, e.g. “lead with the mobile money fraud work”. Your approved style preferences are applied automatically.
        </label>
        <textarea id="guidance" className="field mt-2 min-h-[64px]" value={guidance} onChange={(e) => setGuidance(e.target.value)} />
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <button className="btn btn-primary" onClick={compose} disabled={pending > 0}>
            {app.tailored ? 'Re-compose tailored resume →' : 'Compose tailored resume →'}
          </button>
          {pending > 0 && <span className="text-sm text-warn">Approve or reject the {pending} pending proposal{pending > 1 ? 's' : ''} first.</span>}
          {app.tailored && <button className="btn btn-ghost" onClick={() => go('review')}>Back to the current draft</button>}
        </div>
      </Section>
    </div>
  )
}
