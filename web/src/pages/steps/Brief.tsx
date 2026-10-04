import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { cx } from '../../lib'
import type { StepProps } from '../Workspace'
import Cite from './Cite'
import { btn, btnPrimary, label, semi, sheetCard } from './v3'
import { gapQuestions, gapState, openGaps, questionFor } from './gapState'

const STATUS_DOT = { strong: 'bg-ok', partial: 'bg-warn', gap: 'bg-bad' }
const STATUS_LABEL = { strong: 'Strong', partial: 'Partial', gap: 'Gap' }

export default function Brief({ app, profile, setApp, go, run, memo, setMemo }: StepProps) {
  const nav = useNavigate()
  const [showJd, setShowJd] = useState(!app.analysis)
  const a = app.analysis

  const analyze = () => {
    if (memo.gaps?.proposals.some((d) => d.state === 'pending')
        && !window.confirm('Re-analysing replaces the gap questions and discards the evidence drafts still waiting for your approval. Continue?')) return
    return analyzeNow()
  }
  const analyzeNow = () =>
    run('Reading the job description', [
      'Identifying the industry lens and track…',
      'Matching every requirement to your evidence…',
      'Picking out ATS keywords…',
      'Drafting questions about gaps…',
    ], async () => {
      const next = await api.analyze(app.id)
      setApp(next)
      if (next.id !== app.id) nav(`/a/${next.id}`, { replace: true })
    })

  const jd = (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between">
        <p className={label}>Job description</p>
        <button className="cursor-pointer text-[13px] text-muted hover:text-ink" onClick={() => setShowJd((s) => !s)} aria-expanded={showJd}>
          {showJd ? 'Hide' : 'Show'}
        </button>
      </div>
      {showJd && (
        <pre className={`max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-rule bg-sheet px-[18px] py-4 font-sans text-[15px] leading-[1.55] text-body ${semi}`}>{app.jd}</pre>
      )}
    </section>
  )

  if (!a) {
    return (
      <div className="flex flex-col gap-7">
        <div className={`${sheetCard} animate-rise px-6 py-12 text-center sm:px-8`}>
          <p className="font-display text-[32px] leading-tight text-ink">Not analyzed yet.</p>
          <p className="mx-auto mt-1 max-w-xl text-body">AutoCV will work out the industry, the IC vs manager track, and how your evidence stacks up against each requirement.</p>
          <button className={`${btnPrimary} mt-5`} onClick={analyze}>Analyze the role</button>
        </div>
        {jd}
      </div>
    )
  }

  const answers = memo.gaps?.answers ?? Object.fromEntries(app.answers.map((x) => [x.question_id, x]))
  const drafts = memo.gaps?.proposals ?? []
  const questions = gapQuestions(a, answers)
  const open = openGaps(questions, answers, drafts).length
  const ask = (qid: string) => { setMemo((m) => ({ ...m, gapFocus: qid })); go('gaps') }

  return (
    <div className="flex flex-wrap items-start gap-7">
      <div className="flex min-w-0 flex-[1_1_600px] flex-col gap-7">
        <section className="animate-rise flex flex-col gap-2">
          <p className={label}>The brief</p>
          <p className={`text-2xl leading-[1.35] text-pretty text-ink ${semi}`}>{a.summary}</p>
        </section>

        <section className="animate-rise flex flex-col" style={{ animationDelay: '60ms' }}>
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule pb-2">
            <div>
              <p className={label}>Requirements</p>
              <h2 className="font-display text-2xl text-ink">How your evidence stacks up</h2>
            </div>
            <div className="flex gap-3.5 text-xs text-muted">
              {(['strong', 'partial', 'gap'] as const).map((s) => (
                <span key={s} className="flex items-center gap-1.5">
                  <span className={cx('size-2 rounded-full', STATUS_DOT[s])} />
                  {a.requirements.filter((r) => r.status === s).length} {s}
                </span>
              ))}
            </div>
          </div>
          {a.requirements.map((r, i) => {
            const q = r.status !== 'strong' ? questionFor(r.text, questions) : undefined
            const settled = q && ['approved', 'no_experience'].includes(gapState(answers[q.id], drafts, q.id))
            return (
              <div key={i} className="grid items-start gap-x-3.5 gap-y-1.5 border-b border-[#eef0f4] py-3 md:grid-cols-[96px_minmax(0,1.2fr)_minmax(0,1fr)]">
                <span className="flex items-center gap-2 pt-0.5 text-xs font-medium text-ink">
                  <span className={cx('size-2 rounded-full', STATUS_DOT[r.status])} />
                  {STATUS_LABEL[r.status]}
                </span>
                <div className="flex flex-col gap-0.5">
                  <p className="text-ink">
                    {r.text}
                    {r.priority === 'must' && <span className="ml-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-accent">must</span>}
                  </p>
                  {r.note && <p className="text-xs text-muted">{r.note}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  {r.evidence.map((e) => <Cite key={e} id={e} text={profile.evidence[e]} />)}
                  {q && (
                    <button className="cursor-pointer text-xs text-accent hover:text-accent-strong" onClick={() => ask(q.id)}>
                      {settled ? 'See your answer →' : 'Answer in Gaps →'}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </section>
      </div>

      <aside className="animate-rise flex min-w-0 flex-[1_1_260px] flex-col gap-5 lg:max-w-[340px] lg:flex-[0_1_320px]" style={{ animationDelay: '120ms' }}>
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-rule bg-rule">
          {[['Industry lens', a.industry], ['Track', a.track], ['Seniority', a.seniority], ['Location', a.location]].map(([k, v]) => (
            <div key={k} className="bg-sheet px-4 py-3">
              <dt className="text-[11px] uppercase tracking-[0.06em] text-muted">{k}</dt>
              <dd className="font-medium capitalize text-ink">{v || '—'}</dd>
            </div>
          ))}
        </dl>
        <section className="flex flex-col gap-2.5">
          <p className={label}>ATS keywords</p>
          <div className="flex flex-wrap gap-1.5">
            {a.keywords.map((k) => (
              <span
                key={k.term}
                title={k.aliases.length ? `also: ${k.aliases.join(', ')}` : undefined}
                className={cx('rounded-full border px-2.5 py-[3px] text-[13px]', k.priority === 'must' ? 'border-accent/40 bg-accent-soft text-accent' : 'border-rule bg-sheet text-body')}
              >
                {k.term}
              </span>
            ))}
          </div>
          <p className="text-xs text-faint">Tinted terms are must-haves.</p>
        </section>
        {jd}
      </aside>

      <div className="flex basis-full flex-wrap justify-between gap-3 border-t border-rule pt-5">
        <button className={btn} onClick={analyze}>Re-analyze</button>
        <button className={btnPrimary} onClick={() => go('gaps')}>
          {open ? `Answer ${open} gap question${open > 1 ? 's' : ''} →` : 'Continue →'}
        </button>
      </div>
    </div>
  )
}
