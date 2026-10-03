import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type AppSummary } from '../api'
import { cx, ErrorNote, Spinner } from '../ui'

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
    .filter((x) => x.score >= 2).sort((x, y) => y.score - x.score).slice(0, 2).map((x) => x.a.company)
  return { role, company, similar }
}

const HOW = [
  ['Analyze', 'Industry lens, IC vs manager track, every requirement matched to your evidence.'],
  ['Ask', 'Gaps become questions for you — nothing is assumed.'],
  ['Compose', 'Reordered and rephrased from your profile, every claim cited.'],
  ['Verify', 'A fact-check blocks any number, tool or name not in your evidence.'],
  ['Export', 'Your exact resume design, as .docx and .pdf.'],
]

export default function NewApplication() {
  const nav = useNavigate()
  const [mode, setMode] = useState<'paste' | 'url'>('paste')
  const [jd, setJd] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [apps, setApps] = useState<AppSummary[]>([])
  useEffect(() => { api.applications().then(setApps).catch(() => {}) }, [])

  const ready = mode === 'paste' ? jd.trim().length >= 100 : /^https?:\/\//.test(url.trim())

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const { id } = await api.create(mode === 'paste' ? { jd } : { jd: '', url: url.trim() })
      nav(`/a/${id}?analyze=1`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const det = mode === 'paste' ? detect(jd, apps) : null
  const dim = det ? 'text-ink' : 'text-faint'

  return (
    <div className="flex flex-wrap items-start gap-10">
      <div className="flex min-w-0 flex-[1_1_640px] flex-col gap-5">
        <div className="animate-rise flex flex-col gap-1.5">
          <p className="eyebrow">New tailoring</p>
          <h1 className="font-display text-[44px] leading-[0.95] sm:text-[56px] text-ink">What role are we going after?</h1>
        </div>

        <div className="animate-rise flex gap-1 rounded-lg border border-rule bg-wash p-1 text-sm" style={{ animationDelay: '60ms' }} role="tablist">
          {(['paste', 'url'] as const).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
              className={cx('flex-1 cursor-pointer rounded-lg px-4 py-1.5 transition', mode === m ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(23_23_23/0.08)]' : 'text-muted hover:text-ink')}>
              {m === 'paste' ? 'Paste the description' : 'Fetch from a URL'}
            </button>
          ))}
        </div>

        <div className="animate-rise" style={{ animationDelay: '120ms' }}>
          {mode === 'paste' ? (
            <div className="sheet rounded-lg">
              <textarea
                className="block min-h-[440px] w-full resize-y bg-transparent px-[26px] py-[22px] text-[16px] leading-[1.6] text-ink placeholder:text-faint focus:outline-none"
                placeholder="Paste the full job description here — title, company, responsibilities, requirements…"
                aria-label="Job description" value={jd} onChange={(e) => setJd(e.target.value)} autoFocus />
              <div className="flex items-center justify-between gap-3 border-t border-rule px-[26px] py-2 font-mono text-xs text-faint">
                <span>{jd.trim().split(/\s+/).filter(Boolean).length} words</span>
                {jd.trim().length > 0 && jd.trim().length < 100 && <span className="text-warn">a bit short — paste the full text</span>}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <input className="field px-3 py-2.5 font-mono text-sm" placeholder="https://careers.example.com/jobs/12345" aria-label="Job posting URL"
                value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && ready && !busy) void submit() }} autoFocus />
              <p className="max-w-[640px] text-[13px] text-muted text-pretty">Reads Lever, Greenhouse and Ashby postings (Binance careers included) directly. Other career sites are rendered in a headless browser if needed (can take ~15 s). Pages behind a login, like LinkedIn, can’t be fetched, so paste the text for those.</p>
            </div>
          )}
        </div>

        <ErrorNote error={error} onDismiss={() => setError(null)} />

        <div className="flex flex-wrap items-center gap-4">
          <button className="btn btn-primary px-[18px] py-[9px]" disabled={!ready || busy} onClick={submit}>
            {busy && <Spinner />}{busy ? (mode === 'url' ? 'Fetching the posting…' : 'Saving…') : 'Analyze this role →'}
          </button>
          <span className="text-[13px] text-muted">Company and title are detected automatically.</span>
        </div>
      </div>

      <aside className="animate-rise flex min-w-[260px] flex-[0_1_320px] flex-col gap-5 lg:pt-[108px]" style={{ animationDelay: '200ms' }}>
        <section className="flex flex-col gap-2.5 rounded-lg border border-rule bg-sheet px-[18px] py-4">
          <p className="eyebrow">Detected</p>
          <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
            <span className="text-muted">Company</span><span className={cx('font-medium', dim)}>{det?.company ?? '—'}</span>
            <span className="text-muted">Role</span><span className={cx('font-medium', dim)}>{det?.role ?? '—'}</span>
            <span className="text-muted">Similar</span><span className={dim}>{det?.similar.length ? det.similar.join(', ') : '—'}</span>
          </div>
          <p className="text-xs text-faint">{mode === 'url' ? 'Read from the posting when it’s fetched.' : 'A first guess from the opening line. The analysis confirms both.'}</p>
        </section>

        <section className="flex flex-col gap-3.5 text-[13px]">
          <p className="eyebrow">How it works</p>
          {HOW.map(([t, d], i) => (
            <div key={t} className="flex gap-3">
              <span className="font-mono text-[15px] font-medium leading-none text-accent">{i + 1}</span>
              <div className="flex flex-col gap-0.5">
                <p className="font-medium text-ink">{t}</p>
                <p className="text-muted text-pretty">{d}</p>
              </div>
            </div>
          ))}
        </section>
      </aside>
    </div>
  )
}
