import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type DoctorCheck, type TestResult } from '../api'
import { cx } from '../lib'
import { cacheSettings } from '../settings'
import { ErrorNote, Spinner } from '../ui'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'
const DOT: Record<DoctorCheck['status'], string> = { ok: 'bg-ok', warn: 'bg-[#d08a1c]', error: 'bg-bad' }
const TEXT: Record<DoctorCheck['status'], string> = { ok: 'text-ok', warn: 'text-warn', error: 'text-bad' }
const ITEM: Record<NonNullable<DoctorCheck['items']>[number]['state'], [string, string]> = {
  ready: ['Ready', 'bg-ok-soft text-ok'], missing: ['Not installed', 'bg-wash text-muted'],
  'needs-login': ['Log in', 'bg-[#f6ead2] text-warn'], 'no-key': ['No key', 'bg-wash text-muted'],
}

/** What a row's chip says: its state, worded by how much it matters (not every warning is optional). */
function chip(c: DoctorCheck): string {
  if (c.status === 'ok') return 'ready'
  return { required: 'needed', recommended: 'recommended', optional: 'optional', info: 'to do' }[c.level ?? 'required']
}

/** What TailorbirdCV needs on this computer: what's there, what's missing, and how to fix it. `phase="setup"` is the
 *  wizard's first-step list (every AI option, keychain, PDF, browser, Node); `poll` re-checks every few seconds
 *  while something that matters is missing, so an install is noticed without clicking. */
