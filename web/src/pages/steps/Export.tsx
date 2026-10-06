import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type Profile, type Tailored } from '../../api'
import { cx, fmtDate } from '../../lib'
import { fileManager, pageLimit, pagesText, pdfEngineName, showInFolder, useSettings } from '../../settings'
import { ErrorNote, Stamp } from '../../ui'
import type { StepProps } from '../Workspace'
import StyleCoach from './StyleCoach'
import { btn, btnPrimary, chip, label } from './v3'

const card = 'rounded-xl border border-rule bg-sheet'
const ROOM_MIN_LINES = 5  // matches fit.ROOM_MIN_LINES on the server
const fileLink = 'flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-rule bg-sheet px-3.5 py-2 font-medium text-ink transition-colors hover:border-ink'

export default function Export({ app, profile, setApp, go, run, memo, setMemo }: StepProps) {
  const pdf = app.files.find((f) => f.endsWith('.pdf'))
  const docx = app.files.find((f) => f.endsWith('.docx'))
  const pages = app.build?.pages ?? app.meta.pages
  const stale = app.outputs_stale
  const ok = !!app.report?.ok
  const unsaved = !!memo.review
  const overBudget = !!app.length && app.length.lines > app.length.budget
  const settings = useSettings()
  const [revealError, setRevealError] = useState<string | null>(null)  // e.g. no file manager on Linux
  const limit = pageLimit(settings)
  const tooLong = !stale && !!pages && pages > limit
  const fill = !stale && !tooLong && pages ? app.meta.fill : null
  const lastFill = fill?.pages.length ? fill.pages[fill.pages.length - 1] : null
  const roomy = !!fill && fill.room >= ROOM_MIN_LINES
  const engine = pdfEngineName(settings)
  const via = engine ? ` with ${engine}` : ''

  const build = () =>
    run('Typesetting your resume', [
      'Rendering your exact resume design…',
      `Converting to PDF${via}…`,
      'Counting pages…',
    ], async () => setApp(await api.build(app.id)), false)

  const freezeCopy = () =>
    run('Freezing a copy', ['Saving a read-only copy of exactly these files…'], async () => {
      try {
        setApp(await api.freeze(app.id))
      } catch (e) {
        if (!(e instanceof ApiError) || e.code !== 'needs_build') throw e
        if (window.confirm(`${e.message}\n\nBuild a fresh PDF now and freeze that?`)) {
          setApp(await api.freeze(app.id, { build: true }))
        }
      }
    }, false)

  // The AI proposes a shorter version; it opens in Review as unsaved edits, and nothing is saved
  // until you Save & check there.
  const trim = () =>
    run(`Trimming to ${pagesText(limit)}`, [
      'Dropping the least relevant bullets, oldest roles first…',
      'Re-running the fact-check…',
    ], async () => {
      const { trim_proposal: proposal, ...next } = await api.trim(app.id)
      setApp(next)
      if (proposal === undefined) return  // an older server saved the trim itself
      if (!proposal) {
        throw new Error('The AI couldn’t find anything to cut without changing the facts. Trim it yourself in Review: remove the least relevant lines, then rebuild.')
      }
      const before = app.length ? `~${app.length.lines}` : 'the current length'
      setMemo((m) => ({
        ...m,
        review: {
          draft: proposal.tailored, rev: (m.review?.rev ?? 0) + 1,
          notice: `AI trim suggestions — review the changes, then Save & check. Estimated ${before} → ~${proposal.lines} of ${proposal.budget} lines; edited lines are marked with a dot. Nothing is saved until you save, and Discard keeps the current version.`,
        },
      }))
      go('review')
    })

  // The AI adds relevant evidence the resume doesn't use yet, up to the room measured on the last page.
  // Like Trim, it opens in Review as unsaved edits.
  const fillPage = () =>
    run('Filling the last page', [
      'Finding relevant evidence the resume doesn’t use yet…',
      'Re-running the fact-check…',
    ], async () => {
      const { fill_proposal: proposal, ...next } = await api.fill(app.id)
      setApp(next)
      if (!proposal) {
        throw new Error('The AI found nothing relevant to add that fits without changing the facts. You can add evidence yourself in Review (“+ add … from evidence”).')
      }
      setMemo((m) => ({
        ...m,
        review: {
          draft: proposal.tailored, rev: (m.review?.rev ?? 0) + 1,
          notice: `AI additions to fill the last page — about ${proposal.added_lines} more lines of the ~${proposal.room} available, all from your profile. Review them, then Save & check and rebuild. Edited lines are marked with a dot; nothing is saved until you save, and Discard keeps the current version.`,
        },
      }))
      go('review')
    })

  return (
    <div className="grid grid-cols-1 items-start gap-7 lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="flex min-w-0 flex-col gap-[18px]">
        <section className="animate-rise flex flex-col gap-3.5">
          <div className="border-b border-rule pb-2">
            <p className={label}>Export</p>
            <h2 className="font-display text-2xl text-ink">{docx && !stale ? 'Ready to send' : 'Build the files'}</h2>
          </div>
          <ErrorNote error={revealError} onDismiss={() => setRevealError(null)} />
          {unsaved && <p className="rounded-lg bg-[#f6ead2] px-3 py-2 text-[13px] text-warn">You have unsaved Review edits. Save them in Review before building.</p>}
          {!ok && <p className="text-[13px] text-bad">The fact-check isn’t passing. Fix the issues in Review first.</p>}
          {ok && !docx && <p className="text-[13px] text-muted">Renders your resume in its original design, then converts it to PDF{via}.{settings?.pdf_effective === 'word' && settings.platform === 'macos' ? ' The first run may ask macOS for permission to control Word.' : ''}</p>}
          {ok && !docx && overBudget && (
            <p className="text-[13px] text-warn">Heads-up: this draft looks longer than {pagesText(limit)} (~{app.length!.lines} vs ~{app.length!.budget} lines).</p>
          )}
          {docx && stale && (
            <p className="rounded-lg bg-[#f6ead2] px-3 py-2 text-[13px] text-warn">
              These files are out of date: the resume changed after they were built. Rebuild before sending.
            </p>
          )}
          {docx && !stale && (
            <div className="flex flex-wrap items-center gap-3">
              <Stamp ok={!tooLong}>{pages ? `${pages} page${pages > 1 ? 's' : ''}` : 'docx only'}</Stamp>
              {tooLong && <span className="text-[13px] text-bad">Over the {limit}-page limit</span>}
              {lastFill !== null && (
                <span className="text-[13px] text-muted" title="How far down the last page the text reaches">
                  last page {Math.round(lastFill * 100)}% full{roomy ? ` · room for ~${fill!.room} more lines` : ''}
                </span>
              )}
            </div>
          )}
          {roomy && (
            <p className="text-[13px] text-muted">There’s space left on the last page. Let the AI add the most relevant evidence your resume doesn’t use yet (facts locked), then rebuild.</p>
          )}
          {tooLong && (
            <p className="text-[13px] text-muted">Let the AI cut the least relevant content (oldest roles first, facts locked), or trim it yourself in Review. Then rebuild.</p>
          )}
          {docx && (
            <>
              <div className={cx('flex flex-col gap-2', stale && 'opacity-50')}>
                {[docx, pdf].filter(Boolean).map((f) => (
                  <a key={f} href={api.fileUrl(app.id, f!, true)} className={fileLink} title={f}>
                    <span>{f!.endsWith('.pdf') ? 'PDF' : 'Word document'} <span className="font-mono text-xs text-muted">.{f!.split('.').pop()}{stale ? ' · outdated' : ''}</span></span>
                    <span aria-hidden>↓</span>
                  </a>
                ))}
                <button className={fileLink} onClick={() => api.reveal(app.id).catch((e) => setRevealError((e as Error).message))}
                  title="Opens this application's folder with the PDF selected, so you upload exactly this file">
                  <span>{showInFolder(settings?.platform)}</span><span aria-hidden>↗</span>
                </button>
              </div>
              <p className="text-xs text-faint">Tip: upload from {fileManager(settings?.platform)}. Repeated downloads get “(1)” added to the name.</p>
            </>
          )}
          <div className="flex flex-wrap gap-2">
            <button className={btnPrimary} disabled={!ok || unsaved} onClick={build}
              title={unsaved ? 'Save your Review edits first' : !ok ? 'Fix the fact-check issues in Review first' : `Render the .docx and convert it to PDF${via}`}>{docx ? 'Rebuild' : 'Build .docx + .pdf'}</button>
            {(tooLong || (overBudget && !docx)) && <button className={btn} disabled={!ok || unsaved} onClick={trim}>Trim with AI</button>}
            {roomy && <button className={btn} disabled={!ok || unsaved} onClick={fillPage}>Fill the page with AI</button>}
            <button className={btn} onClick={() => go('review')}>Back to review</button>
          </div>
          {settings && (
            <p className="text-xs text-faint">
              {engine ? <>PDFs are made with {engine}. </> : <>No PDF app found: only the .docx can be built. </>}
              <Link to="/settings" className="text-accent hover:text-accent-strong">Change in Settings</Link>
            </p>
          )}
        </section>

        <section className={cx(card, 'animate-rise flex flex-col gap-2.5 px-[18px] py-4 text-[13px]')} style={{ animationDelay: '60ms' }}>
          <div className="flex items-center justify-between gap-3">
            <p className={label}>Sent copies</p>
            <button className="cursor-pointer text-xs text-accent hover:text-accent-strong disabled:cursor-not-allowed disabled:opacity-45" disabled={!ok || unsaved} onClick={freezeCopy}
              title="Save a read-only copy of exactly these files, e.g. when you send an updated version">
              + Freeze a copy
            </button>
          </div>
          {app.sent.length === 0 ? (
            <p className="text-muted">When you mark this application <strong>applied</strong>, TailorbirdCV keeps a read-only copy of exactly what you sent. Later edits and rebuilds never change it.</p>
          ) : (
            app.sent.map((c) => (
              <div key={c.id} className="flex flex-col gap-1.5 rounded-lg border border-rule px-2.5 py-2">
                <p className="text-xs text-muted">{fmtDate(c.created)} · {c.reason}{c.pages ? ` · ${c.pages} page${c.pages > 1 ? 's' : ''}` : ''}</p>
                <div className="flex flex-wrap gap-1.5">
                  {c.files.filter((f) => /\.(pdf|docx)$/.test(f)).map((f) => (
                    <a key={f} href={api.sentFileUrl(app.id, c.id, f, true)} className={`${chip} hover:bg-accent-soft hover:text-accent`}>↓ {f.split('.').pop()}</a>
                  ))}
                  <button className={`${chip} cursor-pointer hover:bg-accent-soft hover:text-accent`} onClick={() => api.reveal(app.id, c.id).catch((e) => setRevealError((e as Error).message))}
                    title="Opens this sent copy's folder, read-only">{showInFolder(settings?.platform)}</button>
                </div>
                {Object.entries(c.fingerprints ?? {}).filter(([f]) => f.endsWith('.pdf')).map(([f, fp]) => (
                  <p key={f} className="font-mono text-[11px] text-faint" title={`SHA-256 of the PDF sent: ${fp.sha256}`}>
                    PDF SHA-256 <span className="select-all">{fp.sha256.slice(0, 16)}</span>…
                  </p>
                ))}
              </div>
            ))
          )}
        </section>

        {docx && <StyleCoach app={app} />}

        {docx && (
          <div className="animate-rise flex flex-col gap-1 rounded-lg border border-rule bg-[#eef1f5] px-4 py-3.5 text-[13px] text-muted">
            <p className="font-medium text-ink">Before you send it</p>
            <p>Read it once, end to end. The fact-check guarantees numbers and names, but only you can confirm the emphasis sounds like you.</p>
          </div>
        )}
      </aside>

      <div className="animate-rise flex min-w-0 flex-col gap-2" style={{ animationDelay: '80ms' }}>
        {pdf ? (
          <a href={api.fileUrl(app.id, pdf)} target="_blank" rel="noreferrer" className="self-start text-[13px] text-muted hover:text-accent">Open the PDF in a new tab ↗</a>
        ) : (
          <p className="text-[13px] text-muted">{app.tailored ? 'An approximate preview. Build to see the exact PDF.' : ''}</p>
        )}
        <div className="flex justify-center rounded-lg border border-rule bg-lane p-3 sm:p-7">
          {pdf ? (
            <iframe
              key={app.meta.updated}
              title="PDF preview"
              src={api.fileUrl(app.id, pdf)}
              className={cx('aspect-[1/1.414] w-full max-w-[760px] bg-white shadow-[0_8px_24px_-12px_rgb(14_20_34/0.35)] transition-opacity', stale && 'opacity-55')}
            />
          ) : app.tailored ? (
            <PagePreview t={app.tailored} p={profile.profile} />
          ) : (
            <p className="py-24 text-base text-faint">The PDF preview appears here.</p>
          )}
        </div>
      </div>
    </div>
  )
}

