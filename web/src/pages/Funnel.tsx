import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AppSummary } from '../api'
import { cx, ErrorNote, Spinner } from '../ui'

type Stage = 'built' | 'applied' | 'interview' | 'offer'
type Range = '30' | '90' | 'all'
type TrackFilter = 'all' | 'manager' | 'ic' | 'hybrid'
// key, chart label, list title (applications whose furthest stage is this one)
const STAGES: [Stage, string, string][] = [
  ['built', 'CVs built', 'Built, not sent'],
  ['applied', 'Applied', 'Applied, no interview yet'],
  ['interview', 'Interviewed', 'Interviewed, no offer'],
  ['offer', 'Offer', 'Offers'],
]
const RANK: Record<Stage, number> = { built: 0, applied: 1, interview: 2, offer: 3 }
const DROP: Partial<Record<Stage, string>> = { applied: 'not sent', interview: 'no interview', offer: 'no offer' }
const RANGES: [Range, string, number][] = [['30', '30 days', 30], ['90', '90 days', 90], ['all', 'All time', Infinity]]
const TRACKS: [TrackFilter, string][] = [['all', 'All'], ['manager', 'Manager'], ['ic', 'IC'], ['hybrid', 'Hybrid']]
const H = 280 // column chart height (px)

const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0)
const short = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short' }) : '')
const daysAgo = (iso?: string) => (iso ? (Date.now() - Date.parse(iso)) / 86_400_000 : Infinity)

