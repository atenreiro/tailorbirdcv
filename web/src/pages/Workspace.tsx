import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, STATUSES, type Application, type AppAnswer, type ProfileResponse, type Tailored } from '../api'
import { confirmLeave, setUnsaved } from '../unsaved'
import { changeStatus } from '../status'
import { cx, fmtDate, statusStyle, useTitle } from '../lib'
import { ErrorNote, Spinner } from '../ui'
import Brief from './steps/Brief'
import Export from './steps/Export'
import Gaps from './steps/Gaps'
import Review from './steps/Review'
import { openIssues } from './steps/critique'
import { gapQuestions, openGaps, type Draft } from './steps/gapState'

export type { Draft }

const STEPS = [
  { key: 'brief', label: 'Brief' },
  { key: 'gaps', label: 'Gaps' },
  { key: 'review', label: 'Review' },
  { key: 'export', label: 'Export' },
] as const
type Step = (typeof STEPS)[number]['key']
const isStep = (s: string | null): s is Step => STEPS.some((x) => x.key === s)

/** Work in progress that must survive switching steps (each step unmounts when hidden). */
interface StepMemo {
  review: { draft: Tailored; rev: number } | null  // unsaved Review edits
  gaps: { answers: Record<string, AppAnswer>; proposals: Draft[]; guidance: string } | null
  gapFocus: string | null  // the gap question open in Gaps (Brief and Review can point at one)
}

export interface StepProps {
  app: Application
  profile: ProfileResponse
  setApp: (a: Application | ((prev: Application) => Application)) => void
  reloadProfile: () => Promise<void>
  go: (s: Step) => void
  run: (title: string, lines: string[], fn: () => Promise<void>, ai?: boolean) => Promise<void>
  memo: StepMemo
  setMemo: (fn: (m: StepMemo) => StepMemo) => void
}

const enabledSteps = (a: Application): Record<Step, boolean> => ({
  brief: true,
  gaps: !!a.analysis,
  review: !!a.tailored,
  export: !!a.tailored,
})

type Tone = 'ok' | 'warn' | 'bad' | 'accent' | 'none'
const DOT: Record<Tone, string> = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', accent: 'bg-accent', none: 'bg-faint' }

/** One-line status under each step label, derived from the application. */
function stepNotes(app: Application, memo: StepMemo): Record<Step, [string, Tone]> {
  const a = app.analysis
  const answers = memo.gaps?.answers ?? Object.fromEntries(app.answers.map((x) => [x.question_id, x]))
  const questions = gapQuestions(a, answers)
  const open = openGaps(questions, answers, memo.gaps?.proposals ?? []).length
  const c = app.critique
  const fixes = openIssues(c).length
  const verdict = c ? { interview: 'would interview', borderline: 'borderline', pass: 'would pass' }[c.latest.verdict.decision] : ''
  const errors = app.report?.errors.length ?? 0
  const exts = app.files.map((f) => f.split('.').pop()!.toUpperCase()).sort().reverse()
  return {
    brief: a ? [`${a.requirements.length} requirement${a.requirements.length === 1 ? '' : 's'}`, 'ok'] : ['not analyzed', 'none'],
    gaps: !a ? ['after analysis', 'none'] : !questions.length ? ['none to ask', 'ok'] : open ? [`${open} open`, 'warn'] : ['answered', 'ok'],
    review: !app.tailored ? ['not drafted', 'none']
      : memo.review ? ['unsaved edits', 'warn']
      : errors ? [`${errors} to fix`, 'bad']
      : c ? [`${verdict}${fixes ? ` · ${fixes} fix${fixes > 1 ? 'es' : ''}` : ''}`, fixes ? 'accent' : 'ok']
      : ['verified', 'ok'],
    export: !app.files.length ? [app.tailored ? 'not built' : 'not yet', 'none']
      : app.outputs_stale ? ['outdated', 'warn']
      : [exts.join(' · '), 'ok'],
  }
}

