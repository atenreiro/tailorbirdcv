import { Fragment, useEffect, useState } from 'react'
import { api, type HistoryDiff, type HistoryEntry, type HistoryKind } from '../api'
import { cx, ErrorNote, Spinner } from '../ui'

const fmt = (iso: string) =>
  new Date(iso).toLocaleString('en-SG', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/** Previous versions of the master profile / knowledge base, with diff and restore. */
export function HistoryPanel({ onRestored, hasUnsaved }: { onRestored: (kind: HistoryKind) => void; hasUnsaved: boolean }) {
  const [kind, setKind] = useState<HistoryKind>('profile')
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null)
  const [open, setOpen] = useState<HistoryDiff | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const load = (k: HistoryKind) => {
    setEntries(null); setOpen(null)
    api.history(k).then(setEntries).catch((e) => setError(e.message))
  }
  useEffect(() => { load(kind) }, [kind])

  async function toggle(id: string) {
    if (open?.id === id) { setOpen(null); return }
    setError(null)
    try { setOpen(await api.historyDiff(kind, id)) } catch (e) { setError((e as Error).message) }
  }

  async function restore(e: HistoryEntry) {
    const what = kind === 'profile' ? 'master profile' : 'answers & preferences'
    const warn = hasUnsaved ? '\n\nYou have unsaved edits on this page; they will be discarded.' : ''
    if (!window.confirm(`Restore your ${what} to the version from ${fmt(e.time)}?\n\nYour current version is kept in history first, so you can undo this.${warn}`)) return
    setBusy(e.id); setError(null)
    try {
      await api.restore(kind, e.id)
      setFlash(`Restored the version from ${fmt(e.time)}`); setTimeout(() => setFlash(null), 3000)
      onRestored(kind)
      load(kind)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const row = 'grid items-center gap-x-4 gap-y-2 border-b border-rule/70 px-[18px] py-3 sm:grid-cols-[150px_minmax(0,1fr)_auto]'
  const small = 'btn px-3 py-1 text-[13px]'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-[720px] text-[13px] text-muted text-pretty">
          Every save keeps a snapshot of the version <em>before</em> it. Restoring one replaces the current file; your current
          version is snapshotted first, so a restore can be undone. Deleted evidence ids stay retired either way.
        </p>
        <div className="flex gap-1 rounded-lg border border-rule bg-wash p-1 text-[13px]" role="tablist">
          {(['profile', 'knowledge'] as const).map((k) => (
            <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
              className={cx('cursor-pointer rounded-lg px-3 py-1 transition', kind === k ? 'bg-sheet text-ink shadow-sm' : 'text-muted hover:text-ink')}>
              {k === 'profile' ? 'Master profile' : 'Answers & preferences'}
            </button>
          ))}
        </div>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {flash && <p className="animate-rise text-sm text-ok">✓ {flash}</p>}
      {entries === null ? (
        <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-rule bg-sheet">
          <div className={row}>
            <span className="font-mono text-xs text-muted">now</span>
            <div>
              <p className="text-ink">Current version</p>
              <p className="text-xs text-faint">{kind === 'profile' ? 'private/profile.yaml' : 'private/knowledge.yaml'}</p>
            </div>
            <span className="justify-self-start px-3 text-[13px] text-faint sm:justify-self-end">Current</span>
          </div>
          {entries.length === 0 && <p className="px-[18px] py-6 text-center text-sm text-muted">No earlier versions yet. They appear after your first change.</p>}
          {entries.map((e) => (
            <Fragment key={e.id}>
              <div className={cx(row, open?.id === e.id && 'bg-wash/60')}>
                <span className="font-mono text-xs text-muted">{fmt(e.time)}</span>
                <p className="min-w-0 text-ink">Before: {e.cause}</p>
                <div className="flex gap-2">
                  <button className={small} aria-expanded={open?.id === e.id} onClick={() => toggle(e.id)}>{open?.id === e.id ? 'Hide changes' : 'What changed'}</button>
                  <button className={small} disabled={!!busy} onClick={() => restore(e)}>{busy === e.id ? <><Spinner /> Restoring…</> : 'Restore'}</button>
                </div>
              </div>
              {open?.id === e.id && (
                <div className="animate-rise border-b border-rule/70 bg-paper/60 px-[18px] py-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">Changed since this version</p>
                  <ul className="mt-2 space-y-1 text-sm text-body">{open.summary.map((l, i) => <li key={i}>• {l}</li>)}</ul>
                  <details className="mt-3">
                    <summary className="cursor-pointer text-sm text-muted hover:text-ink">Line-by-line diff</summary>
                    <pre className="mt-2 max-h-[420px] overflow-auto rounded-lg border border-rule bg-sheet p-3 font-mono text-[12px] leading-relaxed">
                      {open.diff.split('\n').map((line, i) => (
                        <div key={i} className={line.startsWith('+') && !line.startsWith('+++') ? 'text-ok' : line.startsWith('-') && !line.startsWith('---') ? 'text-bad' : 'text-muted'}>{line || ' '}</div>
                      ))}
                    </pre>
                  </details>
                </div>
              )}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}
