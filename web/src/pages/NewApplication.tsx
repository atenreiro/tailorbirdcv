import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { cx, ErrorNote, Spinner } from '../ui'

export default function NewApplication() {
  const nav = useNavigate()
  const [mode, setMode] = useState<'paste' | 'url'>('paste')
  const [jd, setJd] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_280px]">
      <div className="space-y-6">
        <div className="animate-rise">
          <p className="eyebrow">New tailoring</p>
          <h1 className="font-serif text-5xl leading-tight text-ink">What role are we going after?</h1>
        </div>

        <div className="animate-rise flex gap-1 rounded border border-rule bg-wash p-1 text-sm" style={{ animationDelay: '60ms' }} role="tablist">
          {(['paste', 'url'] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={cx('flex-1 rounded px-4 py-1.5 transition', mode === m ? 'bg-sheet text-ink shadow-sm' : 'text-muted hover:text-ink')}
            >
              {m === 'paste' ? 'Paste the description' : 'Fetch from a URL'}
            </button>
          ))}
        </div>

        <div className="animate-rise" style={{ animationDelay: '120ms' }}>
          {mode === 'paste' ? (
            <div className="sheet rounded">
              <textarea
                className="block min-h-[420px] w-full resize-y bg-transparent px-6 py-5 font-serif text-[17px] leading-relaxed text-ink placeholder:text-faint focus:outline-none"
                placeholder="Paste the full job description here — title, company, responsibilities, requirements…"
                value={jd}
                onChange={(e) => setJd(e.target.value)}
                autoFocus
              />
              <div className="flex items-center justify-between border-t border-rule px-6 py-2 font-mono text-xs text-faint">
                <span>{jd.trim().split(/\s+/).filter(Boolean).length} words</span>
                {jd.trim().length > 0 && jd.trim().length < 100 && <span className="text-warn">a bit short — paste the full text</span>}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <input
                className="field font-mono text-sm"
                placeholder="https://careers.example.com/jobs/12345"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                autoFocus
              />
              <p className="text-sm text-muted">Reads Lever, Greenhouse and Ashby postings (Binance careers included) directly. Other career sites are rendered in a headless browser if needed (can take ~15 s). Pages behind a login, like LinkedIn, can’t be fetched, so paste the text for those.</p>
            </div>
          )}
        </div>

        <ErrorNote error={error} onDismiss={() => setError(null)} />

        <div className="flex items-center gap-4">
          <button className="btn btn-primary" disabled={!ready || busy} onClick={submit}>
            {busy ? <><Spinner /> {mode === 'url' ? 'Fetching the posting…' : 'Saving…'}</> : 'Analyze this role →'}
          </button>
          <span className="text-sm text-muted">Company and title are detected automatically.</span>
        </div>
      </div>

      <aside className="animate-rise space-y-5 text-sm lg:pt-24" style={{ animationDelay: '200ms' }}>
        <p className="eyebrow">How it works</p>
        {[
          ['Analyze', 'Industry lens, IC vs manager track, every requirement matched to your evidence.'],
          ['Ask', 'Gaps become questions for you — nothing is assumed.'],
          ['Compose', 'Reordered and rephrased from your profile, every claim cited.'],
          ['Verify', 'A fact-check blocks any number, tool or name not in your evidence.'],
          ['Export', 'Your exact resume design, as .docx and .pdf.'],
        ].map(([t, d], i) => (
          <div key={t} className="flex gap-3">
            <span className="font-serif text-xl italic text-rust">{i + 1}</span>
            <div>
              <p className="font-medium text-ink">{t}</p>
              <p className="text-muted">{d}</p>
            </div>
          </div>
        ))}
      </aside>
    </div>
  )
}