/** Read-only page mock of the saved tailored resume, shown until a PDF exists. */
function PagePreview({ t, p }: { t: Tailored; p: Profile }) {
  const headline = p.headlines.find((h) => h.id === t.headline)?.text
  const h = (s: string) => <p className="border-b border-ink pb-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink">{s}</p>
  const li = (key: string | number, text: string, italic = false, bullet = true) => (
    <p key={key} className="flex gap-1.5 text-[11px] leading-[1.4] text-body">
      {bullet && <span className="text-faint">•</span>}<span className={cx(italic && 'italic text-muted')}>{text}</span>
    </p>
  )
  const items = (key: 'projects' | 'education' | 'extras', ids: { id: string; text?: string }[]) =>
    ids.map(({ id, text }) => {
      const x = p[key].find((y) => y.id === id)
      return x && <p key={id} className="flex gap-1.5 text-[11px] leading-[1.4] text-body"><span className="text-faint">•</span><span><span className="font-semibold">{x.label}</span> {text ?? x.text}</span></p>
    })
  return (
    <div className="flex w-full max-w-[640px] flex-col gap-3 bg-white px-5 py-7 shadow-[0_8px_24px_-12px_rgb(14_20_34/0.35)] sm:px-12 sm:py-11"
      style={{ fontFamily: "Calibri, Carlito, sans-serif" }} aria-label="Approximate resume preview">
      <div className="flex flex-col gap-0.5 text-center">
        <p className="text-lg font-semibold uppercase tracking-[0.04em] text-ink">{p.contact.name}</p>
        <p className="text-[10px] text-muted">{[p.contact.location, p.contact.phone, p.contact.email, ...p.contact.links.map((l) => l.text)].filter(Boolean).join(' · ')}</p>
        {headline && <p className="mt-1 text-[11px] font-semibold text-accent">{headline}</p>}
      </div>
      {t.summary && <div className="flex flex-col gap-[3px]">{h('Summary')}{li('s', t.summary.text, false, false)}</div>}
      {t.highlights.length > 0 && <div className="flex flex-col gap-[3px]">{h('Career highlights')}{t.highlights.map((c, i) => li(i, c.text))}</div>}
      {t.competencies.length > 0 && (
        <div className="flex flex-col gap-[3px]">
          {h('Core competencies')}
          {t.competencies.map((g, i) => <p key={i} className="text-[11px] leading-[1.4] text-body"><span className="font-semibold">{g.label}:</span> {g.items.join(' · ')}</p>)}
        </div>
      )}
      <div className="flex flex-col gap-[3px]">
        {h('Professional experience')}
        {t.experience.map((tr) => {
          const role = p.roles.find((r) => r.id === tr.role)
          if (!role) return null
          return (
            <div key={tr.role} className="flex flex-col gap-px">
              <div className="mt-[3px] flex justify-between gap-2 text-[11px] text-ink"><span><span className="font-semibold">{role.employer}</span> · {role.location}</span><span className="shrink-0 text-muted">{role.dates}</span></div>
              <p className="text-[11px] font-semibold text-accent">{role.title}</p>
              {tr.scope && li('scope', tr.scope.text, role.scope?.italic !== false, false)}
              {tr.bullets.map((b, j) => li(j, b.text))}
              {tr.sub_roles.map((sr) => {
                const item = role.sub_roles.find((s) => s.id === sr.id)
                return <p key={sr.id} className="flex gap-1.5 text-[11px] leading-[1.4] text-body"><span className="text-faint">•</span><span><span className="font-semibold">{item?.label}</span> {sr.text?.text ?? item?.text}</span></p>
              })}
            </div>
          )
        })}
      </div>
      {t.projects.length > 0 && <div className="flex flex-col gap-[3px]">{h('Projects & community leadership')}{items('projects', t.projects.map((x) => ({ id: x.id, text: x.text?.text })))}</div>}
      {t.education.length > 0 && <div className="flex flex-col gap-[3px]">{h('Education & certifications')}{items('education', t.education.map((id) => ({ id })))}</div>}
      {t.extras.length > 0 && <div className="flex flex-col gap-[3px]">{h('Awards & languages')}{items('extras', t.extras.map((id) => ({ id })))}</div>}
    </div>
  )
}
