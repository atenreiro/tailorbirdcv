import { useEffect, useState } from 'react'
import { api, isLetterFile, type CoverLetter, type Issue, type LetterKind, type LetterSentence, type LetterTone } from '../../api'
import { cx } from '../../lib'
import { pdfEngineName, useSettings } from '../../settings'
import { ErrorNote, SaveDock } from '../../ui'
import type { StepProps } from '../Workspace'
import { btn, btnPrimary, btnSm, label, sheetCard } from './v3'

const TONES: { id: LetterTone; name: string; about: string }[] = [
  { id: 'formal', name: 'Formal', about: 'Measured and courteous. The safe choice for banks, law, government.' },
  { id: 'warm', name: 'Warm', about: 'Friendly and personable, still professional. Good for startups and mission-led teams.' },
  { id: 'direct', name: 'Direct', about: 'Short, plain sentences that lead with outcomes.' },
]
const KINDS: { id: LetterKind; name: string; about: string }[] = [
  { id: 'evidence', name: 'About you', about: 'States your experience; must cite the evidence it uses.' },
  { id: 'posting', name: 'From the posting', about: 'Only what the job posting says about the company or role.' },
  { id: 'link', name: 'Joining sentence', about: 'Short, no facts. One per paragraph at most.' },
]
// The same words TailorbirdCV prints (render.LETTER_CLOSINGS).
const CLOSINGS: Record<LetterTone, [string, string]> = {
  formal: ['Thank you for your time and consideration. I would welcome the opportunity to discuss how I could contribute to {company}.', 'Sincerely,'],
  warm: ['Thank you for reading. I’d love to talk about how I could help {company} with this work.', 'Kind regards,'],
  direct: ['I’d welcome a conversation about the role. Thank you for your time.', 'Best regards,'],
}
const MAX_WORDS = 330  // factcheck.LETTER_MAX_WORDS

const pathOf = (p: number, s: number) => `paragraphs[${p}].sentences[${s}]`
const words = (l: CoverLetter) => l.paragraphs.reduce((n, p) => n + p.sentences.reduce((m, s) => m + s.text.trim().split(/\s+/).filter(Boolean).length, 0), 0)