export default function Workspace() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const [app, setAppState] = useState<Application | null>(null)
  const setApp = useCallback((a: Application | ((prev: Application) => Application)) =>
    setAppState((prev) => (typeof a === 'function' ? (prev ? a(prev) : prev) : a)), [])
  const [profile, setProfile] = useState<ProfileResponse | null>(null)
  const [step, setStep] = useState<Step>('brief')
  const [working, setWorking] = useState<{ title: string; lines: string[]; ai: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [memo, setMemoState] = useState<StepMemo>({ review: null, gaps: null, gapFocus: null })
  const autoRan = useRef(false)
  useTitle([app?.meta.company, app ? STEPS.find((s) => s.key === step)?.label : undefined])

  const setMemo = useCallback((fn: (m: StepMemo) => StepMemo) => setMemoState(fn), [])

  // Unsaved Review edits guard navigation away from the workspace and closing the tab.
  useEffect(() => { setUnsaved('review', !!memo.review) }, [memo.review])
  useEffect(() => () => setUnsaved('review', false), [])

  // A new analysis renumbers the gap questions: re-seed the Gaps step from the server.
  const questionsKey = useMemo(() => JSON.stringify(app?.analysis?.questions ?? []), [app?.analysis])
  useEffect(() => { setMemoState((m) => ({ ...m, gaps: null })) }, [questionsKey])

  // Each step starts at the top (the previous one may have been scrolled far down).
  const shown = working ? 'working' : step
  useEffect(() => { if (window.scrollY > 240) window.scrollTo({ top: 0 }) }, [shown])

  const reloadProfile = useCallback(async () => setProfile(await api.profile()), [])

  const run = useCallback(async (title: string, lines: string[], fn: () => Promise<void>, ai = true) => {
    setError(null)
    setWorking({ title, lines, ai })
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setWorking(null)
    }
  }, [])

  useEffect(() => {
    if (app?.id === id) return  // already loaded (e.g. after a folder rename)
    const want = params.get('step')  // e.g. /a/<id>?step=review from the Applications list
    Promise.all([api.get(id), api.profile()])
      .then(([a, p]) => {
        setApp(a)
        setProfile(p)
        setStep(isStep(want) && enabledSteps(a)[want] ? want
          : a.tailored ? (a.files.length ? 'export' : 'review') : a.analysis ? 'gaps' : 'brief')
        if (want !== null) setParams((prev) => { const next = new URLSearchParams(prev); next.delete('step'); return next }, { replace: true })
      })
      .catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // Coming from "New tailoring": analyze straight away.
  useEffect(() => {
    if (!app || app.analysis || params.get('analyze') !== '1' || autoRan.current) return
    autoRan.current = true
    setParams({}, { replace: true })
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
  }, [app, params, setParams, run, nav, setApp])

  if (!app || !profile) {
    return error ? <ErrorNote error={error} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>
  }

  const enabled = enabledSteps(app)
  const notes = stepNotes(app, memo)

  async function setStatus(status: string) {
    setError(null)
    try {
      const r = await changeStatus(app!.id, status, (on) => setWorking(on ? {
        title: 'Building & freezing the copy you send', ai: false,
        lines: ['Rendering your resume…', 'Converting to PDF through Microsoft Word…', 'Saving a read-only sent copy…'],
      } : null))
      if (!r) return
      // reload: applying freezes a sent copy, which the status response doesn't include
      setApp('app' in r ? r.app : await api.get(app!.id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const props: StepProps = { app, profile, setApp, reloadProfile, go: setStep, run, memo, setMemo }

  return (
    <div className="flex flex-col gap-6">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="flex min-w-0 flex-col gap-2">
          <Link to="/" onClick={(e) => { if (!confirmLeave()) e.preventDefault() }} className="self-start text-[13px] text-muted hover:text-accent">← Applications</Link>
          <h1 className="font-display text-[44px] leading-[0.92] tracking-[-0.02em] text-ink [overflow-wrap:anywhere] sm:text-[56px]">{app.meta.company}</h1>
          <p className="text-[17px] text-body">{app.meta.role}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-muted">Created {fmtDate(app.meta.created)}</span>
          <label className={cx('relative inline-flex cursor-pointer items-center gap-1.5 rounded-[5px] px-[9px] py-[5px] font-mono text-[11px] font-medium uppercase tracking-[0.08em]', statusStyle(app.meta.status))}>
            <span>{app.meta.status}</span><span className="text-[9px] no-underline" aria-hidden>▼</span>
            <select aria-label="Status" className="absolute inset-0 cursor-pointer opacity-0" value={app.meta.status} disabled={!!working}
              onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
        </div>
      </div>

      <ol className="animate-rise grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr))] lg:[grid-template-columns:repeat(auto-fit,minmax(190px,1fr))]" style={{ animationDelay: '60ms' }}>
        {STEPS.map((s, i) => {
          const on = step === s.key
          const [note, tone] = notes[s.key]
          return (
            <li key={s.key} className="flex min-w-0">
              <button
                disabled={!enabled[s.key] || !!working}
                onClick={() => setStep(s.key)}
                aria-current={on ? 'step' : undefined}
                className={cx('flex min-w-0 flex-1 cursor-pointer items-center gap-3.5 rounded-xl px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-40',
                  on ? 'bg-sheet shadow-[inset_0_0_0_2px_var(--color-accent)]' : 'bg-lane enabled:hover:bg-sheet')}
              >
                <span className={cx('font-mono text-[13px] font-medium', on ? 'text-accent' : 'text-faint')}>{String(i + 1).padStart(2, '0')}</span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className={cx('font-display text-lg leading-tight', on ? 'text-ink' : 'text-body')}>{s.label}</span>
                  <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
                    <span className={cx('size-1.5 shrink-0 rounded-full', DOT[tone])} aria-hidden />
                    <span className="truncate">{note}</span>
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {working ? (
        <WorkingPanel title={working.title} lines={working.lines} ai={working.ai} />
      ) : (
        <div key={step}>
          {step === 'brief' && <Brief {...props} />}
          {step === 'gaps' && <Gaps {...props} />}
          {step === 'review' && <Review {...props} />}
          {step === 'export' && <Export {...props} />}
        </div>
      )}
    </div>
  )
}

/** "The AI is working" panel with elapsed time (engine calls take a minute or two). */
function WorkingPanel({ title, lines, ai }: { title: string; lines: string[]; ai: boolean }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs((x) => x + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const line = lines[Math.min(Math.floor(secs / 12), lines.length - 1)]
  return (
    <div className="animate-rise flex flex-col items-center gap-2.5 rounded-[14px] border border-rule bg-sheet px-6 py-14 text-center sm:px-8" role="status" aria-live="polite">
      <div className="mb-3 flex w-[180px] gap-1" aria-hidden>
        {Array.from({ length: 8 }).map((_, i) => (
          <span key={i} className="h-[5px] flex-1 animate-pulse rounded-[5px] bg-accent" style={{ animationDelay: `${i * 120}ms` }} />
        ))}
      </div>
      <p className="font-display text-[32px] leading-tight tracking-[-0.01em] text-ink">{title}</p>
      <p className="text-[15px] text-body">{line}</p>
      <p className="mt-1.5 font-mono text-xs text-faint">
        {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')} elapsed{ai && ' · runs on your Claude subscription'}
      </p>
    </div>
  )
}
