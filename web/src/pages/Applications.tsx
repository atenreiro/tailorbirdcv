import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, STATUSES, type AppSummary } from '../api'
import { cx, ErrorNote, fmtDate, Spinner, StatusPill } from '../ui'

const PIPELINE = ['built', 'applied', 'interview', 'offer']

export default function Applications() {
  const [apps, setApps] = useState<AppSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>('all')

  useEffect(() => {
    api.applications().then(setApps).catch((e) => setError(e.message))
  }, [])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const a of apps ?? []) c[a.status] = (c[a.status] ?? 0) + 1
    return c
  }, [apps])

  const shown = (apps ?? []).filter((a) => filter === 'all' || a.status === filter)

  async function setStatus(id: string, status: string) {
    try {
      await api.patch(id, { status })
      setApps((prev) => prev?.map((a) => (a.id === id ? { ...a, status } : a)) ?? null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-10">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="eyebrow">Applications</p>
          <h1 className="font-serif text-5xl leading-tight text-ink">Every role, one dossier.</h1>
          <p className="mt-2 max-w-xl text-muted">
            Each application keeps its job description, the analysis, the tailored resume and its exports.
            Track where each one stands.
          </p>
        </div>
        <Link to="/new" className="btn btn-primary">+ New tailoring</Link>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="animate-rise grid grid-cols-2 gap-px overflow-hidden rounded border border-rule bg-rule sm:grid-cols-5" style={{ animationDelay: '80ms' }}>
        {[['all', apps?.length ?? 0], ...PIPELINE.map((s) => [s, counts[s] ?? 0])].map(([s, n]) => (
          <button
            key={s}
            onClick={() => setFilter(String(s))}
            className={cx('bg-sheet px-5 py-4 text-left transition-colors hover:bg-wash', filter === s && 'bg-wash')}
          >
            <p className="font-serif text-3xl text-ink">{n}</p>
            <p className={cx('text-xs uppercase tracking-wider', filter === s ? 'text-rust' : 'text-muted')}>{s === 'all' ? 'total' : s}</p>
          </button>
        ))}
      </div>

      {apps === null && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}

      {apps?.length === 0 && (
        <div className="sheet animate-rise rounded px-10 py-16 text-center">
          <p className="font-serif text-3xl text-ink">No applications yet.</p>
          <p className="mx-auto mt-2 max-w-md text-muted">Paste a job description and AutoCV will tailor your resume to it — using only facts from your master profile.</p>
          <Link to="/new" className="btn btn-primary mt-6">Start the first one</Link>
        </div>
      )}

      {shown.length > 0 && (
        <div className="sheet animate-rise overflow-x-auto rounded" style={{ animationDelay: '140ms' }}>
          <table className="w-full text-sm">
            <thead>
              <tr className="rule-b text-left text-[11px] uppercase tracking-wider text-muted">
                <th className="px-5 py-3 font-semibold">Role</th>
                <th className="px-3 py-3 font-semibold">Lens</th>
                <th className="px-3 py-3 font-semibold">Created</th>
                <th className="px-3 py-3 font-semibold">Status</th>
                <th className="px-5 py-3 text-right font-semibold">Files</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.id} className="group border-b border-rule/60 last:border-0 hover:bg-paper/70">
                  <td className="px-5 py-4">
                    <Link to={`/a/${a.id}`} className="block">
                      <span className="font-serif text-lg text-ink group-hover:text-rust">{a.company}</span>
                      <span className="block text-muted">{a.role}</span>
                    </Link>
                  </td>
                  <td className="px-3 py-4 text-muted">
                    {a.industry ? <>{a.industry}<span className="text-faint"> · </span>{a.track}</> : <span className="text-faint">—</span>}
                  </td>
                  <td className="px-3 py-4 whitespace-nowrap text-muted">{fmtDate(a.created)}</td>
                  <td className="px-3 py-4">
                    <label className="relative inline-flex items-center">
                      <StatusPill status={a.status} />
                      <select
                        aria-label={`Status for ${a.company}`}
                        className="absolute inset-0 cursor-pointer opacity-0"
                        value={a.status}
                        onChange={(e) => setStatus(a.id, e.target.value)}
                      >
                        {STATUSES.map((s) => <option key={s}>{s}</option>)}
                      </select>
                    </label>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <div className="flex justify-end gap-2">
                      {a.files.map((f) => (
                        <a key={f} href={api.fileUrl(a.id, f, true)} className="chip hover:bg-rust-soft hover:text-rust">
                          ↓ {f.split('.').pop()}
                        </a>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
