import { useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import type { Identified, PdfMatch } from '../api'
import { cx, fmtDate } from '../lib'
import { ErrorNote, Spinner } from '../ui'

const MATCH: Record<PdfMatch['match'], { label: string; tone: string; explain: string }> = {
  exact: { label: 'Exact file', tone: 'bg-ok-soft text-ok', explain: 'Byte for byte the file AutoCV recorded (same SHA-256).' },
  document: { label: 'Same PDF, re-saved', tone: 'bg-accent-soft text-accent',
    explain: 'The file was changed or re-saved by another app, but it still carries the same PDF document id.' },
  text: { label: 'Similar text', tone: 'bg-[#f6ead2] text-warn',
    explain: 'No id matched: this is the closest resume by its words. A best guess, not proof.' },
}

export interface IdentifyState { name: string; busy: boolean; result: Identified | null; error: string | null }

/** The result of Applications → "Identify a PDF" (see useIdentifyPdf). */
export default function IdentifyPdf({ state, onClose, onFile, onPick }: {
  state: IdentifyState; onClose: () => void; onFile: (f: File) => void; onPick: () => void
}) {
  const [over, setOver] = useState(false)
  const r = state.result
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f) }
  return (
    <section aria-label="Identify a PDF" onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}
      className={cx('animate-rise flex flex-col gap-3.5 rounded-[14px] border bg-sheet px-5 py-4', over ? 'border-accent' : 'border-rule')}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="font-display text-xl text-ink">Identify a PDF</h2>
          <p className="truncate text-sm text-muted" title={state.name}>{state.name}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn h-9 px-3" onClick={onPick} disabled={state.busy}>Another PDF</button>
          <button className="btn h-9 px-3" onClick={onClose}>Close</button>
        </div>
      </div>
      {state.busy && <p className="flex items-center gap-2 text-sm text-muted"><Spinner /> Comparing with your sent copies and builds…</p>}
      <ErrorNote error={state.error} />
      {r && (
        <>
          {r.matches.length === 0 ? (
            <p className="text-sm text-ink">
              No match. This PDF isn’t one of your sent copies or current builds, and its text isn’t close to any of them.
              Copies made before you marked an application <strong>applied</strong> (or froze a copy) aren’t kept, so they can’t be matched.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {r.matches.map((m) => (
                <li key={`${m.app_id}/${m.snapshot ?? 'build'}/${m.file}`}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-rule px-3 py-2.5">
                  <span title={MATCH[m.match].explain}
                    className={cx('rounded-full px-2 py-0.5 text-xs font-semibold', MATCH[m.match].tone)}>
                    {MATCH[m.match].label}{m.match === 'text' ? ` · ${Math.round(m.score * 100)}%` : ''}
                  </span>
                  <span className="min-w-0 font-medium text-ink">{m.company} · {m.role}</span>
                  <span className="text-sm text-muted">
                    {m.kind === 'sent' ? `sent copy, ${fmtDate(m.created)}` : 'current build (not a sent copy)'}
                  </span>
                  <Link to={`/a/${m.app_id}`} className="ml-auto text-sm text-accent hover:text-accent-strong">Open →</Link>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted">{r.matches[0] ? MATCH[r.matches[0].match].explain : ''}</p>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 font-mono text-[11px] text-faint">
            <dt>SHA-256</dt><dd className="select-all break-all">{r.sha256}</dd>
            {r.document_id && <><dt>Document id</dt><dd className="select-all break-all">{r.document_id}</dd></>}
          </dl>
        </>
      )}
    </section>
  )
}
