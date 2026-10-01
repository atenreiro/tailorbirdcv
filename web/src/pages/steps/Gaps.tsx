import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type AppAnswer, type Knowledge } from '../../api'
import { cx, ErrorNote } from '../../ui'
import type { StepProps } from '../Workspace'
import { gapQuestions, gapState, openGaps, REOPENED, type Draft, type GapState, type Question } from './gapState'

const label = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-rust'
const card = 'rounded border border-rule bg-sheet'
const CHIP: Record<GapState, [string, string]> = {
  open: ['open', 'bg-bad-soft text-bad'],
  draft: ['draft', 'bg-warn-soft text-warn'],
  pending: ['to approve', 'bg-rust-soft text-rust'],
  approved: ['evidence', 'bg-ok-soft text-ok'],
  no_experience: ['no exp.', 'bg-wash text-muted'],
}

function fmt(date?: string) {
  return date ? new Date(date).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

export default function Gaps({ app, profile, setApp, reloadProfile, go, run, memo, setMemo }: StepProps) {
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<'idle' | 'saving' | 'saved'>('idle')
  const saveTimer = useRef<number | undefined>(undefined)
  const pendingSave = useRef<Record<string, AppAnswer> | null>(null)

  // State lives in Workspace (memo.gaps) so it survives switching steps; seeded from the server.
  const gaps = memo.gaps ?? {
    answers: Object.fromEntries(app.answers.map((a) => [a.question_id, a])) as Record<string, AppAnswer>,
    proposals: [] as Draft[],
    guidance: app.meta.guidance ?? '',
  }
  const { answers, proposals: drafts, guidance } = gaps
  const answersRef = useRef(answers)
  answersRef.current = answers
  const patchGaps = (patch: Partial<typeof gaps>) =>
    setMemo((m) => ({ ...m, gaps: { ...(m.gaps ?? gaps), ...patch } }))
  const setAnswers = (next: Record<string, AppAnswer>) => { answersRef.current = next; patchGaps({ answers: next }) }
  const setDrafts = (fn: (prev: Draft[]) => Draft[]) =>
    setMemo((m) => { const g = m.gaps ?? gaps; return { ...m, gaps: { ...g, proposals: fn(g.proposals) } } })
  const setGuidance = (g: string) => patchGaps({ guidance: g })

  // Flush a debounced save if the step unmounts before it fires.
  useEffect(() => () => {
    window.clearTimeout(saveTimer.current)
    if (pendingSave.current) void api.saveAnswers(app.id, Object.values(pendingSave.current)).catch(() => {})
  }, [app.id])

  useEffect(() => { api.knowledge().then(setKnowledge).catch(() => setKnowledge({ answers: [], preferences: [] })) }, [])

  const kById = useMemo(() => Object.fromEntries((knowledge?.answers ?? []).map((k) => [k.id, k])), [knowledge])
  const knownGaps = (app.analysis?.known_gaps ?? []).filter((g) => kById[g.knowledge_id])

  const questions: Question[] = useMemo(() => gapQuestions(app.analysis, answers), [app.analysis, answers])

  // Pre-fill from past answers once knowledge has loaded (never over a saved answer).
  useEffect(() => {
    if (!knowledge) return
    const next = { ...answersRef.current }
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
    if (changed) setAnswers(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knowledge, kById, app.analysis])

  const persist = (next: Record<string, AppAnswer>, immediate = false) => {
    window.clearTimeout(saveTimer.current)
    pendingSave.current = next
    const save = async () => {
      pendingSave.current = null
      setSaved('saving')
      try {
        const savedAnswers = await api.saveAnswers(app.id, Object.values(next))
        setApp((prev) => ({ ...prev, answers: savedAnswers }))
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
    const prev = answersRef.current
    const base: AppAnswer = prev[q.id] ?? { question_id: q.id, requirement: q.requirement, question: q.question, answer: '', status: 'draft' }
    const next = { ...prev, [q.id]: { ...base, ...patch } }
    setAnswers(next)
    persist(next, immediate)
  }

  const stateOf = (q: Question) => gapState(answers[q.id], drafts, q.id)
  const open = openGaps(questions, answers, drafts)
  const selId = memo.gapFocus && questions.some((q) => q.id === memo.gapFocus) ? memo.gapFocus : (open[0] ?? questions[0])?.id
  const sel = questions.find((q) => q.id === selId)
  const select = (qid: string) => setMemo((m) => ({ ...m, gapFocus: qid }))

  const reopen = (requirement: string, knowledgeId: string) => {
    const k = kById[knowledgeId]
    const q: Question = {
      id: `${REOPENED}${knowledgeId}`, requirement,
      question: `Earlier you said you had no real experience with “${k?.topic ?? requirement}” (${fmt(k?.date)}). Has that changed? If so, where and what?`,
    }
    update(q, {}, true)
    select(q.id)
  }

  const roles = profile.profile.roles
  const categories = profile.profile.skills.map((s) => s.category)
  // Answers ready to become evidence: typed, and not settled or awaiting approval.
  const draftable = (q: Question) => !!answers[q.id]?.answer.trim() && ['draft', 'open'].includes(stateOf(q))
    && ['draft', 'rejected'].includes(answers[q.id]?.status ?? '')
  const answered = questions.filter(draftable)
  const pending = drafts.filter((d) => d.state === 'pending').length

  const draftEvidence = (qs: Question[]) =>
    run(qs.length > 1 ? `Drafting evidence from ${qs.length} answers` : 'Drafting evidence from your answer', [
      'Turning your answer into a profile entry…',
      'Checking it against your existing evidence…',
    ], async () => {
      const proposals = await api.proposals(app.id, qs.map((q) => ({ question_id: q.id, question: q.question, answer: answers[q.id].answer })))
      const ids = new Set(qs.map((q) => q.id))
      setDrafts((prev) => [
        ...prev.filter((d) => !ids.has(d.question_id) || d.state === 'approved'),
        ...proposals.map((p): Draft => ({ ...p, state: 'pending' })),
      ])
    })

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

  const compose = () => {
    if (memo.review && !window.confirm('Re-composing replaces your unsaved Review edits. Continue?')) return
    void composeNow()
  }
  const composeNow = () =>
    run('Composing your tailored resume', [
      'Choosing the headline and leading highlights…',
      'Reordering evidence by relevance to this role…',
      'Rephrasing in the job’s vocabulary — facts locked…',
      'Applying your approved style preferences…',
      'Running the fact-check and repairing any issues…',
      'Checking it fits on 2 pages, trimming if needed…',
    ], async () => {
      setApp(await api.compose(app.id, guidance))
      setMemo((m) => ({ ...m, review: null }))
      go('review')
    })

  // Proposals for the selected question, plus any whose question no longer exists (never hide a pending one).
  const shown = drafts.map((d, i) => ({ d, i }))
    .filter(({ d }) => d.state !== 'rejected' && (d.question_id === sel?.id || !questionFor(d.question_id)))

  const ans = sel ? answers[sel.id] : undefined
  const st = sel ? stateOf(sel) : 'open'
  const prefill = ans?.prefill_from ? kById[ans.prefill_from] : undefined

  return (
    <div className="flex flex-wrap items-start gap-6">
      {/* ------------------------------------------------------------ question list */}
      <aside className="animate-rise flex min-w-0 flex-[1_1_240px] flex-col gap-2.5 lg:max-w-[320px] lg:flex-[0_1_300px]">
        <div className="flex items-baseline justify-between gap-3">
          <p className={label}>Gap questions · {questions.length}</p>
          {saved !== 'idle' && <span className="text-xs text-faint" role="status">{saved === 'saving' ? 'Saving…' : '✓ Saved'}</span>}
        </div>
        <div className={cx(card, 'overflow-hidden')}>
          {questions.map((q) => {
            const [chip, chipCls] = CHIP[stateOf(q)]
            return (
              <button key={q.id} onClick={() => select(q.id)} aria-current={q.id === sel?.id ? 'true' : undefined}
                className={cx('flex w-full cursor-pointer flex-col gap-1.5 border-b border-rule px-4 py-3.5 text-left transition-colors last:border-b-0 hover:bg-wash', q.id === sel?.id && 'bg-wash')}>
                <span className="flex items-center justify-between gap-2">
                  <span className="min-w-0 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">{q.requirement}</span>
                  <span className={cx('flex-none rounded-full px-2 py-px text-[10px] font-semibold uppercase tracking-[0.06em]', chipCls)}>{chip}</span>
                </span>
                <span className="font-serif text-base leading-[1.3] text-ink">{q.question}</span>
              </button>
            )
          })}
          {!questions.length && <p className="px-4 py-3.5 text-sm text-muted">No questions for this role.</p>}
        </div>
        {answered.length > 1 && (
          <button className="btn btn-ghost self-start px-2 py-1 text-[13px] text-rust" onClick={() => draftEvidence(answered)}>
            Turn all {answered.length} answers into evidence
          </button>
        )}
        <p className="text-xs text-pretty text-faint">
          Answer only with real experience; anything left blank or marked “no experience” stays a gap. Answers are saved to your memory,
          so similar questions pre-fill next time. Only approved evidence can be cited.
        </p>

        {knownGaps.length > 0 && (
          <div className="mt-3 flex flex-col gap-2">
            <p className={label}>Remembered gaps · not asked again</p>
            <ul className={cx(card, 'divide-y divide-rule')}>
              {knownGaps.map((g) => {
                const k = kById[g.knowledge_id]
                const qid = `${REOPENED}${g.knowledge_id}`
                const reopened = !!answers[qid]
                return (
                  <li key={g.knowledge_id} className="flex flex-col gap-1 px-4 py-3">
                    <span className="text-sm text-ink">{g.requirement}</span>
                    <span className="text-xs text-muted">You answered “no real experience”{k.company ? ` for ${k.company}` : ''} on {fmt(k.date)}.</span>
                    <button className="cursor-pointer self-start text-xs text-rust hover:text-[#63230d]"
                      onClick={() => (reopened ? select(qid) : reopen(g.requirement, g.knowledge_id))}>
                      {reopened ? 'Asked again ↑' : 'This has changed. Ask me again'}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </aside>

      {/* ------------------------------------------------------------ the selected question */}
      <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-5">
        <ErrorNote error={error} onDismiss={() => setError(null)} />

        {sel ? (
          <section key={sel.id} className="sheet animate-rise flex flex-col gap-3.5 rounded p-5 sm:p-6">
            <p className={label}>{sel.requirement}</p>
            <p className="font-serif text-2xl leading-[1.3] text-pretty text-ink">{sel.question}</p>
            {prefill && st !== 'approved' && (
              <p className="text-xs text-muted">↺ Pre-filled from your answer{prefill.company ? ` for ${prefill.company}` : ''} on {fmt(prefill.date)}. Confirm or update it.</p>
            )}

            {st === 'no_experience' && (
              <div className="flex flex-wrap items-center gap-3 rounded bg-wash px-3.5 py-3">
                <p className="min-w-0 flex-1 text-[13px] text-body">Marked as no real experience. Future analyses won’t ask about this again.</p>
                <button className="cursor-pointer text-[13px] text-rust hover:text-[#63230d]" onClick={() => update(sel, { status: 'draft' }, true)}>Undo</button>
              </div>
            )}

            {st === 'approved' && (
              <>
                {ans?.answer && <p className="border-l-2 border-rule pl-3 text-sm text-muted">{ans.answer}</p>}
                {!shown.some(({ d }) => d.question_id === sel.id) && (
                  <p className="text-sm text-ok">✓ Saved to your profile as <span className="font-mono text-xs">{ans?.evidence_id}</span></p>
                )}
              </>
            )}

            {st === 'pending' && ans?.answer && (
              <p className="border-l-2 border-rule pl-3 text-sm text-muted">Your answer: {ans.answer}</p>
            )}

            {(st === 'open' || st === 'draft') && (
              <>
                <textarea
                  aria-label={`Answer: ${sel.question}`}
                  className="field min-h-[120px] resize-y leading-normal"
                  rows={5}
                  placeholder="Describe what you actually did: where, scale, outcome. Plain words are fine."
                  value={ans?.answer ?? ''}
                  onChange={(e) => update(sel, { answer: e.target.value, status: 'draft', evidence_id: null })}
                />
                <div className="flex flex-wrap gap-2">
                  <button className="btn btn-primary" disabled={!draftable(sel)} onClick={() => draftEvidence([sel])}
                    title={draftable(sel) ? 'The AI drafts a profile entry from your answer. Nothing is saved until you approve it.' : 'Write your answer first'}>
                    Turn into evidence
                  </button>
                  <button className="btn" onClick={() => update(sel, { status: 'no_experience' }, true)}>I don’t have this experience</button>
                </div>
              </>
            )}

            {shown.length > 0 && (
              <div className="flex flex-col gap-3">
                {shown.map(({ d, i }) => (
                  <ProposalBox key={i} d={d} roles={roles} categories={categories} question={d.question_id === sel.id ? undefined : questionFor(d.question_id)}
                    onPatch={(p) => patchDraft(i, p)} onApprove={() => approve(i)} onReject={() => reject(i)} />
                ))}
              </div>
            )}
          </section>
        ) : (
          <section className="sheet animate-rise flex flex-col gap-2 rounded p-6">
            <p className={label}>Gaps</p>
            <p className="font-serif text-2xl text-ink">No new gaps to ask about</p>
            <p className="text-muted">Your profile and past answers cover every must-have. You can go straight to composing.</p>
            {/* proposals can't exist without questions, but never hide one that blocks composing */}
            {shown.map(({ d, i }) => (
              <ProposalBox key={i} d={d} roles={roles} categories={categories}
                onPatch={(p) => patchDraft(i, p)} onApprove={() => approve(i)} onReject={() => reject(i)} />
            ))}
          </section>
        )}

        <section className="flex flex-col gap-2.5 border-t border-rule pt-5">
          <label className={label} htmlFor="guidance">Guidance for the draft</label>
          <textarea id="guidance" className="field resize-y" rows={2}
            placeholder="Optional. e.g. Lead with the detection work; keep the earliest role short."
            value={guidance} onChange={(e) => setGuidance(e.target.value)}
            onBlur={() => { if (guidance !== (app.meta.guidance ?? '')) api.patch(app.id, { guidance }).then((meta) => setApp((prev) => ({ ...prev, meta }))).catch(() => {}) }} />
          <p className="text-xs text-faint">Your approved style preferences are applied automatically.</p>
          <div className="flex flex-wrap items-center justify-between gap-3">
            {pending > 0 ? (
              <span className="text-[13px] text-warn">Approve or reject the {pending} pending proposal{pending > 1 ? 's' : ''} first.</span>
            ) : (
              <span className="text-[13px] text-muted">
                {open.length ? `${open.length} question${open.length > 1 ? 's' : ''} still open. You can compose anyway.` : 'All questions handled.'}
              </span>
            )}
            <div className="flex flex-wrap gap-2">
              {app.tailored && <button className="btn btn-ghost" onClick={() => go('review')}>Back to the current draft</button>}
              <button className="btn btn-primary" onClick={compose} disabled={pending > 0}>
                {app.tailored ? 'Re-compose resume →' : 'Compose resume →'}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

/** A drafted profile entry. the user edits it until it's exactly true; only approval writes it to the profile. */
function ProposalBox({ d, roles, categories, question, onPatch, onApprove, onReject }: {
  d: Draft; roles: { id: string; employer: string }[]; categories: string[]; question?: Question
  onPatch: (p: Partial<Draft>) => void; onApprove: () => void; onReject: () => void
}) {
  const live = d.state === 'pending'
  const approved = d.state === 'approved'
  const target = d.target === 'general' ? 'General' : roles.find((r) => r.id === d.target)?.employer ?? d.target
  return (
    <div className={cx('flex flex-col gap-2 rounded border px-4 py-3.5', approved ? 'border-ok/40 bg-ok-soft/50' : 'border-rule bg-paper')}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="flex flex-wrap items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          Proposed evidence ·
          {live ? (
            <select aria-label="Belongs to" className="cursor-pointer rounded border border-rule bg-sheet px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink"
              value={d.target} onChange={(e) => onPatch({ target: e.target.value })}>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.employer}</option>)}
              <option value="general">General (not role-specific)</option>
            </select>
          ) : <span>{target}</span>}
        </p>
        {d.id && <span className="font-mono text-[11px] text-rust">{d.id}</span>}
      </div>
      {question && <p className="text-xs text-muted">For: {question.question}</p>}
      {live ? (
        <textarea aria-label="Proposed evidence wording" className="field min-h-[104px] resize-y font-serif text-base leading-[1.4]"
          value={d.text} onChange={(e) => onPatch({ text: e.target.value })} />
      ) : (
        <p className="font-serif text-base leading-[1.4] text-ink">{d.text}</p>
      )}
      {d.skills.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {d.skills.map((s, j) => (
            <span key={j} className="inline-flex items-center gap-1 rounded-[3px] bg-wash px-1.5 py-px font-mono text-[11px] text-muted">
              +
              {live ? (
                <select aria-label={`Skill group for ${s.item}`} className="cursor-pointer bg-transparent text-faint" value={s.category}
                  onChange={(e) => onPatch({ skills: d.skills.map((x, k) => (k === j ? { ...x, category: e.target.value } : x)) })}>
                  {categories.map((c) => <option key={c}>{c}</option>)}
                  {!categories.includes(s.category) && <option>{s.category}</option>}
                </select>
              ) : <span>{s.category}</span>}
              : {s.item}
              {live && (
                <button className="cursor-pointer text-faint hover:text-bad" onClick={() => onPatch({ skills: d.skills.filter((_, k) => k !== j) })} aria-label={`Drop skill ${s.item}`}>×</button>
              )}
            </span>
          ))}
        </div>
      )}
      {live && (
        <>
          <p className="text-xs text-muted">Edit the wording until it’s exactly true, then approve. Only approved items are saved, tagged as coming from you.</p>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary px-3 py-[5px] text-[13px]" disabled={!d.text.trim()} onClick={onApprove}>Approve into profile</button>
            <button className="btn px-3 py-[5px] text-[13px]" onClick={onReject}>Reject</button>
          </div>
        </>
      )}
      {approved && <p className="text-xs text-ok">✓ Added to your master profile.</p>}
    </div>
  )
}
