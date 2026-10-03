import { useEffect, useState, type ReactNode } from 'react'
import { api, type EngineStatus } from './api'
import { cx, statusStyle } from './lib'

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

export function StatusPill({ status, className }: { status: string; className?: string }) {
  return (
    <span className={cx('inline-block rounded px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em]', statusStyle(status), className)}>
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
          <p className="eyebrow mb-2">{status.engine}</p>
          <p className="text-body">{status.detail}</p>
          {status.model && <p className="mt-1 font-mono text-xs text-muted">model: {status.model}</p>}
          {!ready && (
            <pre className="mt-3 rounded-lg bg-wash px-3 py-2 font-mono text-xs text-ink">claude{'\n'}/login</pre>
          )}
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
