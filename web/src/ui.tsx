import { useEffect, useState, type ReactNode } from 'react'
import { api, type EngineStatus } from './api'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      className={cx('inline-block size-3.5 rounded-full border-2 border-current border-r-transparent animate-spin', className)}
      aria-hidden
    />
  )
}

/** Full-width "the AI is working" panel with elapsed time — engine calls take a minute or two. */
export function Working({ title, lines, ai = true }: { title: string; lines: string[]; ai?: boolean }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const line = lines[Math.min(Math.floor(secs / 12), lines.length - 1)]
  return (
    <div className="sheet animate-rise px-8 py-10 text-center" role="status" aria-live="polite">
      <div className="mx-auto mb-5 flex w-40 gap-1" aria-hidden>
        {Array.from({ length: 8 }).map((_, i) => (
          <span key={i} className="h-1 flex-1 rounded-full bg-rust/80 animate-pulse" style={{ animationDelay: `${i * 120}ms` }} />
        ))}
      </div>
      <p className="font-serif text-2xl text-ink">{title}</p>
      <p className="mt-2 text-muted">{line}</p>
      <p className="mt-4 font-mono text-xs text-faint">
        {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')} elapsed{ai && ' · runs on your Claude subscription'}
      </p>
    </div>
  )
}

export function ErrorNote({ error, onDismiss }: { error: string | null; onDismiss?: () => void }) {
  if (!error) return null
  return (
    <div className="animate-rise flex items-start gap-3 rounded border border-bad/30 bg-bad-soft px-4 py-3 text-sm text-bad" role="alert">
      <span className="font-semibold">Something went wrong.</span>
      <span className="flex-1 whitespace-pre-wrap">{error}</span>
      {onDismiss && <button className="text-bad/70 hover:text-bad" onClick={onDismiss} aria-label="Dismiss">✕</button>}
    </div>
  )
}

const STATUS_STYLE: Record<string, string> = {
  draft: 'bg-wash text-muted',
  analyzed: 'bg-wash text-body',
  composed: 'bg-warn-soft text-warn',
  built: 'bg-rust-soft text-rust',
  applied: 'bg-ink text-sheet',
  interview: 'bg-ok-soft text-ok',
  offer: 'bg-ok text-sheet',
  rejected: 'bg-bad-soft text-bad',
  withdrawn: 'bg-wash text-faint line-through',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={cx('inline-block rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider', STATUS_STYLE[status] ?? STATUS_STYLE.draft)}>
      {status}
    </span>
  )
}

export function Stamp({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span
      className={cx(
        'animate-stamp inline-block rounded-sm border-2 px-3 py-1 font-mono text-xs font-medium uppercase tracking-[0.2em]',
        ok ? 'border-ok text-ok' : 'border-bad text-bad',
      )}
    >
      {children}
    </span>
  )
}

export function EngineBadge() {
  const [status, setStatus] = useState<EngineStatus | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    api.engine().then(setStatus).catch(() => setStatus({ engine: '?', ready: false, detail: 'Backend unreachable — is `uv run autocv serve` running?' }))
  }, [])
  const ready = status?.ready
  return (
    <div className="relative">
      <button
        className="flex items-center gap-2 rounded-full border border-rule bg-sheet px-3 py-1 text-xs text-muted hover:border-ink"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`AI engine ${status === null ? 'checking' : ready ? 'ready' : 'offline'}`}
      >
        <span className={cx('size-2 rounded-full', status === null ? 'bg-faint' : ready ? 'bg-ok' : 'bg-bad')} />
        <span className="hidden sm:inline">AI engine {status === null ? '…' : ready ? 'ready' : 'offline'}</span>
      </button>
      {open && status && (
        <div className="sheet animate-rise absolute right-0 z-20 mt-2 w-80 rounded p-4 text-sm">
          <p className="eyebrow mb-2">{status.engine}</p>
          <p className="text-body">{status.detail}</p>
          {status.model && <p className="mt-1 font-mono text-xs text-muted">model: {status.model}</p>}
          {!ready && (
            <pre className="mt-3 rounded bg-wash px-3 py-2 font-mono text-xs text-ink">claude{'\n'}/login</pre>
          )}
        </div>
      )}
    </div>
  )
}

export function Section({ eyebrow, title, children, aside }: { eyebrow?: string; title?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="animate-rise">
      {(eyebrow || title || aside) && (
        <div className="rule-b mb-4 flex items-end justify-between gap-4 pb-2">
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            {title && <h2 className="font-serif text-2xl text-ink">{title}</h2>}
          </div>
          {aside}
        </div>
      )}
      {children}
    </section>
  )
}

export function fmtDate(iso?: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
}
