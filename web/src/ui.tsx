import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, STATUSES, type EngineStatus, type Outcome } from './api'
import { cx, OUTCOME_GROUPS, OUTCOMES, statusLabel, statusStyle } from './lib'
import { ENGINE_NAMES } from './settings'

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      className={cx('inline-block size-3.5 rounded-full border-2 border-current border-r-transparent animate-spin', className)}
      aria-hidden
    />
  )
}

export function ErrorNote({ error, onDismiss }: { error: string | null; onDismiss?: () => void }) {
  if (!error) return null
  return (
    <div className="animate-rise flex items-start gap-3 rounded-lg border border-bad/30 bg-bad-soft px-4 py-3 text-sm text-bad" role="alert">
      <span className="font-semibold">Something went wrong.</span>
      <span className="flex-1 whitespace-pre-wrap">{error}</span>
      {onDismiss && <button className="text-bad/70 hover:text-bad" onClick={onDismiss} aria-label="Dismiss">✕</button>}
    </div>
  )
}

export function StatusPill({ status, outcome, className }: { status: string; outcome?: string | null; className?: string }) {
  return (
    <span className={cx('inline-block whitespace-nowrap rounded px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em]', statusStyle(status, outcome), className)}>
      {statusLabel(status, outcome)}
    </span>
  )
}

/** A status pill that is also the status picker. Closing goes through "Close as…" so the
 *  outcome is always recorded. */
export function StatusSelect({ status, outcome, disabled, label, onChange }: {
  status: string; outcome?: string | null; disabled?: boolean; label: string
  onChange: (status: string, outcome?: Outcome) => void
}) {
  const value = status === 'closed' ? `closed:${outcome ?? ''}` : status
  return (
    <label className="relative inline-flex shrink-0 cursor-pointer items-center" title="Change status">
      <StatusPill status={status} outcome={outcome} className="!py-[5px] !pl-[9px] !pr-6 !text-[11px]" />
      <span className="pointer-events-none absolute right-2 text-[9px] opacity-70" aria-hidden>▼</span>
      <select aria-label={label} className="absolute inset-0 cursor-pointer opacity-0" value={value} disabled={disabled}
        onChange={(e) => {
          const [s, o] = e.target.value.split(':')
          onChange(s, (o || undefined) as Outcome | undefined)
        }}>
        {STATUSES.filter((s) => s !== 'closed').map((s) => <option key={s} value={s}>{s}</option>)}
        {status === 'closed' && !OUTCOMES.some((o) => o.key === outcome) && <option value={value}>closed</option>}
        {OUTCOME_GROUPS.map(([who, title]) => (
          <optgroup key={who} label={`Close · ${title.toLowerCase()}`}>
            {OUTCOMES.filter((o) => o.who === who).map((o) => <option key={o.key} value={`closed:${o.key}`}>{o.label}</option>)}
          </optgroup>
        ))}
      </select>
    </label>
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
    const load = () => api.engine().then(setStatus)
      .catch(() => setStatus({ engine: '?', ready: false, detail: 'Backend unreachable — is `tailorbirdcv serve` still running?' }))
    void load()
    window.addEventListener('tailorbirdcv:settings', load)  // the AI engine or key changed
    return () => window.removeEventListener('tailorbirdcv:settings', load)
  }, [])
  const ready = status?.ready
  return (
    <div className="relative">
      <button
        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 font-mono text-[11px] uppercase tracking-[0.06em] text-[#9aa3b5] hover:text-white"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`AI engine ${status === null ? 'checking' : ready ? 'ready' : 'offline'}`}
      >
        <span className={cx('size-[7px] rounded-full', status === null ? 'bg-faint' : ready ? 'bg-[#3ecf8e]' : 'bg-[#ff6b5e]')} />
        <span className="hidden sm:inline">Engine {status === null ? '…' : ready ? 'ready' : 'offline'}</span>
      </button>
      {open && status && (
        <div className="sheet animate-rise absolute right-0 z-20 mt-2 w-80 rounded-lg p-4 text-sm text-ink">
          <p className="eyebrow mb-2">{ENGINE_NAMES[status.engine] ?? status.engine}</p>
          <p className="text-body">{status.detail}</p>
          {status.model && <p className="mt-1 font-mono text-xs text-muted">model: {status.model}</p>}
          {!ready && status.engine === 'claude-cli' && (
            <pre className="mt-3 rounded-lg bg-wash px-3 py-2 font-mono text-xs text-ink">claude{'\n'}/login</pre>
          )}
          {!ready && status.engine === 'codex-cli' && (
            <pre className="mt-3 rounded-lg bg-wash px-3 py-2 font-mono text-xs text-ink">codex login</pre>
          )}
          <Link to="/settings" onClick={() => setOpen(false)} className="mt-3 inline-block text-xs text-accent hover:text-accent-strong">AI engine settings →</Link>
        </div>
      )}
    </div>
  )
}

/** Floating "unsaved changes" dock, bottom-centre; turns into a brief "✓ Saved" toast. */
export function SaveDock({ dirty, text, busy, flash, onSave, onDiscard, saveLabel = 'Save' }: {
  dirty: boolean; text: string; busy: boolean; flash: string | null
  onSave: () => void; onDiscard: () => void; saveLabel?: string
}) {
  const dock = 'fixed bottom-6 left-1/2 z-40 -translate-x-1/2 animate-rise'
  if (flash && !dirty) {
    return <div className={cx(dock, 'flex items-center gap-2 rounded-xl border border-[#b5dcc6] bg-[#dcefe5] px-[18px] py-3 text-sm font-medium text-ok')} role="status">✓ {flash}</div>
  }
  if (!dirty) return null
  return (
    <div className={cx(dock, 'flex max-w-[calc(100vw-32px)] items-center gap-3 rounded-xl bg-ink py-2.5 pl-5 pr-2.5 text-white shadow-[0_18px_40px_-16px_rgb(14_20_34/0.6)]')} role="region" aria-label="Unsaved changes">
      <span className="size-[7px] flex-none rounded-full bg-[#ffb547]" />
      <span className="truncate text-sm">{text}</span>
      <button className="h-9 shrink-0 cursor-pointer rounded-lg border border-[#3a4356] px-3.5 text-[13px] font-medium hover:border-[#9aa3b5]" onClick={onDiscard} disabled={busy}>Discard</button>
      <button className="flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-lg bg-[#4d6bff] px-4 text-[13px] font-semibold hover:bg-[#3d5bf0] disabled:opacity-60" onClick={onSave} disabled={busy}>
        {busy && <Spinner />}{busy ? 'Saving…' : saveLabel}
      </button>
    </div>
  )
}

/** The company's site icon, served by TailorbirdCV from the application's folder. Decorative (the name is next to it);
 * if it can't be shown it disappears instead of leaving a broken image. */
export function Favicon({ appId, size = 16, className = '' }: { appId: string; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) return null
  return (
    <img src={api.faviconUrl(appId)} alt="" aria-hidden width={size} height={size} loading="lazy" decoding="async"
      draggable={false} onError={() => setFailed(true)}
      className={cx('flex-none rounded-[3px] object-contain', className)} style={{ width: size, height: size }} />
  )
}
