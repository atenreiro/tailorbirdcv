import { useEffect, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type AppSummary } from '../api'
import { cx, useTitle } from '../lib'
import { ErrorNote, Spinner, StatusPill } from '../ui'

const STOP = new Set(['and', 'the', 'of', 'for', 'in', 'a', 'an', 'to', 'with', 'senior', 'lead', 'head', 'manager', 'vp', 'director', 'engineer'])
const words = (t: string) => new Set(t.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2 && !STOP.has(w)))

/** A quick guess from the first line ("Role — Company", "Role at Company"); the analysis confirms it. */
function detect(jd: string, apps: AppSummary[]) {
  const first = jd.trim().split('\n')[0]?.replace(/^#+\s*/, '') ?? ''
  const m = first.match(/^(.{3,90}?)\s+(?:[—–-]|at|@)\s+([^,|·]{2,60})/i)
  if (!m) return null
  const role = m[1].trim(), company = m[2].trim()
  const mine = words(`${role} ${jd.slice(0, 1500)}`)
  const similar = apps
    .map((a) => ({ a, score: (a.company.toLowerCase() === company.toLowerCase() ? 5 : 0) + [...words(a.role)].filter((w) => mine.has(w)).length }))
    .filter((x) => x.score >= 2).sort((x, y) => y.score - x.score).slice(0, 2).map((x) => x.a)
  return { role, company, similar }
}

const HOW = [
  ['Analyze', 'Industry lens, IC vs manager track, every requirement matched to your evidence.'],
  ['Ask', 'Gaps become questions for you — nothing is assumed.'],
  ['Compose', 'Reordered and rephrased from your profile, every claim cited.'],
  ['Verify', 'A fact-check blocks any number, tool or name not in your evidence.'],
  ['Export', 'Your exact resume design, as .docx and .pdf.'],
]
const MAC = typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad/.test((navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform || navigator.userAgent)
const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'

export default function NewApplication() {
  useTitle(['New tailoring'])
  const nav = useNavigate()
  const [mode, setMode] = useState<'paste' | 'url'>('url')
  const [jd, setJd] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [apps, setApps] = useState<AppSummary[]>([])
  useEffect(() => { api.applications().then(setApps).catch(() => {}) }, [])

  const paste = mode === 'paste'
  const ready = paste ? jd.trim().length >= 100 : /^https?:\/\//.test(url.trim())
  const typed = paste ? jd.trim().length > 0 : url.trim().length > 0

  async function submit() {
    if (!ready || busy) return
    setBusy(true)
    setError(null)
    try {
      const { id } = await api.create(paste ? { jd } : { jd: '', url: url.trim() })
      nav(`/a/${id}?analyze=1`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  // ⌘/Ctrl+Enter in the description (Enter alone adds a line); Enter in the URL field.
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && (!paste || e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit() }
  }

  const det = paste ? detect(jd, apps) : null
  const similar = det?.similar ?? []

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <div className="flex flex-col gap-2.5">
          <h1 className="font-display text-[48px] leading-[0.92] tracking-[-0.02em] text-ink sm:text-[64px]">New tailoring</h1>
          <p className="text-lg text-body">What role are we going after?</p>
        </div>
        <div role="group" aria-label="Job description source" className="inline-flex h-10 gap-0.5 rounded-lg bg-lane p-[3px]">
          {(['url', 'paste'] as const).map((m) => (
            <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}
              className={cx('h-[34px] cursor-pointer rounded-md px-3.5 font-medium transition-colors',
                mode === m ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(14_20_34/0.12)]' : 'text-muted hover:text-ink')}>
              {m === 'paste' ? 'Paste the description' : 'Fetch from a URL'}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <section className="flex min-w-0 flex-[1_1_640px] flex-col gap-4">
          {paste ? (
            <div className="animate-rise overflow-hidden rounded-[14px] border border-rule bg-sheet focus-within:border-accent">
              <textarea
                className="block min-h-[420px] w-full resize-y border-0 bg-transparent px-7 py-6 text-base leading-[1.6] text-ink outline-none"
                placeholder="Paste the full job description here — title, company, responsibilities, requirements…" maxLength={60000}
                aria-label="Job description" value={jd} onChange={(e) => setJd(e.target.value)} onKeyDown={onKey} autoFocus />
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-wash px-7 py-2.5 font-mono text-xs text-faint">
                <span>{jd.trim().split(/\s+/).filter(Boolean).length} words</span>
                {jd.trim().length > 0 && jd.trim().length < 100 && <span className="text-[#7a4700]">a bit short — paste the full text</span>}
              </div>
            </div>
          ) : (
            <div className="animate-rise flex flex-col gap-3 rounded-[14px] border border-rule bg-sheet px-7 py-6">
              <label htmlFor="jd-url" className={cx(label, 'text-muted')}>Job posting URL</label>
              <input id="jd-url" className="field h-12 bg-wash px-3.5 font-mono text-sm focus:bg-sheet" placeholder="https://careers.example.com/jobs/12345"
                value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={onKey} autoFocus />
              <p className="max-w-[640px] text-sm leading-[1.5] text-muted text-pretty">Reads Lever, Greenhouse and Ashby postings directly. Other career sites are rendered in a headless browser if needed (can take ~15 s). Pages behind a login, like LinkedIn, can’t be fetched, so paste the text for those.</p>
            </div>
          )}

          <ErrorNote error={error} onDismiss={() => setError(null)} />

          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <button onClick={submit} aria-disabled={!ready || busy}
              className={cx('inline-flex h-11 items-center gap-2.5 rounded-lg px-5 text-[15px] font-semibold text-white transition-colors',
                ready || busy ? 'bg-accent' : 'bg-[#c3cad6]', ready && !busy ? 'cursor-pointer hover:bg-accent-strong' : 'cursor-default')}>
              {busy && <Spinner />}{busy ? (paste ? 'Saving…' : 'Fetching the posting…') : 'Analyze this role →'}
            </button>
            <span className="text-sm text-muted">Company and title are detected automatically.</span>
            <span className="ml-auto hidden font-mono text-[11px] text-faint sm:inline">{paste ? `${MAC ? '⌘' : 'Ctrl'} Enter to analyze` : 'Enter to fetch'}</span>
          </div>
        </section>

        <aside className="flex min-w-[min(300px,100%)] flex-[0_1_380px] flex-col gap-4">
          <section className="flex flex-col gap-4 rounded-[14px] border border-rule bg-sheet px-[22px] py-5">
            <div className="flex items-center justify-between gap-2.5">
              <p className={cx(label, 'text-accent')}>Detected</p>
              <span className={cx('flex items-center gap-1.5 font-mono text-[11px]', det ? 'text-accent' : 'text-faint')}>
                <span className={cx('size-1.5 rounded-full', det ? 'bg-accent' : 'bg-faint')} />
                {det ? 'First guess' : typed ? 'Not found yet' : 'Waiting'}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <p className={cx('font-display text-[30px] leading-none tracking-[-0.01em]', det ? 'text-ink' : 'text-[#c3cad6]')}>{det?.company ?? 'Company'}</p>
              <p className={cx('text-[15px]', det ? 'text-body' : 'text-[#aeb7c6]')}>{det?.role ?? 'Role title'}</p>
            </div>
            <p className="text-[13px] leading-[1.45] text-faint text-pretty">
              {det ? 'A first guess from the opening line. The analysis confirms both.'
                : paste ? 'Starts with a line like “Role — Company” or “Role at Company”.' : 'Read from the posting when it’s fetched.'}
            </p>
          </section>

          <section className="overflow-hidden rounded-[14px] border border-rule bg-sheet">
            <div className="flex items-baseline justify-between gap-2.5 px-[22px] pb-3 pt-4">
              <p className={cx(label, 'text-muted')}>Similar past applications</p>
              {det && <span className="font-mono text-xs text-faint">{similar.length}</span>}
            </div>
            {similar.map((a) => (
              <Link key={a.id} to={`/a/${a.id}`} className="flex items-center gap-3 border-t border-[#eef0f4] px-[22px] py-3 text-ink hover:bg-wash hover:text-ink">
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold">{a.company}</span>
                  <span className="block truncate text-[13px] text-muted">{a.role}</span>
                </span>
                <StatusPill status={a.status} className="flex-none" />
              </Link>
            ))}
            {similar.length === 0 && (
              <p className="px-[22px] pb-[18px] pt-1 text-[13px] text-faint text-pretty">
                {det ? 'No close match among your past applications.' : 'Past applications with the same company or a similar title appear here, so you can reuse answers.'}
              </p>
            )}
          </section>
        </aside>
      </div>

      <section className="flex flex-col gap-3.5">
        <p className={cx(label, 'text-muted')}>How it works</p>
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
          {HOW.map(([t, d], i) => (
            <div key={t} className="flex flex-col gap-2 rounded-xl bg-lane px-[18px] py-4">
              <span className="font-mono text-xs font-medium text-accent">0{i + 1}</span>
              <p className="font-display text-xl text-ink">{t}</p>
              <p className="text-[13px] leading-[1.45] text-body text-pretty">{d}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
