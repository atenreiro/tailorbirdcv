import { Fragment, useEffect, useRef, useState } from 'react'
import { api, type HistoryDiff, type HistoryEntry, type HistoryKind } from '../api'
import { cx } from '../lib'
import { ErrorNote, Spinner } from '../ui'

const fmt = (iso: string) =>
  new Date(iso).toLocaleString('en-SG', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/** Previous versions of the master profile / knowledge base, with diff and restore. */
export function HistoryPanel({ onRestored, hasUnsaved }: { onRestored: (kind: HistoryKind) => void; hasUnsaved: boolean }) {
  const [kind, setKind] = useState<HistoryKind>('profile')
  // Entries are tagged with the kind they belong to, so switching kinds shows "Loading…" without
  // resetting state inside an effect.
  const [listed, setListed] = useState<{ kind: HistoryKind; entries: HistoryEntry[] } | null>(null)
  const entries = listed?.kind === kind ? listed.entries : null
  const [open, setOpen] = useState<HistoryDiff | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const load = (k: HistoryKind) =>
    api.history(k).then((list) => setListed({ kind: k, entries: list })).catch((e) => setError(e.message))
  useEffect(() => { void load(kind) }, [kind])
  // Only the latest "What changed" request may open its diff (responses can arrive out of order).
  const diffSeq = useRef(0)
  const switchKind = (k: HistoryKind) => { diffSeq.current++; setKind(k); setOpen(null) }

  async function toggle(id: string) {
    const seq = ++diffSeq.current
    if (open?.id === id) { setOpen(null); return }
    setError(null)
    try {
      const diff = await api.historyDiff(kind, id)
      if (seq === diffSeq.current) setOpen(diff)
    } catch (e) {
      if (seq === diffSeq.current) setError((e as Error).message)
    }
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
      diffSeq.current++
      setOpen(null)
      void load(kind)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const row = 'grid items-center gap-x-4 gap-y-2 border-b border-[#e9efeb] px-5 py-3 sm:grid-cols-[170px_minmax(0,1fr)_auto]'
  const small = 'btn h-8 px-3 py-0 text-[13px]'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-[720px] text-sm leading-[1.5] text-muted text-pretty">
          Every save keeps a snapshot of the version <em>before</em> it. Restoring one replaces the current file; your current
          version is snapshotted first, so a restore can be undone. Deleted evidence ids stay retired either way.
        </p>
        <div className="inline-flex h-10 gap-0.5 rounded-lg bg-lane p-[3px]" role="group" aria-label="Show the history of">
          {(['profile', 'knowledge'] as const).map((k) => (
            <button key={k} aria-pressed={kind === k} onClick={() => switchKind(k)}
              className={cx('h-[34px] cursor-pointer rounded-md px-3 font-medium transition-colors', kind === k ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(15_61_46/0.12)]' : 'text-muted hover:text-ink')}>
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
        <div className="overflow-hidden rounded-[14px] border border-rule bg-sheet">
          <div className={cx(row, 'bg-wash py-3.5')}>
            <span className="font-mono text-xs text-accent">now</span>
            <div>
              <p className="font-semibold text-ink">Current version</p>
              <p className="font-mono text-[11px] text-faint">{kind === 'profile' ? 'profile.yaml' : 'knowledge.yaml'} · in your data folder</p>
            </div>
            <span className="justify-self-start px-3 text-[13px] text-faint sm:justify-self-end">Current</span>
          </div>
          {entries.length === 0 && <p className="px-[18px] py-6 text-center text-sm text-muted">No earlier versions yet. They appear after your first change.</p>}
          {entries.map((e) => (
            <Fragment key={e.id}>
              <div className={cx(row, open?.id === e.id && 'bg-wash')}>
                <span className="font-mono text-xs text-muted">{fmt(e.time)}</span>
                <p className="min-w-0 text-ink">Before: {e.cause}</p>
                <div className="flex gap-2">
                  <button className={small} aria-expanded={open?.id === e.id} onClick={() => toggle(e.id)}>{open?.id === e.id ? 'Hide changes' : 'What changed'}</button>
                  <button className={cx(small, 'text-accent hover:border-accent')} disabled={!!busy} onClick={() => restore(e)}>{busy === e.id ? <><Spinner /> Restoring…</> : 'Restore'}</button>
                </div>
              </div>
              {open?.id === e.id && (
                <div className="animate-rise border-b border-[#e9efeb] bg-wash px-5 pb-[18px] pt-3.5">
                  <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-accent">Changed since this version</p>
                  <ul className="mt-2 space-y-1 text-sm text-body">{open.summary.map((l, i) => <li key={i}>• {l}</li>)}</ul>
                  <details className="mt-3">
                    <summary className="cursor-pointer text-[13px] text-muted hover:text-ink">Line-by-line diff</summary>
                    <pre className="mt-2 max-h-[420px] overflow-auto rounded-lg border border-line bg-sheet p-3 font-mono text-[12px] leading-[1.6]">
                      {open.diff.split('\n').map((line, i) => (
                        <div key={i} className={line.startsWith('+') && !line.startsWith('+++') ? 'bg-[#eef7f2] text-ok' : line.startsWith('-') && !line.startsWith('---') ? 'bg-[#fce8ec] text-bad' : 'text-muted'}>{line || ' '}</div>
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
