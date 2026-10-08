import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AppSummary, type GapItem, type GapsView } from '../api'
import { cx } from '../lib'
import { ErrorNote, Spinner } from '../ui'

const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short' }) : '')

interface Theme {
  label: string; items: GapItem[]; apps: number; missing: number; must: number; answered: number; said: string | null
}

/** Results → What to learn next: the needs the user's target jobs keep asking for that their profile doesn't show.
 *  The AI only groups and names them (insights.py); everything here is counted from the applications in view,
 *  so the page's range and track filters apply. Two lists: needs missing from the profile in 2+ applications (worth
 *  learning), ranked by how many miss them; and needs it only partly shows (worth wording better). Counts, not
 *  percentages: there are tens of applications, not thousands. */
export default function RecurringGaps({ apps, inView, filterText }: { apps: AppSummary[]; inView: (a: AppSummary) => boolean; filterText: string }) {
  const [data, setData] = useState<GapsView | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)  // by label: unique (the server merges same-named themes)
  useEffect(() => { api.gaps().then(setData).catch((e) => setError(e.message)) }, [])

  const byId = useMemo(() => new Map(apps.map((a) => [a.id, a])), [apps])
  const analysed = useMemo(() => (data?.analysed ?? []).map((id) => byId.get(id)).filter((a): a is AppSummary => !!a && inView(a)),
    [data, byId, inView])
  const ids = useMemo(() => new Set(analysed.map((a) => a.id)), [analysed])
  const themes = useMemo(() => (data?.themes ?? []).map((t): Theme => {
    const all = t.items.filter((i) => ids.has(i.app_id))
    const items = all.filter((i) => !i.answered)  // answered since with approved evidence: no longer a gap
    const answers = items.map((i) => i.no_experience).filter((d): d is string => !!d)
    return {
      label: t.label, items: all, apps: new Set(items.map((i) => i.app_id)).size, answered: all.length - items.length,
      must: new Set(items.filter((i) => i.priority === 'must').map((i) => i.app_id)).size,
      missing: new Set(items.filter((i) => i.status === 'gap').map((i) => i.app_id)).size,
      said: answers.filter((d) => d !== 'yes').sort().at(-1) ?? answers[0] ?? null,  // the latest date, else "yes"
    }
  }).filter((t) => t.apps >= 2), [data, ids])
  const missing = themes.filter((t) => t.missing >= 2).sort((a, b) => b.missing - a.missing || b.must - a.must || b.apps - a.apps)
  const partly = themes.filter((t) => t.missing < 2).sort((a, b) => b.apps - a.apps || b.must - a.must)
  const outdated = (data?.outdated ?? []).map((id) => byId.get(id)).filter((a): a is AppSummary => !!a && inView(a))

  const group = async () => {
    setBusy(true)
    setError(null)
    try {
      setData(await api.groupGaps())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const total = analysed.length
  const row = (t: Theme, kind: 'missing' | 'partly') => {
    const expanded = open === t.label
    const big = kind === 'missing' ? t.missing : t.apps
    return (
      <div key={t.label} className="border-b border-[#e9efeb] last:border-b-0">
        <button aria-expanded={expanded} onClick={() => setOpen(expanded ? null : t.label)}
          className="grid w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 gap-y-2 border-0 bg-transparent px-5 py-3.5 text-left hover:bg-wash">
          <span className="min-w-0">
            <span className="block text-[15px] font-semibold text-ink">{t.label}</span>
            <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
              {t.must > 0 && <span>Must-have in {t.must}</span>}
              {kind === 'missing' && t.apps > t.missing && <span>Partly shown in {t.apps - t.missing} more</span>}
              {kind === 'partly' && t.missing > 0 && <span>Missing in {t.missing}</span>}
              {t.answered > 0 && <span className="text-ok">{t.answered} answered since</span>}
              {t.said && <span className="text-warn">You said no experience{/^\d{4}-\d{2}-\d{2}/.test(t.said) && ` · ${day(t.said)}`}</span>}
            </span>
          </span>
          <span className="flex w-[132px] flex-col items-end gap-1.5">
            <span className="font-mono text-xs text-body"><span className="font-display text-[22px] leading-none text-ink">{big}</span> of {total}</span>
            <span className="block h-1.5 w-full overflow-hidden rounded-full bg-paper" aria-hidden>
              <span className={cx('block h-full rounded-full', kind === 'missing' ? 'bg-accent' : 'bg-[#a3bcb0]')} style={{ width: `${(big / Math.max(1, total)) * 100}%` }} />
            </span>
          </span>
        </button>
        {expanded && (
          <ul className="flex flex-col gap-2 px-5 pb-4">
            {t.items.map((i, n) => {
              const a = byId.get(i.app_id)
              return (
                <li key={n} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 text-[13px] leading-[1.45]">
                  <span className={i.answered ? 'text-faint line-through decoration-faint/60' : 'text-body'}>“{i.text}”
                    {i.priority === 'must' && <span className="ml-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-faint">must</span>}
                    {!i.answered && <span className={cx('ml-1.5 text-[11px]', i.status === 'gap' ? 'text-accent' : 'text-faint')}>{i.status === 'gap' ? 'missing' : 'partly shown'}</span>}
                    {i.answered && <span className="ml-1.5 text-[11px] text-ok">answered since</span>}
                  </span>
                  {a && <Link to={`/a/${a.id}`} className="max-w-[200px] truncate text-muted hover:text-ink" title={a.company}>{a.company}</Link>}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    )
  }

  return (
    <section aria-labelledby="gaps-title" className="animate-rise flex flex-col gap-3.5">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex max-w-[680px] flex-col gap-1">
          <h2 id="gaps-title" className="font-display text-[28px] tracking-[-0.01em] text-ink">What to learn next</h2>
          <p className="text-sm leading-[1.5] text-muted text-pretty">
            What your target jobs keep asking for that your profile doesn’t show: worth a course, a certification or a
            project. Below it, what your profile shows only partly, which is often a matter of describing it better.
          </p>
        </div>
        {data && data.requirements >= 2 && (
          <button className={cx('btn h-10 px-4', !data.themes && 'btn-primary')} disabled={busy} onClick={() => void group()}>
            {busy && <Spinner />}{busy ? 'Grouping (about a minute)' : data.themes ? 'Refresh' : 'Find recurring gaps'}
          </button>
        )}
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {data === null && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}
      {data && data.requirements < 2 && <p className="text-sm text-faint">Analyse a few applications first: this compares what they ask for.</p>}
      {data && data.requirements >= 2 && !data.themes && !busy && (
        <p className="text-sm text-faint">The AI groups the {data.requirements} requirements you don’t fully meet, across your analysed applications, by the need behind them. One AI call; the result is kept.</p>
      )}
      {data?.stale && (
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">Applications were analysed since this was grouped ({day(data.created)}). Refresh to include them.</p>
      )}
      {outdated.length > 0 && (
        <div className="rounded-lg bg-warn-soft px-3 py-2.5 text-[13px] text-warn">
          <p>Your evidence changed after {outdated.length === 1 ? 'this application was' : 'these applications were'} analysed, so some of {outdated.length === 1 ? 'its' : 'their'} gaps may be covered now. Re-analyse in Brief to update them (it replaces the gap questions):</p>
          <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
            {outdated.map((a) => <li key={a.id}><Link to={`/a/${a.id}?step=brief`} className="font-medium underline underline-offset-2">{a.company} · {a.role}</Link></li>)}
          </ul>
        </div>
      )}

      {data?.themes && (
        <div className="overflow-hidden rounded-[14px] border border-rule bg-sheet">
          {missing.map((t) => row(t, 'missing'))}
          {missing.length === 0 && <p className="px-5 py-9 text-center text-faint">Nothing is missing from your profile in two or more applications{themes.length ? '' : ' for the current filters'}.</p>}
        </div>
      )}

      {data?.themes && partly.length > 0 && (
        <>
          <div className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
            <div className="flex max-w-[680px] flex-col gap-1">
              <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Partly shown — say it better</h3>
              <p className="text-sm leading-[1.5] text-muted text-pretty">Your profile has related experience, but not the way these jobs ask for it. Check how it’s described, and add what’s true.</p>
            </div>
            <Link to="/profile" className="btn h-10 px-4">Open your profile →</Link>
          </div>
          <div className="overflow-hidden rounded-[14px] border border-rule bg-sheet">
            {partly.map((t) => row(t, 'partly'))}
          </div>
        </>
      )}

      {data?.themes && (
        <p className="font-mono text-[11px] text-faint">
          {total} analysed {total === 1 ? 'application' : 'applications'} · {filterText} · grouped by the AI {day(data.created)} · shown when it comes up in 2 or more · click one for what each job asked
          {(data.outdated_sent ?? 0) > 0 && ` · ${data.outdated_sent} sent ${data.outdated_sent === 1 ? 'application was' : 'applications were'} analysed before your latest evidence changes`}
        </p>
      )}
    </section>
  )
}
