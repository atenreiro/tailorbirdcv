import { api, ApiError } from '../../api'
import { fmtDate } from '../../ui'
import { Section, Stamp } from '../../ui'
import type { StepProps } from '../Workspace'
import StyleCoach from './StyleCoach'

export default function Export({ app, setApp, go, run, memo }: StepProps) {
  const pdf = app.files.find((f) => f.endsWith('.pdf'))
  const docx = app.files.find((f) => f.endsWith('.docx'))
  const pages = app.build?.pages ?? app.meta.pages
  const stale = app.outputs_stale
  const tooLong = !stale && !!pages && pages > 2
  const ok = !!app.report?.ok
  const unsaved = !!memo.review
  const overBudget = !!app.length && app.length.lines > app.length.budget

  const build = () =>
    run('Typesetting your resume', [
      'Rendering your exact resume design…',
      'Converting to PDF through Microsoft Word…',
      'Counting pages…',
    ], async () => setApp(await api.build(app.id)), false)

  const freezeCopy = () =>
    run('Freezing a copy', ['Saving a read-only copy of exactly these files…'], async () => {
      try {
        setApp(await api.freeze(app.id))
      } catch (e) {
        if (!(e instanceof ApiError) || e.code !== 'needs_build') throw e
        if (window.confirm(`${e.message}\n\nBuild a fresh PDF now and freeze that? (Word will open briefly.)`)) {
          setApp(await api.freeze(app.id, { build: true }))
        }
      }
    }, false)

  const trim = () =>
    run('Trimming to 2 pages', [
      'Dropping the least relevant bullets, oldest roles first…',
      'Re-running the fact-check…',
    ], async () => setApp(await api.trim(app.id)))

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="space-y-6">
        <Section eyebrow="Export" title={docx && !stale ? 'Ready to send' : 'Build the files'}>
          {unsaved && <p className="mb-3 rounded bg-warn-soft px-3 py-2 text-sm text-warn">You have unsaved Review edits. Save them in Review before building.</p>}
          {!ok && <p className="text-sm text-bad">The fact-check isn’t passing. Fix the issues in Review first.</p>}
          {ok && !docx && <p className="text-sm text-muted">Renders your resume in its original design, then converts it to PDF with Microsoft Word. The first run may ask macOS for permission to control Word.</p>}
          {ok && !docx && overBudget && (
            <p className="mt-2 text-sm text-warn">Heads-up: this draft looks longer than 2 pages (~{app.length!.lines} vs ~{app.length!.budget} lines).</p>
          )}
          {docx && stale && (
            <p className="mb-3 rounded bg-warn-soft px-3 py-2 text-sm text-warn">
              These files are out of date: the resume changed after they were built. Rebuild before sending.
            </p>
          )}
          {docx && (
            <div className="space-y-4">
              {!stale && (
                <div className="flex items-center gap-3">
                  <Stamp ok={!tooLong}>{pages ? `${pages} page${pages > 1 ? 's' : ''}` : 'docx only'}</Stamp>
                  {tooLong && <span className="text-sm text-bad">Over the 2-page limit</span>}
                </div>
              )}
              {tooLong && (
                <p className="text-sm text-muted">Let the AI cut the least relevant content (oldest roles first, facts locked), or trim it yourself in Review. Then rebuild.</p>
              )}
              <div className={stale ? 'flex flex-col gap-2 opacity-50' : 'flex flex-col gap-2'}>
                {[docx, pdf].filter(Boolean).map((f) => (
                  <a key={f} href={api.fileUrl(app.id, f!, true)} className="btn justify-between" title={f}>
                    <span>{f!.endsWith('.pdf') ? 'PDF' : 'Word document'} <span className="font-mono text-xs text-muted">.{f!.split('.').pop()}{stale ? ' · outdated' : ''}</span></span>
                    <span aria-hidden>↓</span>
                  </a>
                ))}
                <button className="btn justify-between" onClick={() => api.reveal(app.id).catch(() => {})}
                  title="Opens this application's folder with the PDF selected, so you upload exactly this file">
                  <span>Show in Finder</span><span aria-hidden>↗</span>
                </button>
              </div>
              <p className="text-xs text-faint">Tip: upload from Finder. Repeated downloads get “(1)” added to the name.</p>
            </div>
          )}
          <div className="mt-6 flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={!ok || unsaved} onClick={build}>{docx ? 'Rebuild' : 'Build .docx + .pdf'}</button>
            {(tooLong || (overBudget && !docx)) && <button className="btn" disabled={!ok || unsaved} onClick={trim}>Trim with AI</button>}
            <button className="btn" onClick={() => go('review')}>Back to review</button>
          </div>
        </Section>

        {(docx || app.sent.length > 0) && (
          <div className="sheet animate-rise rounded p-5 text-sm">
            <div className="flex items-center justify-between">
              <p className="eyebrow">Sent copies</p>
              <button className="btn btn-ghost px-2 py-1 text-xs text-rust" disabled={!ok || unsaved} onClick={freezeCopy}
                title="Save a read-only copy of exactly these files, e.g. when you send an updated version">
                + Freeze a copy
              </button>
            </div>
            {app.sent.length === 0 ? (
              <p className="mt-2 text-muted">When you mark this application <strong>applied</strong>, AutoCV keeps a read-only copy of exactly what you sent. Later edits and rebuilds never change it.</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {app.sent.map((c) => (
                  <li key={c.id} className="rounded border border-rule p-2">
                    <p className="text-xs text-muted">{fmtDate(c.created)} · {c.reason}{c.pages ? ` · ${c.pages} pages` : ''}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {c.files.filter((f) => /\.(pdf|docx)$/.test(f)).map((f) => (
                        <a key={f} href={api.sentFileUrl(app.id, c.id, f, true)} className="chip hover:bg-rust-soft hover:text-rust">↓ {f.split('.').pop()}</a>
                      ))}
                      <button className="chip hover:bg-rust-soft hover:text-rust" onClick={() => api.reveal(app.id, c.id).catch(() => {})}>Show in Finder</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {docx && <StyleCoach app={app} />}

        {docx && (
          <div className="animate-rise rounded border border-rule bg-wash/60 p-4 text-sm text-muted">
            <p className="font-medium text-ink">Before you send it</p>
            <p className="mt-1">Read it once, end to end. The fact-check guarantees numbers and names, but only you can confirm the emphasis sounds like you.</p>
          </div>
        )}
      </div>

      <div className="animate-rise">
        {pdf && (
          <a href={api.fileUrl(app.id, pdf)} target="_blank" rel="noreferrer" className="mb-2 inline-block text-sm text-muted hover:text-rust">Open the PDF in a new tab ↗</a>
        )}
        {pdf ? (
          <iframe
            key={app.meta.updated}
            title="PDF preview"
            src={api.fileUrl(app.id, pdf)}
            className="sheet h-[1100px] w-full rounded"
          />
        ) : (
          <div className="sheet flex h-[600px] items-center justify-center rounded">
            <p className="font-serif text-xl italic text-faint">The PDF preview appears here.</p>
          </div>
        )}
      </div>
    </div>
  )
}