export default function SystemCheck({ bare, phase = 'all', poll, onChecks }: {
  bare?: boolean; phase?: 'all' | 'setup'; poll?: boolean; onChecks?: (checks: DoctorCheck[]) => void
}) {
  const [checks, setChecks] = useState<DoctorCheck[] | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, TestResult | 'running'>>({})
  const [browser, setBrowser] = useState<{ state: string; detail: string } | null>(null)
  const onChecksRef = useRef(onChecks)
  useEffect(() => { onChecksRef.current = onChecks }, [onChecks])
  const load = useCallback(() => api.doctor(phase)
    .then((c) => { setChecks(c); setError(null); onChecksRef.current?.(c) })
    .catch((e) => setError(e.message)).finally(() => setBusy(false)), [phase])
  useEffect(() => {
    void load()
    const again = () => { void load() }
    window.addEventListener('tailorbirdcv:settings', again)  // engine, key or PDF choice changed
    return () => window.removeEventListener('tailorbirdcv:settings', again)
  }, [load])
  const missing = checks?.filter((c) => c.status !== 'ok' && (c.level === 'required' || c.level === 'recommended')).length ?? 0
  useEffect(() => {
    if (!poll || !missing) return
    // Re-check while something that matters is missing: every 6 s at first, slowing to once a minute, and
    // stopping after ~15 minutes (Check again still works) — each check runs local programs.
    let delay = 6000, elapsed = 0, timer = 0
    const tick = () => {
      if (document.visibilityState === 'visible') void load()
      elapsed += delay
      delay = Math.min(delay * 1.5, 60000)
      if (elapsed < 15 * 60000) timer = window.setTimeout(tick, delay)
    }
    timer = window.setTimeout(tick, delay)
    return () => window.clearTimeout(timer)
  }, [poll, missing, load])
  useEffect(() => {  // a browser install in progress: follow it, then re-check
    if (browser?.state !== 'running') return
    const t = setInterval(() => api.browserStatus().then((b) => {
      setBrowser(b)
      if (b.state !== 'running') void load()
    }).catch(() => {}), 3000)
    return () => clearInterval(t)
  }, [browser?.state, load])

  const run = () => { setBusy(true); setError(null); void load() }
  const test = async (id: string, call: () => Promise<TestResult>) => {
    setResults((r) => ({ ...r, [id]: 'running' }))
    try {
      const res = await call()
      setResults((r) => ({ ...r, [id]: res }))
    } catch (e) {
      setResults((r) => ({ ...r, [id]: { ok: false, detail: (e as Error).message, seconds: 0 } }))
    }
  }
  const act = (c: DoctorCheck) => {
    const a = c.action!
    if (a.kind === 'settings') return <Link to="/settings" className="btn">{a.label}</Link>
    if (a.kind === 'install-browser') {
      const running = browser?.state === 'running'
      return (
        <button className="btn" disabled={running} onClick={() => api.installBrowser().then(setBrowser)
          .catch((e) => setBrowser({ state: 'failed', detail: (e as Error).message }))}>
          {running && <Spinner />}{running ? 'Installing…' : a.label}
        </button>
      )
    }
    const running = results[c.id] === 'running'
    return (
      <button className="btn" disabled={running} onClick={() => test(c.id, a.kind === 'test-pdf' ? api.pdfTest : api.engineTest)}>
        {running && <Spinner />}{running ? 'Testing…' : a.label}
      </button>
    )
  }

  const important = checks?.filter((c) => c.status !== 'ok' && c.level !== 'info' && c.level !== 'optional').length ?? 0
  const title = !checks ? 'Checking…' : important ? `${important} thing${important > 1 ? 's' : ''} to sort out`
    : phase === 'setup' ? 'You have what you need' : 'Everything’s ready'
  return (
    <section aria-labelledby={`doctor-title-${phase}`} className={bare ? 'flex min-w-0 flex-col gap-4' : 'animate-rise flex min-w-0 max-w-[980px] flex-col gap-4 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7'}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex max-w-[640px] flex-col gap-1.5">
          <p className={cx(label, 'text-accent', bare && 'sr-only')}>System check</p>
          <h2 id={`doctor-title-${phase}`} className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">{title}</h2>
          <p className="text-sm leading-[1.5] text-muted text-pretty">
            {phase === 'setup' ? 'What this computer already has, and what to install or set up. Rows update by themselves as you fix them.'
              : <>What TailorbirdCV needs on this computer. Same as running <code className="font-mono text-[13px]">tailorbirdcv doctor</code>.</>}
          </p>
        </div>
        <button className="btn" onClick={run} disabled={busy}>{busy && <Spinner />}Check again</button>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {checks && (
        <ul className="flex flex-col divide-y divide-line">
          {checks.map((c) => {
            const res = results[c.id]
            return (
              <li key={c.id} className="flex flex-wrap items-start gap-x-3 gap-y-2 py-3">
                <span aria-hidden className={cx('mt-[7px] size-2 flex-none rounded-full', DOT[c.status])} />
                <span className="flex min-w-0 flex-1 flex-col gap-1 text-[13px]">
                  <span className="text-ink"><span className="font-semibold">{c.label}</span>
                    <span className={cx('ml-2 font-mono text-[11px] uppercase tracking-[0.06em]', TEXT[c.status])}>{chip(c)}</span>
                    {c.status === 'ok' && c.level && c.level !== 'info' && (
                      <span className="ml-2 font-mono text-[11px] uppercase tracking-[0.06em] text-faint">{c.level}</span>
                    )}</span>
                  <span className="break-words text-muted">{c.detail}</span>
                  {c.items && (
                    <ul className="mt-1 grid gap-1.5 sm:grid-cols-2">
                      {c.items.map((i) => (
                        <li key={i.id} className="flex min-w-0 items-start gap-2 rounded-lg bg-wash px-2.5 py-1.5">
                          <span className={cx('mt-px flex-none rounded px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.06em]', ITEM[i.state][1])}>{ITEM[i.state][0]}</span>
                          <span className="min-w-0"><span className="font-semibold text-ink">{i.label}</span>
                            <span className="block break-words text-muted">{i.detail}</span></span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {c.fix && (c.status !== 'ok' || c.action) && <span className="text-body">→ {c.fix}</span>}
                  {c.id === 'browser' && browser?.state === 'failed' && <span className="text-bad">Install failed: {browser.detail}</span>}
                  {res === 'running' && c.action?.hint && <span className="text-body">{c.action.hint}</span>}
                  {res && res !== 'running' && (
                    <span role="status" className={res.ok ? 'text-ok' : 'text-bad'}>
                      {res.ok ? '✓ ' : '✗ '}{res.detail}{res.ok && res.seconds ? ` (${res.seconds} s)` : ''}
                    </span>
                  )}
                  {res && res !== 'running' && !res.ok && res.alternative && (
                    <button className="btn self-start" onClick={() => api.saveSettings({ pdf_engine: res.alternative as 'word' | 'libreoffice' })
                      .then((next) => { cacheSettings(next); setResults((r) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== c.id))); void load() })
                      .catch((e) => setError((e as Error).message))}>
                      Use {res.alternative === 'libreoffice' ? 'LibreOffice' : 'Word'} instead
                    </button>
                  )}
                </span>
                {c.action && <span className="flex-none">{act(c)}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
