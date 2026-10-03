import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type EngineStatus, type SetupState, type SetupStep, type Settings, type Targets } from '../../api'
import { cx, useTitle } from '../../lib'
import { cacheSettings, loadSettings } from '../../settings'
import { markSetupDone } from '../../setup'
import { ErrorNote, Spinner } from '../../ui'
import { AIEngine, ResumeDesign, SystemCheck, YourTargets } from '../Settings'
import ReviewProfile from './ReviewProfile'
import UploadCv from './UploadCv'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'
const STEPS: [SetupStep, string][] = [['welcome', 'Welcome'], ['connect', 'Connect Claude'], ['upload', 'Your CV'],
  ['review', 'Review'], ['targets', 'Your targets'], ['design', 'Design'], ['checks', 'Final checks']]
const PROFILE_STEPS: SetupStep[] = ['upload', 'review']

function Panel({ eyebrow, title, intro, children, footer }: {
  eyebrow: string; title: string; intro?: ReactNode; children?: ReactNode; footer?: ReactNode
}) {
  return (
    <section aria-labelledby="step-title" className="animate-rise flex flex-col gap-5">
      <div className="flex max-w-[760px] flex-col gap-2">
        <p className={cx(label, 'text-accent')}>{eyebrow}</p>
        <h1 id="step-title" tabIndex={-1} className="font-display text-[40px] leading-[0.95] tracking-[-0.02em] text-ink outline-none sm:text-[52px]">{title}</h1>
        {intro && <p className="text-[15px] leading-[1.55] text-body text-pretty">{intro}</p>}
      </div>
      {children}
      {footer && <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">{footer}</div>}
    </section>
  )
}

/** Step 1: the AI engine must answer before the CV can be read. Polls while waiting for a login. */
function ConnectClaude({ settings, onSettings, onNext, onBlank }: {
  settings: Settings; onSettings: (s: Settings) => void; onNext: () => void; onBlank: () => void
}) {
  const [status, setStatus] = useState<EngineStatus | null>(null)
  const check = useCallback(() => api.engine().then(setStatus).catch(() => setStatus(null)), [])
  useEffect(() => {
    void check()
    const t = setInterval(() => { if (document.visibilityState === 'visible') void check() }, 4000)
    return () => clearInterval(t)
  }, [check, settings.ai_engine, settings.api_key.configured])
  const ready = !!status?.ready
  const cli = settings.ai_engine === 'claude-cli'
  return (
    <Panel eyebrow="Connect Claude" title="Connect Claude"
      intro="AutoCV uses Claude to read your CV and to tailor it for each job. Use your Claude subscription through Claude Code, or an Anthropic API key."
      footer={<>
        <button className="btn btn-primary" onClick={onNext} disabled={!ready}>Continue</button>
        <button className="text-[13px] text-muted hover:text-ink" onClick={onBlank}>Set this up later and start with a blank profile</button>
      </>}>
      <div role="status" className={cx('flex items-start gap-3 rounded-xl px-4 py-3 text-[14px]', ready ? 'bg-ok-soft text-ok' : 'bg-wash text-body')}>
        {status === null ? <Spinner className="mt-1" /> : <span aria-hidden className={cx('mt-[7px] size-2 flex-none rounded-full', ready ? 'bg-ok' : 'bg-[#d08a1c]')} />}
        <span>{status === null ? 'Checking…' : ready ? `Connected — ${status.detail}.` : status.detail}</span>
      </div>
      {cli && !ready && status && (
        <ol className="flex max-w-[760px] list-decimal flex-col gap-1.5 pl-5 text-[14px] text-body">
          <li><a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noreferrer" className="text-accent hover:text-accent-strong">Install Claude Code</a> (it needs a Claude Pro or Max subscription).</li>
          <li>Open a terminal and run <code className="rounded bg-wash px-1.5 font-mono text-[13px]">claude</code>, then type <code className="rounded bg-wash px-1.5 font-mono text-[13px]">/login</code> and finish in your browser.</li>
          <li>Come back here: this page notices by itself within a few seconds.</li>
        </ol>
      )}
      <AIEngine settings={settings} onSaved={(s) => { onSettings(s); void check() }} bare />
    </Panel>
  )
}

function StartBlank({ onCreated, onBack }: { onCreated: () => void; onBack: () => void }) {
  const [form, setForm] = useState({ name: '', headline: '', location: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.createProfile({ blank: form })
      onCreated()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  return (
    <Panel eyebrow="Start blank" title="Start with a blank profile"
      intro="Add the basics now; you’ll type in your roles and achievements under Master profile afterwards."
      footer={<>
        <button className="btn btn-primary" disabled={!form.name.trim() || !form.headline.trim() || busy} onClick={create}>{busy && <Spinner />}Create my profile</button>
        <button className="btn" onClick={onBack} disabled={busy}>Back</button>
      </>}>
      <div className="grid max-w-[760px] gap-4 sm:grid-cols-2">
        {([['name', 'Your name', 120], ['headline', 'Headline (e.g. your current title)', 240], ['location', 'Location', 120]] as const).map(([k, text, max]) => (
          <label key={k} className={cx('flex flex-col gap-1.5', k === 'headline' && 'sm:col-span-2')}>
            <span className="text-[13px] font-semibold text-ink">{text}</span>
            <input className="field" value={form[k]} maxLength={max} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
          </label>
        ))}
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
    </Panel>
  )
}

/** Step 6: what's still missing on this computer, with the optional headless browser installable here. */
function FinalChecks({ onFinish, busy }: { onFinish: () => void; busy: boolean }) {
  const [browser, setBrowser] = useState<{ state: string; detail: string } | null>(null)
  useEffect(() => {
    let live = true
    const poll = () => api.browserStatus().then((b) => { if (live) setBrowser(b) }).catch(() => {})
    void poll()
    const t = setInterval(() => { if (browser?.state === 'running') void poll() }, 3000)
    return () => { live = false; clearInterval(t) }
  }, [browser?.state])
  return (
    <Panel eyebrow="Final checks" title="Almost done"
      intro="AutoCV checked what it needs on this computer. Anything marked “needs attention” has a fix next to it; you can also come back to this under Settings."
      footer={<button className="btn btn-primary" onClick={onFinish} disabled={busy}>{busy && <Spinner />}Finish setup</button>}>
      <SystemCheck key={browser?.state === 'done' ? 'browser-installed' : 'checks'} bare />
      {browser && browser.state !== 'done' && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl bg-wash px-4 py-3 text-[13px] text-body">
          <span className="flex-1">Optional: a headless browser lets AutoCV read job pages that only load with JavaScript (about 100 MB).
            {browser.state === 'failed' && <span className="block text-bad">Install failed: {browser.detail}</span>}</span>
          <button className="btn" disabled={browser.state === 'running'}
            onClick={() => api.installBrowser().then(setBrowser).catch((e) => setBrowser({ state: 'failed', detail: (e as Error).message }))}>
            {browser.state === 'running' && <Spinner />}{browser.state === 'running' ? 'Installing…' : 'Install'}</button>
        </div>
      )}
    </Panel>
  )
}

const looksNorthAmerican = (region: string) => /\b(us|usa|united states|america|canada|ca|new york|san francisco|toronto|vancouver|seattle|boston|chicago|texas|california)\b/i.test(region)

export default function SetupWizard() {
  useTitle(['Setup'])
  const nav = useNavigate()
  const [setup, setSetup] = useState<SetupState | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [step, setStep] = useState<SetupStep>('welcome')
  const [blank, setBlank] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [finishing, setFinishing] = useState(false)

  useEffect(() => {
    Promise.all([api.setup(), loadSettings(true)]).then(([s, st]) => {
      setSetup(s)
      setSettings(st)
      // Someone with a profile (re-running setup) starts at their targets.
      setStep(s.has_profile && (PROFILE_STEPS.includes(s.step) || s.completed || s.step === 'welcome') ? 'targets' : s.step)
    }).catch((e) => setError(e.message))
  }, [])
  useEffect(() => { document.getElementById('step-title')?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }) }, [step, blank])

  const go = (next: SetupStep) => {
    setBlank(false)
    setStep(next)
    api.setupStep(next).then(setSetup).catch(() => {})
  }
  const onSettings = (s: Settings) => { cacheSettings(s); setSettings(s) }
  const refresh = () => api.setup().then(setSetup)
  const finish = async () => {
    setFinishing(true)
    try {
      await api.finishSetup()
      markSetupDone()
      nav('/?welcome=1')
    } catch (e) {
      setError((e as Error).message)
      setFinishing(false)
    }
  }

  if (!setup || !settings) {
    return <div className="py-20 text-center text-muted">{error ? <ErrorNote error={error} /> : <span className="inline-flex items-center gap-2"><Spinner /> Loading…</span>}</div>
  }
  const at = STEPS.findIndex(([k]) => k === step)
  const reachable = (k: SetupStep, i: number) => i <= at && !(setup.has_profile && PROFILE_STEPS.includes(k))

  const suggested = (): Targets => {
    const t = settings.targets, s = setup.suggested_targets ?? {}
    const empty = !t.field && !t.seniority && !t.roles && !t.region
    const pages = setup.pages && setup.pages >= 1 && setup.pages <= 3 ? setup.pages as 1 | 2 | 3 : t.pages
    return empty ? { ...t, field: s.field ?? '', seniority: s.seniority ?? '', roles: s.roles ?? '', region: s.region ?? '',
      spelling: (s.spelling as 'US' | 'UK') ?? t.spelling, pages, pack: s.pack ?? t.pack } : t
  }

  let body: ReactNode
  if (blank) {
    body = <StartBlank onBack={() => setBlank(false)} onCreated={() => { void refresh(); go('targets') }} />
  } else if (step === 'welcome') {
    body = (
      <Panel eyebrow="Welcome" title="Let’s set up AutoCV"
        intro={<>AutoCV tailors your resume to each job you apply for, <strong>without inventing anything</strong>: every line it writes comes from your own CV.</>}
        footer={<><button className="btn btn-primary" onClick={() => go('connect')}>Get started</button><span className="text-[13px] text-muted">About 5 minutes</span></>}>
        <ol className="grid max-w-[900px] gap-3 sm:grid-cols-3">
          {[['1', 'Your CV becomes a master profile', 'Upload it once; you check what was read.'],
            ['2', 'Paste a job description', 'AutoCV finds the requirements and asks about gaps.'],
            ['3', 'Get a tailored resume', 'Rephrased and reordered from your facts, fact-checked, as Word and PDF.']].map(([n, t, d]) => (
            <li key={n} className="flex flex-col gap-1.5 rounded-xl bg-lane px-4 py-4">
              <span className="font-mono text-xs font-medium text-accent">0{n}</span>
              <span className="font-display text-lg leading-tight text-ink">{t}</span>
              <span className="text-[13px] leading-[1.45] text-body">{d}</span>
            </li>
          ))}
        </ol>
        <p className="max-w-[760px] text-[13px] text-muted">Your profile and applications stay on this computer. Only what the AI needs to read or write your resume is sent to Claude.</p>
      </Panel>
    )
  } else if (step === 'connect') {
    body = <ConnectClaude settings={settings} onSettings={onSettings} onNext={() => go(setup.has_profile ? 'targets' : 'upload')} onBlank={() => setBlank(true)} />
  } else if (step === 'upload' || (step === 'review' && !setup.draft)) {
    body = (
      <Panel eyebrow="Your CV" title="Upload your CV"
        intro="Your current CV, in any layout. AutoCV reads it once to build your master profile: the facts every tailored resume is made from.">
        <UploadCv onBlank={() => setBlank(true)} onImported={(draft) => { setSetup((s) => s && { ...s, draft }); void refresh(); setStep('review') }} />
      </Panel>
    )
  } else if (step === 'review') {
    body = (
      <Panel eyebrow="Review" title="Is this your CV?"
        intro="Check what was read. Nothing is saved until you click Save my profile.">
        <ReviewProfile draft={setup.draft!} onSaved={() => { void refresh(); go('targets') }}
          onRestart={() => api.discardDraft().then((s) => { setSetup(s); go('upload') })} />
      </Panel>
    )
  } else if (step === 'targets') {
    body = (
      <Panel eyebrow="Your targets" title="What are you aiming for?"
        intro={<>{setup.suggested_targets && !settings.targets.field ? 'Suggested from your CV — edit freely. ' : ''}These steer what the AI emphasises and which words it uses. They never add facts.</>}>
        <YourTargets settings={settings} initial={suggested()} onSaved={onSettings} onContinue={async () => {
          const st = await loadSettings(true)
          if (st.paper === null) onSettings(await api.saveSettings({ paper: looksNorthAmerican(st.targets.region) ? 'letter' : 'a4' }))
          go('design')
        }} />
      </Panel>
    )
  } else if (step === 'design') {
    body = (
      <Panel eyebrow="Design" title="Pick a look"
        intro="How your resumes will look. You can change it any time under Settings."
        footer={<><button className="btn btn-primary" onClick={() => go('checks')}>Continue</button><button className="btn" onClick={() => go('targets')}>Back</button></>}>
        <ResumeDesign settings={settings} onSaved={onSettings} bare />
      </Panel>
    )
  } else {
    body = <FinalChecks onFinish={finish} busy={finishing} />
  }

  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-8">
      <nav aria-label="Setup steps" className="flex flex-col gap-3">
        <div className="h-1.5 overflow-hidden rounded-full bg-lane sm:hidden" aria-hidden>
          <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${((at + 1) / STEPS.length) * 100}%` }} />
        </div>
        <p className="font-mono text-xs text-muted sm:hidden">Step {at + 1} of {STEPS.length} · {STEPS[at][1]}</p>
        <ol className="hidden flex-wrap gap-1.5 sm:flex">
          {STEPS.map(([k, name], i) => {
            const done = i < at || (setup.has_profile && PROFILE_STEPS.includes(k))
            return (
              <li key={k}>
                <button disabled={!reachable(k, i) || i === at} onClick={() => go(k)} aria-current={i === at ? 'step' : undefined}
                  className={cx('flex h-8 items-center gap-2 rounded-full px-3 text-[13px] font-medium transition-colors',
                    i === at ? 'bg-ink text-white' : done ? 'bg-accent-soft text-accent enabled:hover:bg-[#dbe1fb]' : 'bg-lane text-faint')}>
                  <span className="font-mono text-[11px]">{done && i !== at ? '✓' : i + 1}</span>{name}
                </button>
              </li>
            )
          })}
        </ol>
      </nav>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {body}
      {setup.completed && <p className="text-[13px] text-muted"><Link to="/" className="text-accent hover:text-accent-strong">Leave setup</Link> — your changes so far are saved.</p>}
    </div>
  )
}
