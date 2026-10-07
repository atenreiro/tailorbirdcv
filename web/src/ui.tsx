import { useEffect, useId, useState, type CSSProperties, type ReactNode } from 'react'
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


/** The waiting animation, from the brand mark: the tailorbird hops along its leaf sewing the stitch while the AI
 *  works ("ai"), or the stitch runs around a page while documents are built ("build"). With "reduce motion" on only
 *  the stitch keeps sewing (a line drawing itself, nothing moves across the screen); the bird stands still. */
export function Stitching({ mode, className }: { mode: 'ai' | 'build'; className?: string }) {
  const mask = useId()
  return (
    <svg aria-hidden="true" viewBox="0 0 120 92" className={cx('h-[104px] w-[136px]', className)}>
      {mode === 'ai' ? (
        <>
          <mask id={mask}>
            <path d="M22 80 C44 78 72 80 96 74" pathLength={100} fill="none" stroke="#fff" strokeWidth="6" strokeDasharray="100" className="stitch-sew" />
          </mask>
          <path d="M12 76 C28 62 66 62 104 72 C88 98 40 102 12 76 Z" fill="#8CCB7A" />
          <path d="M22 80 C44 78 72 80 96 74" fill="none" stroke="#0F3D2E" strokeWidth="1.8" strokeLinecap="round" strokeDasharray="5 4" mask={`url(#${mask})`} />
          <g style={{ animation: 'stitch-walk 2.6s linear infinite' }}>
            <g style={{ animation: 'stitch-hop 0.325s ease-in-out infinite' }}>
              <g transform="translate(-14 24) scale(.62)">
                <path d="M44 52 L30 20 L38 19 L53 47 Z" fill="#0F3D2E" />
                <path d="M42 54 C42 41 54 34 66 37 C77 40 82 50 78 58 C74 65 56 66 47 61 C44 59 42 57 42 54 Z" fill="#0F3D2E" />
                <circle cx="74" cy="34" r="10" fill="#0F3D2E" />
                <path d="M65 31 C66 22 80 22 84 30 C78 27 70 27 65 31 Z" fill="#E4572E" />
                <circle cx="78" cy="33" r="1.8" fill="#F4F7F5" />
                <path d="M83 35 L94 37.5 L83 40 Z" fill="#F2A93B" />
                <path d="M52 52 C58 58 68 58 74 50" fill="none" stroke="#8CCB7A" strokeWidth="2.5" strokeLinecap="round" />
                <path d="M60 63 L60 70 M68 63 L68 70" stroke="#0F3D2E" strokeWidth="2.4" strokeLinecap="round" />
              </g>
            </g>
          </g>
        </>
      ) : (
        <>
          <mask id={mask}>
            <rect x="34" y="10" width="52" height="68" rx="5" pathLength={100} fill="none" stroke="#fff" strokeWidth="7" strokeDasharray="100"
              className="stitch-sew" style={{ '--sew': '3s' } as CSSProperties} />
          </mask>
          <rect x="34" y="10" width="52" height="68" rx="5" fill="#F4F7F5" />
          <rect x="34" y="10" width="52" height="68" rx="5" fill="none" stroke="#0F3D2E" strokeWidth="1.8" strokeLinecap="round" strokeDasharray="5 4" mask={`url(#${mask})`} />
          <rect x="44" y="20" width="32" height="4" rx="2" fill="#0F3D2E" />
          <rect x="44" y="30" width="22" height="2.5" rx="1.2" fill="#C8431D" />
          {[[40, 32], [47, 28], [54, 31], [61, 20]].map(([y, w]) => <rect key={y} x="44" y={y} width={w} height="2.5" rx="1.2" fill="#C0CCC5" />)}
          <path d="M8 84 C24 74 50 74 66 80 C56 94 26 96 8 84 Z" fill="#8CCB7A" />
        </>
      )}
    </svg>
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
        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 font-mono text-[11px] uppercase tracking-[0.06em] text-[#a3bcb0] hover:text-white"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`AI engine ${status === null ? 'checking' : ready ? 'ready' : 'offline'}`}
      >
        <span className={cx('size-[7px] rounded-full', status === null ? 'bg-faint' : ready ? 'bg-[#3ecf8e]' : 'bg-[#ff6b5e]')} />
        <span className="hidden lg:inline">Engine {status === null ? '…' : ready ? 'ready' : 'offline'}</span>
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
    <div className={cx(dock, 'flex max-w-[calc(100vw-32px)] items-center gap-3 rounded-xl bg-ink py-2.5 pl-5 pr-2.5 text-white shadow-[0_18px_40px_-16px_rgb(15_61_46/0.6)]')} role="region" aria-label="Unsaved changes">
      <span className="size-[7px] flex-none rounded-full bg-[#ffb547]" />
      <span className="truncate text-sm">{text}</span>
      <button className="h-9 shrink-0 cursor-pointer rounded-lg border border-[#2e5a4a] px-3.5 text-[13px] font-medium hover:border-[#a3bcb0]" onClick={onDiscard} disabled={busy}>Discard</button>
      <button className="flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-lg bg-[#c8431d] px-4 text-[13px] font-semibold hover:bg-[#a3361a] disabled:opacity-60" onClick={onSave} disabled={busy}>
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
