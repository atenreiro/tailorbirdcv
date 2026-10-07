import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, isLetterFile, type Application, type AppAnswer, type CoverLetter, type FillProposal, type Outcome, type ProfileResponse,
  type Proposal, type Tailored, type TaskKind, type TaskView, type TrimProposal } from '../api'
import { NO_GUARD, setUnsaved } from '../unsaved'
import { changeStatus, sentAsApplied } from '../status'
import { cx, fmtDate, useTitle } from '../lib'
import { engineRuns, useSettings } from '../settings'
import { ErrorNote, Spinner, StatusSelect, Stitching } from '../ui'
import Brief from './steps/Brief'
import CoverLetterStep from './steps/CoverLetter'
import Export from './steps/Export'
import Gaps from './steps/Gaps'
import Review from './steps/Review'
import { openIssues } from './steps/critique'
import { gapQuestions, openGaps, type Draft } from './steps/gapState'
import { pageKey, renamed } from './renamed'
import { FILL_NOTHING, TRIM_NOTHING, withFill, withProposals, withTrim } from './steps/taskResults'

const STEPS = [
  { key: 'brief', label: 'Brief' },
  { key: 'gaps', label: 'Gaps' },
  { key: 'review', label: 'Review' },
  { key: 'letter', label: 'Cover letter' },
  { key: 'export', label: 'Export' },
] as const
type Step = (typeof STEPS)[number]['key']
const isStep = (s: string | null): s is Step => STEPS.some((x) => x.key === s)

/** Work in progress that must survive switching steps (each step unmounts when hidden). */
export interface StepMemo {
  // Unsaved Review edits; `notice` explains where they came from (e.g. an AI trim proposal).
  review: { draft: Tailored; rev: number; notice?: string } | null
  gaps: { answers: Record<string, AppAnswer>; proposals: Draft[]; guidance: string } | null
  gapFocus: string | null  // the gap question open in Gaps (Brief and Review can point at one)
  letter: { draft: CoverLetter; rev: number } | null  // unsaved cover-letter edits
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
  /** Show an error on the application page, e.g. from a step that has already closed. */
  report: (message: string) => void
}

/** What the "working" panel says when this page picks up an AI step that's already running. */
const TASK_LINES: Record<TaskKind, string[]> = {
  analyze: ['Identifying the industry lens and track…', 'Matching every requirement to your evidence…', 'Picking out ATS keywords…',
    'Drafting questions about gaps…'],
  proposals: ['Turning your answer into a profile entry…', 'Checking it against your existing evidence…'],
  compose: ['Choosing the headline and leading highlights…', 'Reordering evidence by relevance to this role…',
    'Rephrasing in the job’s vocabulary — facts locked…', 'Running the fact-check and repairing any issues…'],
  trim: ['Dropping the least relevant bullets, oldest roles first…', 'Re-running the fact-check…'],
  fill: ['Finding relevant evidence the resume doesn’t use yet…', 'Re-running the fact-check…'],
  critique: ['Reading it as the hiring manager for this role…', 'Skimming the top third like a recruiter…',
    'Writing specific fixes and fact-checking each one…'],
  letter: ['Choosing the evidence that fits this role…', 'Reading what the posting says about the company…',
    'Checking every sentence against your profile…'],
}
/** Where a finished AI step's result is shown. */
const TASK_STEP: Record<TaskKind, Step> = {
  analyze: 'brief', proposals: 'gaps', compose: 'review', trim: 'review', fill: 'review', critique: 'review', letter: 'letter',
}

/** One page per application (see renamed.ts): a rename keeps the page, another application gets a new one. */
export function WorkspacePage() {
  const { id = '' } = useParams()
  return <Workspace key={pageKey(id)} />
}

