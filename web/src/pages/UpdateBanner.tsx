import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { api, type UpdateStatus } from '../api'
import { Spinner } from '../ui'

const DISMISS_KEY = 'tailorbirdcv:update-dismissed'  // the version (or upgrade outcome) "Later"/"Dismiss" hid
const POLL_MS = 2000
const GIVE_UP_MS = 180_000

function readDismissed() {
  try { return localStorage.getItem(DISMISS_KEY) } catch { return null }
}
function writeDismissed(value: string) {
  try { localStorage.setItem(DISMISS_KEY, value) } catch { /* private window: it shows again next time */ }
}

const banner = 'animate-rise mb-6 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-3 text-[14px] text-ink'
const quiet = 'text-[13px] text-muted hover:text-ink'

function Command({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <span className="inline-flex max-w-full items-center gap-2">
      <code className="max-w-full overflow-x-auto whitespace-nowrap rounded bg-wash px-1.5 py-0.5 font-mono text-[12.5px]">{text}</code>
      <button className={quiet} onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true)).catch(() => {})}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  )
}

/** "A newer TailorbirdCV is out": Upgrade (one-line-installer copies) or the command to run, plus the restart itself
 * and its outcome. Shown on every page; checks happen on the server (PyPI, at most daily, off in Settings). */
export default function UpdateBanner() {
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [dismissed, setDismissed] = useState(readDismissed)
  const [phase, setPhase] = useState<'idle' | 'confirm' | 'upgrading' | 'stuck'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState<string | null>(null)

  useEffect(() => {
    const load = () => { api.updateStatus().then(setStatus).catch(() => {}) }
    load()
    window.addEventListener('tailorbirdcv:update', load)  // Settings → About TailorbirdCV changed something
    return () => window.removeEventListener('tailorbirdcv:update', load)
  }, [])

  useEffect(() => {
    if (phase !== 'upgrading') return
    const started = Date.now()
    const timer = window.setInterval(() => {
      if (Date.now() - started > GIVE_UP_MS) { setPhase('stuck'); return }
      api.updateStatus().then((s) => {
        if (s.current === target) window.location.reload()  // the new version answers
        else if (s.last_upgrade && !s.last_upgrade.ok) { setStatus(s); setPhase('idle') }  // restarted on the old one
      }).catch(() => { /* restarting: the server is briefly unreachable */ })
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [phase, target])

  if (!status) return null
  const hide = (key: string) => { writeDismissed(key); setDismissed(key) }

  if (phase === 'upgrading' || phase === 'stuck') {
    return createPortal(
      <div role="status" className="fixed inset-0 z-50 flex items-center justify-center bg-paper px-4">
        <div className="flex max-w-[520px] flex-col items-center gap-4 text-center">
          {phase === 'upgrading' ? <Spinner className="size-6" /> : null}
          <h2 className="font-display text-[34px] leading-none tracking-[-0.01em] text-ink">
            {phase === 'upgrading' ? `Upgrading to ${target}…` : 'This is taking longer than expected'}
          </h2>
          <p className="text-[15px] leading-[1.6] text-body text-pretty">
            {phase === 'upgrading'
              ? <>TailorbirdCV is downloading the new version and restarting. This takes about a minute; the page reloads by itself.
                {status.windows ? ' It continues in a new terminal window.' : ''}</>
              : <>Check the terminal where TailorbirdCV runs. If it stopped, start it again with
                <code className="mx-1 rounded bg-wash px-1.5 font-mono text-[13px]">tailorbirdcv serve</code>
                or run the install command from the README again.</>}
          </p>
          {phase === 'stuck' && <button className="btn h-9 px-3.5" onClick={() => window.location.reload()}>Reload</button>}
        </div>
      </div>,
      document.body,  // over the whole page, whatever the layout around the banner does
    )
  }

  const last = status.last_upgrade
  if (last && dismissed !== `upgrade:${last.at}` && !(last.ok && status.newer)) {  // a newer version beats "upgraded"
    return last.ok ? (
      <div role="status" className={`${banner} border-[#bfe3cf] bg-ok-soft`}>
        <span className="flex-1"><strong>TailorbirdCV was upgraded to {last.target}.</strong> You’re on the latest version.</span>
        <button className={quiet} onClick={() => hide(`upgrade:${last.at}`)}>Dismiss</button>
      </div>
    ) : (
      <div role="alert" className={`${banner} border-[#f1c9c4] bg-bad-soft`}>
        <span className="flex-1"><strong>The upgrade to {last.target} didn’t finish.</strong> {last.error}</span>
        {status.log && <button className={quiet} onClick={() => api.revealUpgradeLog().catch((e) => setError((e as Error).message))}>Show the log</button>}
        <button className={quiet} onClick={() => hide(`upgrade:${last.at}`)}>Dismiss</button>
        {error && <span className="w-full text-[13px] text-bad">{error}</span>}
      </div>
    )
  }

  if (!status.newer || !status.latest || dismissed === status.latest) return null
  const latest = status.latest
  const upgrade = () => {
    setError(null)
    setTarget(latest)
    api.upgrade().then(() => setPhase('upgrading')).catch((e) => { setError((e as Error).message); setPhase('idle') })
  }
  return (
    <div role="status" className={`${banner} border-[#cfd8f7] bg-accent-soft`}>
      <span className="flex-1">
        <strong>TailorbirdCV {latest} is available</strong> (you have {status.current}).
        {status.kind === 'uv-tool' && phase === 'confirm' &&
          <> TailorbirdCV restarts to upgrade, in about a minute{status.windows ? ', in a new terminal window' : ''}. Anything running stops.</>}
      </span>
      {status.kind === 'uv-tool' ? (
        phase === 'confirm' ? (
          <>
            <button className="btn btn-primary h-9 px-3.5 hover:text-white" onClick={upgrade}>Upgrade now</button>
            <button className={quiet} onClick={() => setPhase('idle')}>Cancel</button>
          </>
        ) : (
          <>
            <button className="btn btn-primary h-9 px-3.5 hover:text-white" onClick={() => setPhase('confirm')}>Upgrade</button>
            <button className={quiet} onClick={() => hide(latest)}>Later</button>
          </>
        )
      ) : (
        <>
          {status.command && <span className="w-full text-[13px] text-body">To upgrade: <Command text={status.command} /></span>}
          <Link to="/settings#about" className={quiet}>Settings</Link>
          <button className={quiet} onClick={() => hide(latest)}>Later</button>
        </>
      )}
      {error && <span className="w-full text-[13px] text-bad">{error}</span>}
    </div>
  )
}