export default function CoverLetterStep({ app, profile, setApp, run, memo, setMemo, go }: StepProps) {
  const settings = useSettings()
  const company = app.analysis?.company || app.meta.company
  const role = app.analysis?.role || app.meta.role
  const saved = app.letter
  const draft = memo.letter?.draft ?? saved
  const dirty = !!memo.letter
  const [tone, setTone] = useState<LetterTone>(saved?.tone ?? 'formal')
  const [recipient, setRecipient] = useState(saved?.recipient ?? '')
  const [notes, setNotes] = useState<string[]>(app.letter_notes.map((n) => n.id))
  const [focus, setFocus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { if (!flash) return; const t = setTimeout(() => setFlash(null), 2500); return () => clearTimeout(t) }, [flash])

  const write = () =>
    run('Writing your cover letter', [
      'Choosing the evidence that fits this role…',
      'Reading what the posting says about the company…',
      'Checking every sentence against your profile…',
    ], async () => { setApp(await api.writeLetter(app.id, { tone, recipient, notes })); setMemo((m) => ({ ...m, letter: null })) })

  if (!draft) {
    return (
      <div className={cx(sheetCard, 'animate-rise flex max-w-[860px] flex-col gap-5 px-6 py-6 sm:px-8')}>
        <div className="flex flex-col gap-2">
          <p className={label}>Cover letter</p>
          <h2 className="font-display text-[32px] leading-none tracking-[-0.01em] text-ink">One page, the same facts as your resume</h2>
          <p className="max-w-[680px] text-[15px] leading-[1.55] text-body text-pretty">
            The AI writes the body: why you fit this role, with your strongest evidence for its must-haves, and what the
            posting says about {company}. Every sentence is checked like your resume. Your header, the greeting, the closing
            line and the sign-off come from TailorbirdCV.
          </p>
        </div>
        <LetterOptions tone={tone} setTone={setTone} recipient={recipient} setRecipient={setRecipient} />
        {app.letter_notes.length > 0 && (
          <fieldset className="flex flex-col gap-2">
            <legend className={cx(label, 'mb-1')}>From the hiring-manager review</legend>
            {app.letter_notes.map((n) => (
              <label key={n.id} className="flex cursor-pointer items-start gap-2.5 text-sm text-body">
                <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={notes.includes(n.id)}
                  onChange={(e) => setNotes((x) => e.target.checked ? [...x, n.id] : x.filter((i) => i !== n.id))} />
                <span className="text-pretty">{n.text} <span className="text-muted">(addressed only if your evidence supports it)</span></span>
              </label>
            ))}
          </fieldset>
        )}
        <div><button className={btnPrimary} onClick={write}>Write cover letter</button></div>
      </div>
    )
  }

  const report = app.letter_report
  const issuesAt = (path: string): Issue[] => (dirty ? [] : report?.errors.filter((e) => e.where === path) ?? [])
  const general = dirty ? [] : report?.errors.filter((e) => !e.where.startsWith('paragraphs[')) ?? []
  const update = (fn: (d: CoverLetter) => void) => setMemo((m) => {
    const next = structuredClone(m.letter?.draft ?? saved!) as CoverLetter
    fn(next)
    return { ...m, letter: { draft: next, rev: (m.letter?.rev ?? 0) + 1 } }
  })
  const [fp, fs] = focus ? (focus.match(/\d+/g) ?? []).map(Number) : [-1, -1]
  const selected: LetterSentence | undefined = draft.paragraphs[fp]?.sentences[fs]
  const files = app.files.filter(isLetterFile)
  const pdf = files.find((f) => f.endsWith('.pdf'))
  const docx = files.find((f) => f.endsWith('.docx'))
  const count = words(draft)
  const engine = pdfEngineName(settings)
  const [closing, sign] = CLOSINGS[draft.tone]
  const errorCount = report?.errors.length ?? 0

  async function save() {
    const sentRev = memo.letter?.rev
    setBusy(true); setError(null)
    try {
      setApp(await api.saveLetter(app.id, draft!))
      setMemo((m) => (m.letter && m.letter.rev === sentRev ? { ...m, letter: null } : m))
      setFlash('Saved and checked')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const build = () => run('Typesetting your cover letter', ['Rendering it in your resume’s design…', `Converting to PDF${engine ? ` with ${engine}` : ''}…`, 'Checking it fits one page…'],
    async () => setApp(await api.buildLetter(app.id)), false)
  const rewrite = () => {
    if (!window.confirm('Write a new letter with the AI? This replaces the current one.')) return
    setMemo((m) => ({ ...m, letter: null }))
    void write()
  }
  const remove = () => {
    if (!window.confirm('Delete this cover letter? The application will be sent with the resume only.')) return
    setBusy(true)
    api.deleteLetter(app.id).then((a) => { setMemo((m) => ({ ...m, letter: null })); setFocus(null); setApp(a) })
      .catch((e) => setError((e as Error).message)).finally(() => setBusy(false))
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
      <article className={cx(sheetCard, 'animate-rise flex flex-col gap-3.5 px-6 py-7 text-[15px] leading-[1.6] text-body sm:px-10')} aria-label="Cover letter">
        <p className="font-display text-2xl leading-tight text-ink">{profile.profile.contact.name}</p>
        <p className="text-muted">{[draft.recipient, company, app.analysis?.location].filter(Boolean).join(' · ')}</p>
        {role && <p className="font-semibold text-ink">Re: {role}</p>}
        <p>{draft.recipient ? `Dear ${draft.recipient},` : `Dear ${company} hiring team,`}</p>
        {draft.paragraphs.map((p, pi) => (
          <p key={pi}>
            {p.sentences.map((s, si) => {
              const path = pathOf(pi, si)
              const bad = issuesAt(path).length > 0
              return (
                <span key={si}>
                  <button onClick={() => setFocus(path)} title={KINDS.find((k) => k.id === s.kind)?.name}
                    className={cx('cursor-pointer rounded-[3px] text-left transition-colors hover:bg-wash',
                      focus === path && 'bg-accent-soft text-ink',
                      bad && 'underline decoration-bad decoration-wavy underline-offset-4',
                      s.kind === 'posting' && 'italic')}>
                    {s.text}
                  </button>{' '}
                </span>
              )
            })}
          </p>
        ))}
        <p className="text-muted">{closing.replace('{company}', company || 'your team')}</p>
        <p className="text-muted">{sign}<br />{profile.profile.contact.name}</p>
        <p className="border-t border-line pt-3 text-xs text-faint">
          The greeting, closing line and sign-off are written by TailorbirdCV. Sentences in italics come from the posting.
          Click any sentence to edit it.
        </p>
      </article>

      <aside className="flex flex-col gap-4 lg:sticky lg:top-20">
        <ErrorNote error={error} onDismiss={() => setError(null)} />
        <section className={cx(sheetCard, 'flex flex-col gap-2 px-5 py-4')}>
          <p className={label}>Fact-check</p>
          {dirty ? <p className="text-sm text-warn">Unsaved edits: save to check them.</p>
            : errorCount ? <p className="text-sm font-semibold text-bad">{errorCount} to fix before building</p>
            : <p className="text-sm font-semibold text-ok">Every sentence checks out</p>}
          {general.map((e, i) => <p key={i} className="text-[13px] text-bad">{e.message}</p>)}
          <p className={cx('font-mono text-xs', count > MAX_WORDS ? 'text-bad' : 'text-faint')}>{count} of {MAX_WORDS} words · one page</p>
        </section>

        {selected && (
          <section className={cx(sheetCard, 'animate-rise flex flex-col gap-3 px-5 py-4')} aria-label="Selected sentence">
            <div className="flex items-center justify-between">
              <p className={label}>Selected sentence</p>
              <button className="text-xs text-faint hover:text-ink" onClick={() => setFocus(null)} aria-label="Close">✕</button>
            </div>
            <SentenceEditor sentence={selected} evidence={profile.evidence} issues={issuesAt(focus!)}
              onChange={(s) => update((d) => { d.paragraphs[fp].sentences[fs] = s })} />
            <div className="flex flex-wrap gap-1 border-t border-line pt-2 text-xs">
              <button className="btn btn-ghost px-2 py-1 text-xs" disabled={fs === 0}
                onClick={() => { update((d) => { const s = d.paragraphs[fp].sentences; [s[fs - 1], s[fs]] = [s[fs], s[fs - 1]] }); setFocus(pathOf(fp, fs - 1)) }}>← Earlier</button>
              <button className="btn btn-ghost px-2 py-1 text-xs" disabled={fs === draft.paragraphs[fp].sentences.length - 1}
                onClick={() => { update((d) => { const s = d.paragraphs[fp].sentences; [s[fs + 1], s[fs]] = [s[fs], s[fs + 1]] }); setFocus(pathOf(fp, fs + 1)) }}>Later →</button>
              <button className="btn btn-ghost px-2 py-1 text-xs"
                onClick={() => { update((d) => { d.paragraphs[fp].sentences.splice(fs + 1, 0, { text: '', kind: 'evidence', sources: [] }) }); setFocus(pathOf(fp, fs + 1)) }}>+ Sentence after</button>
              <button className="btn btn-ghost ml-auto px-2 py-1 text-xs text-bad"
                onClick={() => { update((d) => { d.paragraphs[fp].sentences.splice(fs, 1); d.paragraphs = d.paragraphs.filter((p) => p.sentences.length) }); setFocus(null) }}>Remove</button>
            </div>
          </section>
        )}

        <section className={cx(sheetCard, 'flex flex-col gap-3 px-5 py-4')}>
          <LetterOptions compact tone={draft.tone} setTone={(t) => update((d) => { d.tone = t })}
            recipient={draft.recipient} setRecipient={(r) => update((d) => { d.recipient = r })} />
        </section>

        <section className={cx(sheetCard, 'flex flex-col gap-3 px-5 py-4')}>
          <p className={label}>Files</p>
          {files.length ? (
            <>
              {app.letter_stale && <p className="text-[13px] text-warn">Out of date: the letter or your profile changed after it was built.</p>}
              <div className="flex flex-wrap gap-2">
                {pdf && <a className={btnSm} href={api.fileUrl(app.id, pdf)} target="_blank" rel="noreferrer">PDF</a>}
                {docx && <a className={btnSm} href={api.fileUrl(app.id, docx, true)}>Word document</a>}
              </div>
            </>
          ) : <p className="text-[13px] text-muted">Not built yet. Build it to send it with your resume (Export freezes both).</p>}
          <div className="flex flex-wrap gap-2">
            <button className={btnPrimary} onClick={build} disabled={dirty || !!errorCount || busy}>
              {files.length ? 'Rebuild letter' : 'Build letter'}
            </button>
            {files.length > 0 && !app.letter_stale && <button className={btn} onClick={() => go('export')}>Go to Export →</button>}
          </div>
          <div className="flex flex-wrap gap-3 border-t border-line pt-3 text-[13px]">
            <button className="text-accent hover:text-accent-strong" onClick={rewrite} disabled={busy}>Rewrite with AI</button>
            <button className="text-bad hover:underline" onClick={remove} disabled={busy}>Delete letter</button>
          </div>
        </section>
      </aside>
      <SaveDock dirty={dirty} text="Unsaved letter edits" busy={busy} flash={flash} onSave={save}
        onDiscard={() => setMemo((m) => ({ ...m, letter: null }))} saveLabel="Save & check" />
    </div>
  )
}

function LetterOptions({ tone, setTone, recipient, setRecipient, compact }: {
  tone: LetterTone; setTone: (t: LetterTone) => void; recipient: string; setRecipient: (r: string) => void; compact?: boolean
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <p className={label}>Tone</p>
        <div role="group" aria-label="Tone" className="inline-flex h-9 w-fit gap-0.5 rounded-lg bg-lane p-[3px]">
          {TONES.map((t) => (
            <button key={t.id} aria-pressed={tone === t.id} onClick={() => setTone(t.id)}
              className={cx('h-[30px] cursor-pointer rounded-md px-3 text-[13px] font-medium transition-colors',
                tone === t.id ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(15_61_46/0.12)]' : 'text-muted hover:text-ink')}>{t.name}</button>
          ))}
        </div>
        {!compact && <p className="text-[13px] text-muted">{TONES.find((t) => t.id === tone)!.about}</p>}
      </div>
      <label className="flex max-w-[420px] flex-col gap-1 text-[13px] font-medium text-ink">
        <span>Hiring manager’s name <span className="font-normal text-muted">(optional)</span></span>
        <input className="field" value={recipient} onChange={(e) => setRecipient(e.target.value)} placeholder="e.g. Alex Morgan" maxLength={120} />
      </label>
    </div>
  )
}

function SentenceEditor({ sentence, evidence, issues, onChange }: {
  sentence: LetterSentence; evidence: Record<string, string>; issues: Issue[]; onChange: (s: LetterSentence) => void
}) {
  const options = Object.keys(evidence).filter((id) => !sentence.sources.includes(id))
  return (
    <div className="flex flex-col gap-2.5">
      <textarea className="field min-h-[88px] px-2.5 text-sm leading-[1.45]" value={sentence.text} aria-label="Sentence"
        onChange={(e) => onChange({ ...sentence, text: e.target.value })} />
      <label className="flex flex-col gap-1 text-[12px] font-medium text-muted">Kind
        <select className="field h-9 py-0 text-sm text-ink" value={sentence.kind}
          onChange={(e) => onChange({ ...sentence, kind: e.target.value as LetterKind, sources: e.target.value === 'evidence' ? sentence.sources : [] })}>
          {KINDS.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
        </select>
        <span className="font-normal">{KINDS.find((k) => k.id === sentence.kind)!.about}</span>
      </label>
      {sentence.kind === 'evidence' && (
        <>
          <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Cites</p>
          {sentence.sources.map((s) => (
            <div key={s} className="grid grid-cols-[minmax(0,100px)_minmax(0,1fr)_14px] items-start gap-2.5 text-xs">
              <span className={cx('break-all font-mono', evidence[s] ? 'text-accent' : 'text-bad')}>{s}</span>
              <span className="text-body">{evidence[s]?.split('\n')[0] ?? 'Unknown evidence id'}</span>
              <button className="cursor-pointer text-faint hover:text-bad" aria-label={`Remove source ${s}`}
                onClick={() => onChange({ ...sentence, sources: sentence.sources.filter((x) => x !== s) })}>×</button>
            </div>
          ))}
          <select className="chip w-auto max-w-full cursor-pointer self-start border-dashed border-rule bg-transparent hover:border-accent hover:text-accent"
            value="" aria-label="Add a source" onChange={(e) => e.target.value && onChange({ ...sentence, sources: [...sentence.sources, e.target.value] })}>
            <option value="">+ cite evidence</option>
            {options.map((id) => <option key={id} value={id}>{id}: {(evidence[id] ?? '').split('\n')[0].slice(0, 70)}</option>)}
          </select>
        </>
      )}
      {issues.map((i, n) => <p key={n} className="rounded-md bg-bad-soft px-2.5 py-1.5 text-[13px] text-bad">{i.message}</p>)}
    </div>
  )
}
