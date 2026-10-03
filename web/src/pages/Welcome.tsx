import { useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type ImportDraft, type Profile } from '../api'
import { cx, useTitle } from '../lib'
import { markHasProfile, useLeaveWelcomeIfSetUp } from '../setup'
import { ErrorNote, Spinner } from '../ui'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'
const card = 'rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7'

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(new Error('That file could not be read.'))
    reader.readAsDataURL(file)
  })
}

/** One extracted line; amber when it wasn't found word-for-word in the original file. */
function Line({ path, flagged, children }: { path: string; flagged: Set<string>; children: ReactNode }) {
  const off = flagged.has(path)
  return (
    <li className={cx('rounded-md px-2 py-1 text-[13px] leading-[1.45]', off ? 'bg-warn-soft text-ink' : 'text-body')}>
      {children}
      {off && <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.06em] text-warn">check: not word-for-word in your file</span>}
    </li>
  )
}

function Section({ title, children, count }: { title: string; children: ReactNode; count: number }) {
  if (!count) return null
  return (
    <section className="flex flex-col gap-1.5">
      <p className={cx(label, 'text-muted')}>{title}</p>
      <ul className="flex flex-col gap-0.5">{children}</ul>
    </section>
  )
}

function Review({ draft, onSave, onRestart, busy }: { draft: ImportDraft; onSave: () => void; onRestart: () => void; busy: boolean }) {
  const p: Profile = draft.profile
  const flagged = new Set(draft.unverified)
  const bullets = p.roles.reduce((n, r) => n + r.achievements.length, 0)
  return (
    <div className="flex flex-col gap-6">
      <div className={cx(card, 'flex flex-col gap-2')}>
        <p className={cx(label, 'text-accent')}>Step 2 of 2 · Check what was read</p>
        <h2 className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Is this your resume?</h2>
        <p className="max-w-[720px] text-sm leading-[1.5] text-muted text-pretty">
          This is what AutoCV read: {p.roles.length} role{p.roles.length === 1 ? '' : 's'}, {bullets} achievement{bullets === 1 ? '' : 's'},
          {' '}{p.skills.length} skill group{p.skills.length === 1 ? '' : 's'}. Everything AutoCV writes later comes only from this
          profile, so check it. {flagged.size > 0
            ? <strong className="text-warn">{flagged.size} item{flagged.size > 1 ? 's' : ''} didn’t match your file word-for-word (highlighted): fix or remove them after saving.</strong>
            : 'Every line matched your file word-for-word.'}
        </p>
      </div>

      <div className={cx(card, 'flex flex-col gap-5')}>
        <div className="flex flex-col gap-1">
          <ul><Line path="contact.name" flagged={flagged}><span className="font-display text-[26px] text-ink">{p.contact.name}</span></Line></ul>
          {p.headlines.map((h, i) => <ul key={h.id}><Line path={`headlines[${i}]`} flagged={flagged}><span className="font-semibold text-accent">{h.text}</span></Line></ul>)}
          <p className="px-2 text-[13px] text-muted">{[p.contact.location, p.contact.phone, p.contact.email, ...p.contact.links.map((l) => l.text)].filter(Boolean).join(' · ')}</p>
        </div>
        <Section title="Summary" count={p.summary_facts.length}>
          {p.summary_facts.map((f, i) => <Line key={f.id} path={`summary_facts[${i}]`} flagged={flagged}>{f.text}</Line>)}
        </Section>
        <Section title="Highlights" count={p.highlights.length}>
          {p.highlights.map((f, i) => <Line key={f.id} path={`highlights[${i}]`} flagged={flagged}>• {f.text}</Line>)}
        </Section>
        <Section title="Skills" count={p.skills.length}>
          {p.skills.map((g) => (
            <li key={g.category} className="px-2 py-1 text-[13px] text-body">
              <strong className="text-ink">{g.category}:</strong>{' '}
              {g.items.map((item, j) => (
                <span key={item} className={cx(flagged.has(`skills.${g.category}[${j}]`) && 'rounded bg-warn-soft px-1')}>{item}{j < g.items.length - 1 ? ' · ' : ''}</span>
              ))}
            </li>
          ))}
        </Section>
        <Section title="Experience" count={p.roles.length}>
          {p.roles.map((r) => (
            <li key={r.id} className="flex flex-col gap-0.5 py-1.5">
              <ul>
                <Line path={`${r.id}.employer`} flagged={flagged}>
                  <span className="font-semibold text-ink">{r.employer}{r.location ? `, ${r.location}` : ''}</span>
                  <span className="float-right font-mono text-[11px] text-muted">{r.dates}</span>
                </Line>
                <Line path={`${r.id}.title`} flagged={flagged}><span className="font-semibold text-accent">{r.title}</span></Line>
                {r.scope && <Line path={r.scope.id} flagged={flagged}><em>{r.scope.text}</em></Line>}
                {r.achievements.map((a) => <Line key={a.id} path={a.id} flagged={flagged}>• {a.text}</Line>)}
                {r.sub_roles.map((s) => <Line key={s.id} path={s.id} flagged={flagged}>• <strong>{s.label}</strong> {s.text}</Line>)}
              </ul>
            </li>
          ))}
        </Section>
        {(['projects', 'education', 'extras'] as const).map((key) => (
          <Section key={key} title={key === 'extras' ? 'Awards, languages & more' : key[0].toUpperCase() + key.slice(1)} count={p[key].length}>
            {p[key].map((item) => <Line key={item.id} path={item.id} flagged={flagged}>• <strong>{item.label}</strong> {item.text}</Line>)}
          </Section>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button className="btn btn-primary" onClick={onSave} disabled={busy}>{busy && <Spinner />}Save as my profile</button>
        <button className="btn" onClick={onRestart} disabled={busy}>Start over</button>
        <span className="text-[13px] text-muted">You can edit everything afterwards under Master profile.</span>
      </div>
    </div>
  )
}

export default function Welcome() {
  useTitle(['Welcome'])
  useLeaveWelcomeIfSetUp()
  const nav = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<'file' | 'paste'>('file')
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<ImportDraft | null>(null)
  const [busy, setBusy] = useState<'read' | 'save' | 'blank' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [blank, setBlank] = useState({ name: '', location: '', headline: '' })

  const done = () => { markHasProfile(); nav('/profile') }
  const read = async () => {
    setBusy('read')
    setError(null)
    try {
      setDraft(await api.importProfile(mode === 'paste' ? { text } : { filename: file!.name, data: await toBase64(file!) }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const save = async (body: Parameters<typeof api.createProfile>[0], kind: 'save' | 'blank') => {
    setBusy(kind)
    setError(null)
    try {
      await api.createProfile(body)
      done()
    } catch (e) {
      setError((e as Error).message)
      setBusy(null)
    }
  }
  const canRead = mode === 'paste' ? text.trim().length >= 80 : !!file

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-col gap-2.5">
        <h1 className="font-display text-[48px] leading-[0.92] tracking-[-0.02em] text-ink sm:text-[64px]">Welcome to AutoCV</h1>
        <p className="max-w-[760px] text-lg text-body text-pretty">
          Tailor your resume to each job without inventing anything. It starts with your master profile: everything
          your resume can say, read from the resume you already have.
        </p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {draft ? (
        <Review draft={draft} busy={busy === 'save'} onSave={() => save({ profile: draft.profile }, 'save')}
          onRestart={() => { setDraft(null); setError(null) }} />
      ) : (
        <div className="flex flex-wrap items-start gap-6">
          <section className={cx(card, 'animate-rise flex min-w-0 flex-[1_1_560px] flex-col gap-4')}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex flex-col gap-1.5">
                <p className={cx(label, 'text-accent')}>Step 1 of 2 · Recommended</p>
                <h2 className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Import your resume</h2>
              </div>
              <div role="group" aria-label="Import from" className="inline-flex h-9 gap-0.5 rounded-lg bg-lane p-[3px]">
                {(['file', 'paste'] as const).map((m) => (
                  <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}
                    className={cx('h-[30px] cursor-pointer rounded-md px-3 text-[13px] font-medium transition-colors',
                      mode === m ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(14_20_34/0.12)]' : 'text-muted hover:text-ink')}>
                    {m === 'file' ? 'Upload a file' : 'Paste text'}
                  </button>
                ))}
              </div>
            </div>
            {mode === 'file' ? (
              <button type="button" onClick={() => fileInput.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setFile(f) }}
                className="flex min-h-[150px] cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-rule bg-wash px-6 text-center hover:border-accent">
                <span className="font-display text-xl text-ink">{file ? file.name : 'Drop your resume here, or click to choose'}</span>
                <span className="text-[13px] text-muted">{file ? `${Math.max(1, Math.round(file.size / 1024))} KB · click to change` : 'Word (.docx), PDF, or plain text'}</span>
                <input ref={fileInput} type="file" className="hidden" accept=".docx,.pdf,.txt,.md,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </button>
            ) : (
              <textarea className="field min-h-[220px] resize-y font-[inherit] leading-[1.5]" value={text} onChange={(e) => setText(e.target.value)}
                placeholder="Paste the full text of your resume…" aria-label="Resume text" />
            )}
            <p className="text-[13px] leading-[1.5] text-muted text-pretty">
              The AI copies your resume into structured sections word-for-word; it doesn’t rewrite anything. You review the
              result before it’s saved. Takes about a minute.
            </p>
            <div>
              <button className="btn btn-primary" onClick={read} disabled={!canRead || !!busy}>
                {busy === 'read' && <Spinner />}{busy === 'read' ? 'Reading your resume…' : 'Read my resume'}
              </button>
            </div>
          </section>

          <aside className="flex min-w-[min(300px,100%)] flex-[0_1_380px] flex-col gap-4">
            <section className={cx(card, 'flex flex-col gap-3')}>
              <p className={cx(label, 'text-muted')}>Or start blank</p>
              <p className="text-[13px] text-muted">Type your profile in yourself under Master profile.</p>
              {(['name', 'headline', 'location'] as const).map((k) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[13px] font-semibold text-ink">{k === 'name' ? 'Your name' : k === 'headline' ? 'Headline (e.g. your current title)' : 'Location'}</span>
                  <input className="field" value={blank[k]} maxLength={k === 'headline' ? 240 : 120}
                    onChange={(e) => setBlank((b) => ({ ...b, [k]: e.target.value }))} />
                </label>
              ))}
              <div>
                <button className="btn" disabled={!blank.name.trim() || !blank.headline.trim() || !!busy}
                  onClick={() => save({ blank }, 'blank')}>{busy === 'blank' && <Spinner />}Create a blank profile</button>
              </div>
            </section>
            <section className={cx(card, 'flex flex-col gap-2 text-[13px] text-muted')}>
              <p className={cx(label, 'text-muted')}>Before you start</p>
              <p>Your profile and applications stay on this computer. Only what the AI needs to read or write your resume is sent to Claude.</p>
              <p><Link to="/settings" className="text-accent hover:text-accent-strong">Settings</Link>: tell AutoCV what roles you’re targeting, and check that the AI and PDF engines are ready.</p>
            </section>
          </aside>
        </div>
      )}
    </div>
  )
}
