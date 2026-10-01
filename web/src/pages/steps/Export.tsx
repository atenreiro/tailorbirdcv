import { api } from '../../api'
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
              </div>
            </div>
          )}
          <div className="mt-6 flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={!ok || unsaved} onClick={build}>{docx ? 'Rebuild' : 'Build .docx + .pdf'}</button>
            {(tooLong || (overBudget && !docx)) && <button className="btn" disabled={!ok || unsaved} onClick={trim}>Trim with AI</button>}
            <button className="btn" onClick={() => go('review')}>Back to review</button>
          </div>
        </Section>

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