function Segmented<T extends string>({ label, options, value, onChange }: { label: string; options: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex h-10 gap-0.5 rounded-lg bg-lane p-[3px]">
      {options.map(([k, name]) => (
        <button key={k} aria-pressed={value === k} onClick={() => onChange(k)}
          className={cx('h-[34px] cursor-pointer rounded-md px-3 font-medium transition-colors',
            value === k ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(14_20_34/0.12)]' : 'text-muted hover:text-ink')}>
          {name}
        </button>
      ))}
    </div>
  )
}

const barColor = (k: Stage, on: boolean) => (k === 'offer' ? (on ? 'bg-ok' : 'bg-[#5fae86]') : on ? 'bg-accent' : 'bg-[#8fa2f2]')
const RING = 'shadow-[0_0_0_3px_#fff,0_0_0_5px_var(--color-ink)]'
const EASE = 'duration-[350ms] ease-[cubic-bezier(.2,.7,.2,1)]'

export default function Funnel() {
  const [apps, setApps] = useState<AppSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<Range>('90')
  const [track, setTrack] = useState<TrackFilter>('all')
  const [sel, setSel] = useState<Stage>('applied')
  useEffect(() => { api.applications().then(setApps).catch((e) => setError(e.message)) }, [])

  // Applications enter the funnel once their CV is built; the range is by when they were started.
  const inFunnel = useMemo(() => {
    const days = RANGES.find((r) => r[0] === range)![2]
    return (apps ?? []).filter((a) => a.reached && daysAgo(a.created) <= days && (track === 'all' || a.track === track))
  }, [apps, range, track])
  const counts = STAGES.map(([k]) => inFunnel.filter((a) => RANK[a.reached!] >= RANK[k]).length)
  const top = Math.max(1, counts[0])
  const hOf = (c: number) => Math.max(6, Math.round((c / top) * H))
  const edge = (h: number) => (((H - h) / 2 / H) * 100).toFixed(2)

  const stages = STAGES.map(([k, label], i) => {
    const h = hOf(counts[i]), last = i === STAGES.length - 1, h2 = last ? h : hOf(counts[i + 1])
    return {
      k, label, on: sel === k, count: counts[i], h,
      ofTop: i ? `${pct(counts[i], counts[0])}%` : '',
      w: `${Math.max(1, (counts[i] / top) * 100)}%`,
      ghostW: `${((i ? counts[i - 1] : counts[i]) / top) * 100}%`,
      drop: i && counts[i - 1] > counts[i] ? `−${counts[i - 1] - counts[i]} ${DROP[k]}` : '',
      conv: last ? '' : `${pct(counts[i + 1], counts[i])}%`,
      clip: `polygon(0 ${edge(h)}%, 100% ${edge(h2)}%, 100% ${100 - +edge(h2)}%, 0 ${100 - +edge(h)}%)`,
    }
  })

  const title = STAGES.find((s) => s[0] === sel)![2]
  const list = inFunnel.filter((a) => a.reached === sel).sort((x, y) => (y.reached_at ?? '').localeCompare(x.reached_at ?? ''))
  const rangeText = range === 'all' ? 'all time' : `last ${RANGES.find((r) => r[0] === range)![1]}`
  const trackText = track === 'all' ? '' : ` · ${TRACKS.find((t) => t[0] === track)![1]} roles`

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <div className="flex flex-col gap-2.5">
          <h1 className="font-display text-[48px] leading-[0.92] tracking-[-0.02em] text-ink sm:text-[64px]">Funnel</h1>
          {apps && <p className="font-mono text-xs text-muted">Built to offer: {pct(counts[3], counts[0])}% · {rangeText}{trackText}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Segmented label="Track" options={TRACKS} value={track} onChange={setTrack} />
          <Segmented label="Time range" options={RANGES.map(([k, l]) => [k, l] as [Range, string])} value={range} onChange={setRange} />
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {apps === null && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}

      {apps && (
        <section aria-label="Funnel chart" className="animate-rise rounded-[14px] border border-rule bg-sheet px-5 pb-6 pt-7 sm:px-7">
          {/* Columns with tapered connectors (wide screens) */}
          <div className="hidden items-end md:flex">
            {stages.map((s, i) => (
              <div key={s.k} className="contents">
                <div className="flex min-w-0 flex-1 flex-col gap-4">
                  <div className="flex flex-col gap-1.5">
                    <p className={cx('text-[15px] font-semibold', s.on ? 'text-accent' : 'text-muted')}>{s.label}</p>
                    <p className="flex items-baseline gap-2.5">
                      <span className="font-display text-[56px] leading-[0.9] tracking-[-0.02em] text-ink">{s.count}</span>
                      <span className="font-mono text-xs text-faint">{s.ofTop}</span>
                    </p>
                  </div>
                  <button aria-pressed={s.on} aria-label={`${s.label}: ${s.count}`} onClick={() => setSel(s.k)}
                    className="flex h-[280px] cursor-pointer items-center border-0 bg-transparent p-0">
                    <span className={cx('block min-h-1.5 w-full rounded-md transition-[height,background-color]', EASE, barColor(s.k, s.on), s.on && RING)} style={{ height: s.h }} />
                  </button>
                </div>
                {i < stages.length - 1 && (
                  <div className="relative h-[280px] w-[84px] flex-none" aria-hidden>
                    <div className={cx('absolute inset-0 bg-[#dfe5fb] transition-[clip-path]', EASE)} style={{ clipPath: s.clip }} />
                    <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border border-[#cfd8f7] bg-sheet px-2 py-1 font-mono text-xs font-medium text-accent">{s.conv}</span>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Horizontal bars (phones and narrow windows) */}
          <div className="flex flex-col gap-[18px] md:hidden">
            {stages.map((s) => (
              <button key={s.k} aria-pressed={s.on} onClick={() => setSel(s.k)}
                className="grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-0 bg-transparent p-0 text-left">
                <span className={cx('text-[15px] font-semibold', s.on ? 'text-accent' : 'text-muted')}>{s.label}</span>
                <span className="flex items-baseline justify-end gap-2">
                  <span className="font-display text-[34px] leading-none text-ink">{s.count}</span>
                  <span className="font-mono text-[11px] text-faint">{s.ofTop}</span>
                </span>
                <span className="relative col-span-2 block h-10">
                  <span className={cx('absolute inset-y-0 left-0 rounded-md bg-[repeating-linear-gradient(135deg,#eef1f6_0_6px,#e1e5ec_6px_12px)] transition-[width]', EASE)} style={{ width: s.ghostW }} />
                  <span className={cx('absolute inset-y-0 left-0 min-w-1.5 rounded-md transition-[width,background-color]', EASE, barColor(s.k, s.on), s.on && RING)} style={{ width: s.w }} />
                </span>
                {s.drop && <span className="col-span-2 -mt-1 font-mono text-xs text-muted">{s.drop}</span>}
              </button>
            ))}
          </div>
          {counts[0] === 0 && (
            <p className="mt-6 text-center text-sm text-faint">Nothing in the funnel {range === 'all' ? 'yet' : 'for this range'}. Applications enter it once their CV is built.</p>
          )}
        </section>
      )}

      {apps && (
        <section className="flex flex-col gap-3.5">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-display text-[28px] tracking-[-0.01em] text-ink">{title}</h2>
            <span className="font-mono text-xs text-muted">{list.length} {list.length === 1 ? 'application' : 'applications'}</span>
          </div>
          <div className="overflow-hidden rounded-[14px] border border-rule bg-sheet">
            {list.map((a) => (
              <Link key={a.id} to={`/a/${a.id}`}
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-5 border-b border-[#eef0f4] px-5 py-[13px] text-ink last:border-b-0 hover:bg-wash hover:text-ink">
                <span className="min-w-0">
                  <span className="block truncate text-[15px] font-semibold">{a.company}</span>
                  <span className="block truncate text-[13px] text-muted">{a.role}</span>
                </span>
                {a.track
                  ? <span className="rounded bg-[#e6e9ef] px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-body">{a.track}</span>
                  : <span />}
                <span className="min-w-14 text-right font-mono text-[11px] text-faint" title={`Reached ${title.toLowerCase()} stage`}>{short(a.reached_at)}</span>
              </Link>
            ))}
            {list.length === 0 && <p className="px-5 py-9 text-center text-faint">Nothing at this stage for the current filters.</p>}
          </div>
          <p className="font-mono text-[11px] text-faint">Click a stage to list the applications that stopped there · newest first</p>
        </section>
      )}
    </div>
  )
}
