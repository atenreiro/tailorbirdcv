import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, STATUSES, type Application, type AppAnswer, type ProfileResponse, type Proposal, type Tailored } from '../api'
import { confirmLeave, setUnsaved } from '../unsaved'
import { changeStatus } from '../status'
import { cx, ErrorNote, fmtDate, Spinner, StatusPill, Working } from '../ui'
import Brief from './steps/Brief'
import Export from './steps/Export'
import Gaps from './steps/Gaps'
import Review from './steps/Review'

const STEPS = [
  { key: 'brief', label: 'Brief', hint: 'role analysis' },
  { key: 'gaps', label: 'Gaps', hint: 'your answers' },
  { key: 'review', label: 'Review', hint: 'claims & sources' },
  { key: 'export', label: 'Export', hint: 'docx & pdf' },
] as const
type Step = (typeof STEPS)[number]['key']

export type Draft = Proposal & { state: 'pending' | 'approved' | 'rejected'; id?: string }

/** Work in progress that must survive switching steps (each step unmounts when hidden). */
export interface StepMemo {
  review: { draft: Tailored; rev: number } | null  // unsaved Review edits
  gaps: { answers: Record<string, AppAnswer>; proposals: Draft[]; guidance: string } | null
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
  const [memo, setMemoState] = useState<StepMemo>({ review: null, gaps: null })
  const autoRan = useRef(false)

  const setMemo = useCallback((fn: (m: StepMemo) => StepMemo) => setMemoState(fn), [])

  // Unsaved Review edits guard navigation away from the workspace and closing the tab.
  useEffect(() => { setUnsaved('review', !!memo.review) }, [memo.review])
  useEffect(() => () => setUnsaved('review', false), [])

  // A new analysis renumbers the gap questions: re-seed the Gaps step from the server.
  const questionsKey = useMemo(() => JSON.stringify(app?.analysis?.questions ?? []), [app?.analysis])
  useEffect(() => { setMemoState((m) => ({ ...m, gaps: null })) }, [questionsKey])

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
    Promise.all([api.get(id), api.profile()])
      .then(([a, p]) => {
        setApp(a)
        setProfile(p)
        setStep(a.tailored ? (a.files.length ? 'export' : 'review') : a.analysis ? 'gaps' : 'brief')
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

  const enabled: Record<Step, boolean> = {
    brief: true,
    gaps: !!app.analysis,
    review: !!app.tailored,
    export: !!app.tailored,
  }

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
    <div className="space-y-8">
      <div className="animate-rise flex flex-wrap items-start justify-between gap-6">
        <div>
          <Link to="/" onClick={(e) => { if (!confirmLeave()) e.preventDefault() }} className="text-sm text-muted hover:text-rust">← Applications</Link>
          <h1 className="mt-2 font-serif text-5xl leading-none text-ink">{app.meta.company}</h1>
          <p className="mt-2 text-lg text-muted">{app.meta.role}</p>
        </div>
        <div className="flex items-center gap-3 pt-7 text-sm text-muted">
          <span>{fmtDate(app.meta.created)}</span>
          <label className="relative inline-flex">
            <StatusPill status={app.meta.status} />
            <select aria-label="Status" className="absolute inset-0 cursor-pointer opacity-0" value={app.meta.status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
        </div>
      </div>

      <ol className="animate-rise grid grid-cols-4 border-y border-rule" style={{ animationDelay: '60ms' }}>
        {STEPS.map((s, i) => (
          <li key={s.key}>
            <button
              disabled={!enabled[s.key] || !!working}
              onClick={() => setStep(s.key)}
              className={cx(
                'group flex w-full items-baseline gap-3 px-2 py-3 text-left transition disabled:cursor-not-allowed disabled:opacity-40',
                step === s.key ? 'text-ink' : 'text-muted hover:text-ink',
              )}
            >
              <span className={cx('font-serif text-2xl italic', step === s.key ? 'text-rust' : 'text-faint')}>{i + 1}</span>
              <span>
                <span className="block font-medium">
                  {s.label}
                  {s.key === 'review' && memo.review && <span className="ml-1 text-warn" title="Unsaved edits">•</span>}
                </span>
                <span className="hidden text-xs text-faint sm:block">{s.hint}</span>
              </span>
            </button>
            <div className={cx('h-0.5 transition-colors', step === s.key ? 'bg-rust' : 'bg-transparent')} />
          </li>
        ))}
      </ol>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {working ? (
        <Working title={working.title} lines={working.lines} ai={working.ai} />
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
