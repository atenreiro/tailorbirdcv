import { useEffect, useState } from 'react'
import { api, type HistoryDiff, type HistoryEntry, type HistoryKind } from '../api'
import { cx, ErrorNote, Spinner } from '../ui'

const fmt = (iso: string) =>
  new Date(iso).toLocaleString('en-SG', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/** Previous versions of the master profile / knowledge base, with diff and restore. */
export function HistoryPanel({ onRestored, hasUnsaved }: { onRestored: () => void; hasUnsaved: boolean }) {
  const [kind, setKind] = useState<HistoryKind>('profile')
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null)
  const [open, setOpen] = useState<HistoryDiff | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const load = (k: HistoryKind) => {
    setEntries(null); setOpen(null)
    api.history(k).then(setEntries).catch((e) => setError(e.message))
  }
  useEffect(() => { load(kind) }, [kind])

  async function show(id: string) {
    setError(null)
    try { setOpen(await api.historyDiff(kind, id)) } catch (e) { setError((e as Error).message) }
  }

  async function restore(e: HistoryEntry) {
    const what = kind === 'profile' ? 'master profile' : 'answers & preferences'
    const warn = hasUnsaved ? '\n\nYou have unsaved edits on this page; they will be discarded.' : ''
    if (!window.confirm(`Restore your ${what} to the version from ${fmt(e.time)}?\n\nYour current version is kept in history first, so you can undo this.${warn}`)) return
    setBusy(true); setError(null)
    try {
      await api.restore(kind, e.id)
      setFlash(`Restored the version from ${fmt(e.time)}`); setTimeout(() => setFlash(null), 3000)
      onRestored()
      load(kind)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="max-w-2xl text-sm text-muted">
        Every change is saved here automatically. Each entry is the version <em>before</em> that change. Restoring keeps
        your current version too, so it can be undone. Deleted evidence ids stay retired, so no resume can quietly point at a different fact.
      </p>
      <div className="flex gap-1 rounded border border-rule bg-wash p-1 text-sm" role="tablist">
        {(['profile', 'knowledge'] as const).map((k) => (
          <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
            className={cx('flex-1 rounded px-4 py-1.5 transition', kind === k ? 'bg-sheet text-ink shadow-sm' : 'text-muted hover:text-ink')}>
            {k === 'profile' ? 'Master profile' : 'Answers & preferences'}
          </button>
        ))}
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {flash && <p className="animate-rise text-sm text-ok">✓ {flash}</p>}
      {entries === null && <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}
      {entries?.length === 0 && <div className="sheet rounded px-8 py-10 text-center text-muted">No earlier versions yet. They appear after your first change.</div>}
      {entries && entries.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <ol className="sheet max-h-[640px] divide-y divide-rule/70 overflow-auto rounded">
            {entries.map((e) => (
              <li key={e.id}>
                <button onClick={() => show(e.id)}
                  className={cx('w-full px-4 py-3 text-left transition hover:bg-paper', open?.id === e.id && 'bg-wash')}>
                  <span className="block text-sm text-ink">{fmt(e.time)}</span>
                  <span className="block text-xs text-muted">before: {e.cause}</span>
                </button>
              </li>
            ))}
          </ol>
          <div className="min-w-0">
            {!open ? (
              <div className="sheet rounded px-8 py-10 text-center text-sm text-muted">Pick a version to see what changed since then.</div>
            ) : (
              <div className="sheet space-y-4 rounded p-5">
                <div>
                  <p className="eyebrow">Changed since this version</p>
                  <ul className="mt-2 space-y-1 text-sm text-body">{open.summary.map((l, i) => <li key={i}>• {l}</li>)}</ul>
                </div>
                <details>
                  <summary className="cursor-pointer text-sm text-muted hover:text-ink">Line-by-line diff</summary>
                  <pre className="mt-2 max-h-[420px] overflow-auto rounded bg-paper p-3 font-mono text-[12px] leading-relaxed">
                    {open.diff.split('\n').map((line, i) => (
                      <div key={i} className={line.startsWith('+') && !line.startsWith('+++') ? 'text-ok' : line.startsWith('-') && !line.startsWith('---') ? 'text-bad' : 'text-muted'}>{line || ' '}</div>
                    ))}
                  </pre>
                </details>
                <button className="btn btn-primary" disabled={busy} onClick={() => restore(entries.find((x) => x.id === open.id)!)}>
                  {busy ? <><Spinner /> Restoring…</> : 'Restore this version'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