const enabledSteps = (a: Application): Record<Step, boolean> => ({
  brief: true,
  gaps: !!a.analysis,
  review: !!a.tailored,
  letter: !!a.tailored && !!a.report?.ok,
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
  const resumeFiles = app.files.filter((f) => !isLetterFile(f))
  const exts = resumeFiles.map((f) => f.split('.').pop()!.toUpperCase()).sort().reverse()
  const letterErrors = app.letter_report?.errors.length ?? 0
  const letterBuilt = app.files.some(isLetterFile)
  return {
    brief: a ? [`${a.requirements.length} requirement${a.requirements.length === 1 ? '' : 's'}`, 'ok'] : ['not analyzed', 'none'],
    gaps: !a ? ['after analysis', 'none'] : !questions.length ? ['none to ask', 'ok'] : open ? [`${open} open`, 'warn'] : ['answered', 'ok'],
    review: !app.tailored ? ['not drafted', 'none']
      : memo.review ? ['unsaved edits', 'warn']
      : errors ? [`${errors} to fix`, 'bad']
      : c ? [`${verdict}${fixes ? ` · ${fixes} fix${fixes > 1 ? 'es' : ''}` : ''}`, fixes ? 'accent' : 'ok']
      : ['verified', 'ok'],
    letter: !app.letter ? [app.report?.ok ? 'not written' : 'after review', 'none']
      : memo.letter ? ['unsaved edits', 'warn']
      : letterErrors ? [`${letterErrors} to fix`, 'bad']
      : !letterBuilt ? ['draft · not built', 'accent']
      : app.letter_stale ? ['outdated', 'warn'] : ['built', 'ok'],
    export: !resumeFiles.length ? [app.tailored ? 'not built' : 'not yet', 'none']
      : app.outputs_stale ? ['outdated', 'warn']
      : [exts.join(' · '), 'ok'],
  }
}

function Workspace() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const [app, setAppState] = useState<Application | null>(null)
  const setApp = useCallback((a: Application | ((prev: Application) => Application)) =>
    setAppState((prev) => (typeof a === 'function' ? (prev ? a(prev) : prev) : a)), [])
  const [profile, setProfile] = useState<ProfileResponse | null>(null)
  const [step, setStep] = useState<Step>('brief')
  const [working, setWorking] = useState<Working | null>(null)
  const [following, setFollowing] = useState(false)  // checking on an AI step started before this page opened
  const [arrived, setArrived] = useState<Application | null>(null)  // an application whose AI step just finished
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
  const appId = useRef<string | null>(null)
  appId.current = app?.id ?? null
  const [error, setError] = useState<string | null>(null)
  const [memo, setMemoState] = useState<StepMemo>({ review: null, gaps: null, gapFocus: null, letter: null })
  const autoRan = useRef(false)
  useTitle([app?.meta.company, app ? STEPS.find((s) => s.key === step)?.label : undefined])

  const setMemo = useCallback((fn: (m: StepMemo) => StepMemo) => setMemoState(fn), [])

  // Unsaved Review edits, and AI evidence proposals awaiting approval (or being reworded), guard
  // navigation away from the workspace and closing the tab: both live only in this page's memory.
  const pendingProposals = !!memo.gaps?.proposals.some((d) => d.state === 'pending')
  useEffect(() => { setUnsaved('review', !!memo.review) }, [memo.review])
  useEffect(() => { setUnsaved('letter', !!memo.letter) }, [memo.letter])
  useEffect(() => { setUnsaved('proposals', pendingProposals) }, [pendingProposals])
  useEffect(() => () => { setUnsaved('review', false); setUnsaved('proposals', false); setUnsaved('letter', false) }, [])

  // A new analysis renumbers the gap questions: re-seed the Gaps step from the server.
  const questionsKey = useMemo(() => JSON.stringify(app?.analysis?.questions ?? []), [app?.analysis])
  useEffect(() => { setMemoState((m) => ({ ...m, gaps: null })) }, [questionsKey])

  // An AI step finished while this page wasn't showing it: show its outcome, then let the server forget it.
  useEffect(() => {
    if (!arrived) return
    setArrived(null)
    const a = arrived
    const t = a.task
    if (appId.current && a.id !== appId.current) {  // the analysis renamed it
      renamed(appId.current, a.id)
      nav(`/a/${a.id}`, { replace: true, state: NO_GUARD })
    }
    setApp(a)
    if (t?.status === 'failed') setError(t.error || 'The AI step failed.')
    else if (t?.status === 'done') {
      const r = (t.result ?? {}) as { trim_proposal?: TrimProposal | null; fill_proposal?: FillProposal | null }
      if (t.kind === 'trim' && !r.trim_proposal) setError(TRIM_NOTHING)
      else if (t.kind === 'fill' && !r.fill_proposal) setError(FILL_NOTHING)
      else {
        if (t.kind === 'trim') setMemoState((m) => withTrim(m, r.trim_proposal!, a))
        if (t.kind === 'fill') setMemoState((m) => withFill(m, r.fill_proposal!))
        if (t.kind === 'proposals') setMemoState((m) => withProposals(m, a, (t.result as Proposal[] | undefined) ?? []))
        if (enabledSteps(a)[TASK_STEP[t.kind]]) setStep(TASK_STEP[t.kind])
      }
    }
    if (t && t.status !== 'running') void api.clearTask(a.id).catch(() => {})
  }, [arrived, nav, setApp])

  // Each step starts at the top (the previous one may have been scrolled far down).
  const shown = working ? 'working' : step
  useEffect(() => { if (window.scrollY > 240) window.scrollTo({ top: 0 }) }, [shown])

  const reloadProfile = useCallback(async () => setProfile(await api.profile()), [])

  // An AI step that was already running (started before you came back, or from another tab): show it
  // working, check on it every few seconds, and show its outcome when it's done.
  const follow = useCallback((task: TaskView) => {
    setWorking({ title: task.label, lines: TASK_LINES[task.kind] ?? [], ai: true, started: Date.parse(task.started), stoppable: true })
    setFollowing(true)
    window.dispatchEvent(new Event('tailorbirdcv:tasks'))
  }, [])
  useEffect(() => {
    if (!following) return
    const timer = window.setInterval(async () => {
      try {
        const a = await api.get(appId.current!)
        if (a.task?.status === 'running') return
        setFollowing(false)
        setWorking(null)
        setArrived(a)
      } catch { /* the server may be busy or restarting: try again */ }
    }, 2500)
    return () => window.clearInterval(timer)
  }, [following])

  const run = useCallback(async (title: string, lines: string[], fn: () => Promise<void>, ai = true) => {
    setError(null)
    setWorking({ title, lines, ai, started: Date.now(), stoppable: ai })
    if (ai) window.dispatchEvent(new Event('tailorbirdcv:tasks'))
    let followed = false
    try {
      await fn()
    } catch (e) {
      const err = e as ApiError
      if (err.code === 'stopped') { /* you pressed Stop: nothing was changed */ }
      else if (err.code === 'running' && err.detail?.task && mounted.current) { followed = true; follow(err.detail.task as TaskView) }
      else setError(err.message)
    } finally {
      // Still on this page: its outcome has been shown, so the server can forget the finished step. If you
      // left, it's kept, and the page shows it when you come back.
      if (!followed && mounted.current) {
        setWorking(null)
        if (ai && appId.current) void api.clearTask(appId.current).catch(() => {})
      }
    }
  }, [follow])

  const stop = useCallback(async () => {
    if (!window.confirm('Stop this AI step? What it has done so far is discarded; nothing is changed.')) return
    setWorking((w) => (w ? { ...w, stopping: true } : w))
    try {
      await api.stopTask(appId.current!)
    } catch (e) {
      setError((e as Error).message)
      setWorking((w) => (w ? { ...w, stopping: false } : w))
    }
  }, [])

  useEffect(() => {
    if (app?.id === id) return  // already loaded (e.g. after a folder rename)
    if (app) setMemoState({ review: null, gaps: null, gapFocus: null, letter: null })  // another application: drop the old one's work
    const want = params.get('step')  // e.g. /a/<id>?step=review from the Applications list
    let current = true  // a quick switch to another application: this (slower) answer must not win
    Promise.all([api.get(id), api.profile()])
      .then(([a, p]) => {
        if (!current) return
        setApp(a)
        setProfile(p)
        setStep(isStep(want) && enabledSteps(a)[want] ? want
          : a.tailored ? (a.files.length ? 'export' : 'review') : a.analysis ? 'gaps' : 'brief')
        if (want !== null) setParams((prev) => { const next = new URLSearchParams(prev); next.delete('step'); return next }, { replace: true })
        if (a.task?.status === 'running') follow(a.task)
        else if (a.task) setArrived(a)  // it finished while you were elsewhere
      })
      .catch((e) => { if (current) setError(e.message) })
    return () => { current = false }
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
      if (next.id !== app.id) { renamed(app.id, next.id); nav(`/a/${next.id}`, { replace: true, state: NO_GUARD }) }
    })
  }, [app, params, setParams, run, nav, setApp])

  if (!app || !profile) {
    return error ? <ErrorNote error={error} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>
  }

  const enabled = enabledSteps(app)
  const notes = stepNotes(app, memo)

  async function setStatus(status: string, outcome?: Outcome) {
    const alreadySent = sentAsApplied(app!.sent)
    if (status === 'applied' && memo.review && !alreadySent && !window.confirm(
      'You have unsaved Review edits. Marking this applied freezes the last saved version as the copy you sent, without these edits.\n\n'
      + 'Cancel, then Save & check in Review (and rebuild) to send the edited version. Mark applied anyway?')) return
    setError(null)
    try {
      const r = await changeStatus(app!.id, status, { alreadySent, outcome, onBuilding: (on) => setWorking(on ? {
        title: 'Building & freezing the copy you send', ai: false, started: Date.now(),
        lines: ['Rendering your resume…', 'Converting to PDF…', 'Saving a read-only sent copy…'],
      } : null) })
      if (!r) return
      // reload: applying freezes a sent copy, which the status response doesn't include
      setApp('app' in r ? r.app : await api.get(app!.id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const props: StepProps = { app, profile, setApp, reloadProfile, go: setStep, run, memo, setMemo, report: setError }
  // The posting the description came from (only http/https links are shown).
  const postingUrl = /^https?:\/\//i.test(app.meta.url ?? '') ? app.meta.url! : null
  const postingHost = postingUrl ? (() => { try { return new URL(postingUrl).host.replace(/^www\./, '') } catch { return '' } })() : ''


  return (
    <div className="flex flex-col gap-6">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="flex min-w-0 flex-col gap-2">
          <Link to="/" className="self-start text-[13px] text-muted hover:text-accent">← Applications</Link>
          <h1 className="font-display text-[44px] leading-[0.92] tracking-[-0.02em] text-ink [overflow-wrap:anywhere] sm:text-[56px]">{app.meta.company}</h1>
          <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[17px] text-body">
            <span>{app.meta.role}</span>
            {postingUrl && (
              <a href={postingUrl} target="_blank" rel="noopener noreferrer" title={`Open the original job posting: ${postingUrl}`}
                className="inline-flex items-baseline gap-1 text-sm text-accent hover:text-accent-strong hover:underline">
                Job posting <span className="font-mono text-xs text-muted">{postingHost}</span> <span aria-hidden>↗</span>
              </a>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-muted">Created {fmtDate(app.meta.created)}</span>
          <StatusSelect label="Status" status={app.meta.status} outcome={app.meta.outcome} disabled={!!working}
            onChange={(s, o) => void setStatus(s, o)} />
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
        <WorkingPanel working={working} onStop={working.stoppable ? stop : undefined} />
      ) : (
        <div key={step}>
          {step === 'brief' && <Brief {...props} />}
          {step === 'gaps' && <Gaps {...props} />}
          {step === 'review' && <Review {...props} />}
          {step === 'letter' && <CoverLetterStep {...props} />}
          {step === 'export' && <Export {...props} />}
        </div>
      )}
    </div>
  )
}

interface Working {
  title: string; lines: string[]; ai: boolean
  started: number  // when the step began (ms), also when it began before this page opened
  stoppable?: boolean; stopping?: boolean
}

/** "The AI is working" panel with elapsed time (engine calls take a minute or two). You can leave the page
 *  meanwhile: the step keeps going, and its result is here when you come back. */
function WorkingPanel({ working, onStop }: { working: Working; onStop?: () => void }) {
  const { title, lines, ai, started, stopping } = working
  const runs = engineRuns(useSettings())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const secs = Math.max(0, Math.floor((now - started) / 1000))
  const line = lines[Math.min(Math.floor(secs / 12), lines.length - 1)]
  return (
    <div className="animate-rise flex flex-col items-center gap-2.5 rounded-[14px] border border-rule bg-sheet px-6 py-12 text-center sm:px-8">
      <Stitching mode={ai ? 'ai' : 'build'} className="mb-1" />
      <div role="status" aria-live="polite" className="flex flex-col items-center gap-2.5">
        <p className="font-display text-[32px] leading-tight tracking-[-0.01em] text-ink">{stopping ? 'Stopping…' : title}</p>
        <p className="text-[15px] text-body">{stopping ? 'Ending the AI step. Nothing is changed.' : line}</p>
      </div>
      <p className="mt-1.5 font-mono text-xs text-muted" aria-hidden="true">
        {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')} elapsed{ai && runs && ` · ${runs}`}
      </p>
      {onStop && (
        <>
          <p className="max-w-[460px] text-[13px] text-muted text-pretty">
            You can leave this page: the AI keeps working, and the result is waiting here when you come back.
          </p>
          <button className="btn mt-1 px-4 py-1.5 text-[13px]" onClick={onStop} disabled={stopping}>
            {stopping ? 'Stopping…' : 'Stop'}
          </button>
        </>
      )}
    </div>
  )
}
