import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, STATUSES, type Application, type AppSummary, type ScoreKey } from '../api'
import { cx, ErrorNote, Spinner, StatusPill } from '../ui'
import { changeStatus } from '../status'

type Stage = 'progress' | 'ready' | 'flight' | 'closed'
type Filter = 'needs' | 'all' | Stage
const STAGE: Record<string, Stage> = {
  draft: 'progress', analyzed: 'progress', composed: 'progress', built: 'ready',
  applied: 'flight', interview: 'flight', offer: 'flight', rejected: 'closed', withdrawn: 'closed',
}
const GROUPS: [Stage, string][] = [['progress', 'In progress'], ['ready', 'Ready to send'], ['flight', 'In flight'], ['closed', 'Closed']]

type Tone = 'warn' | 'act' | 'ok' | 'mute'
type Kind = 'brief' | 'gaps' | 'review' | 'rebuild' | 'build' | 'critique' | 'apply'
interface Next { text: string; short?: string; tone: Tone; cta?: string; kind?: Kind }
// text colour, dot colour, soft background
const TONE: Record<Tone, [string, string, string]> = {
  warn: ['text-warn', 'bg-warn', 'bg-warn-soft'], act: ['text-rust', 'bg-rust', 'bg-rust-soft'],
  ok: ['text-ok', 'bg-ok', 'bg-ok-soft'], mute: ['text-muted', 'bg-rule', 'bg-wash'],
}
const VERDICT = { interview: 'border-ok text-ok', borderline: 'border-warn text-warn', pass: 'border-bad text-bad' }
const SCORES: ScoreKey[] = ['fit', 'impact', 'clarity', 'seniority']

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
const short = (iso?: string) => (iso ? new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short' }) : '')
const hasPdf = (a: AppSummary) => a.files.some((f) => f.endsWith('.pdf'))

/** The one thing to do next for an application, derived from its real state. */
function nextOf(a: AppSummary): Next {
  const p = a.progress
  if (a.status === 'rejected') return { text: 'Closed', tone: 'mute' }
  if (a.status === 'withdrawn') return { text: 'Withdrawn', tone: 'mute' }
  if (a.status === 'offer') return { text: 'Offer received', tone: 'ok' }
  if (a.status === 'interview') return { text: a.notes?.split('\n')[0] || 'Interviewing', tone: 'ok' }
  if (a.status === 'applied') return { text: a.sent ? `Sent ${short(a.sent.created)}` : 'Applied', tone: 'mute' }
  if (!p || !p.requirements) return { text: 'Analyze the job description.', short: 'Analyze the role', tone: 'act', cta: 'Open brief', kind: 'brief' }
  if (!p.drafted) {
    return p.gaps_open
      ? { text: `Answer ${plural(p.gaps_open, 'gap question')}.`, tone: 'warn', cta: 'Open gaps', kind: 'gaps' }
      : { text: 'Gaps answered. Compose the tailored resume.', short: 'Compose the resume', tone: 'act', cta: 'Open gaps', kind: 'gaps' }
  }
  if (p.verified === false) return { text: 'The draft fails the fact-check. Fix it in Review.', short: 'Fact-check failing', tone: 'warn', cta: 'Open review', kind: 'review' }
  if (a.files.length && a.outputs_stale) return { text: 'Resume changed after the last build. Files are outdated.', short: 'Rebuild: files outdated', tone: 'warn', cta: 'Rebuild', kind: 'rebuild' }
  const hm = p.critique
  const fixes = hm && !hm.stale && hm.open > 0
    ? { text: `Hiring manager: ${hm.verdict}. ${plural(hm.open, 'suggestion')} open.`, short: `${plural(hm.open, 'fix')} open`, tone: 'act' as const, cta: 'Review fixes', kind: 'review' as const }
    : null
  if (!hasPdf(a)) {
    if (!hm) return { text: 'Facts verified. Get the hiring-manager read before building.', short: 'Run hiring-manager read', tone: 'act', cta: 'Run review', kind: 'critique' }
    return fixes ?? { text: 'Reviewed. Build the PDF and DOCX.', short: 'Build the files', tone: 'act', cta: 'Build', kind: 'build' }
  }
  return fixes ?? { text: 'Built and checked. Ready to send.', short: 'Ready to send', tone: 'ok', cta: 'Mark applied', kind: 'apply' }
}
const needsYou = (a: AppSummary) => { const n = nextOf(a); return n.tone === 'warn' || n.tone === 'act' || n.kind === 'apply' }

const BUSY_TEXT: Partial<Record<Kind, string>> = {
  rebuild: 'Rebuilding the PDF and DOCX from the current resume (Word opens briefly)…',
  build: 'Building the PDF and DOCX (Word opens briefly)…',
  critique: 'Reading the resume as the hiring manager. This takes about a minute…',
  apply: 'Building a fresh PDF and freezing the copy you’re sending…',
}

export default function Applications() {
  const nav = useNavigate()
  const [apps, setApps] = useState<AppSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const [detail, setDetail] = useState<Application | null>(null)
  const [busy, setBusy] = useState<{ id: string; kind: Kind } | null>(null)
  const [notes, setNotes] = useState<string | null>(null)
  const aside = useRef<HTMLElement>(null)

  const reload = useCallback(() => api.applications().then(setApps).catch((e) => setError(e.message)), [])
  useEffect(() => { void reload() }, [reload])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = (apps ?? [])
      .filter((a) => filter === 'all' || (filter === 'needs' ? needsYou(a) : STAGE[a.status] === filter))
      .filter((a) => !q || `${a.company} ${a.role}`.toLowerCase().includes(q))
    return GROUPS.flatMap(([k]) => list.filter((a) => (STAGE[a.status] ?? 'progress') === k))
  }, [apps, filter, query])
  const selId = visible.some((a) => a.id === sel) ? sel : visible[0]?.id ?? null
  const a = visible.find((x) => x.id === selId) ?? null

  // Full details (scores, keyword coverage, notes) for the selected application.
  useEffect(() => {
    setDetail(null); setNotes(null)
    if (!selId) return
    let live = true
    api.get(selId).then((d) => { if (live) setDetail(d) }).catch(() => {})
    return () => { live = false }
  }, [selId, apps])

  // ↑ ↓ (or j k) move through the list; Enter opens the workspace.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/INPUT|TEXTAREA|SELECT/.test((document.activeElement as HTMLElement | null)?.tagName ?? '')) return
      if (e.key === 'Enter' && selId) { nav(`/a/${selId}`); return }
      if (!['ArrowDown', 'ArrowUp', 'j', 'k'].includes(e.key) || !visible.length) return
      e.preventDefault()
      const i = visible.findIndex((x) => x.id === selId)
      const d = e.key === 'ArrowDown' || e.key === 'j' ? 1 : -1
      setSel(visible[Math.max(0, Math.min(visible.length - 1, i < 0 ? 0 : i + d))].id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [visible, selId, nav])

  function select(id: string) {
    setSel(id)
    if (window.matchMedia('(max-width: 1023px)').matches) setTimeout(() => aside.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  async function act(app: AppSummary, n: Next) {
    if (!n.kind || busy) return
    if (n.kind === 'brief' || n.kind === 'gaps' || n.kind === 'review') { nav(`/a/${app.id}?step=${n.kind}`); return }
    setError(null)
    setBusy({ id: app.id, kind: n.kind })
    try {
      if (n.kind === 'rebuild' || n.kind === 'build') {
        const r = await api.build(app.id)
        if (r.build?.too_long) setError(`${app.company}: the PDF came out at ${r.build.pages} pages. Open the workspace to trim it.`)
      } else if (n.kind === 'critique') {
        await api.critique(app.id)
      } else if (n.kind === 'apply') {
        await changeStatus(app.id, 'applied')
      }
      await reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function setStatus(app: AppSummary, status: string) {
    setError(null)
    try {
      setBusy({ id: app.id, kind: 'apply' })
      if (await changeStatus(app.id, status)) await reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function saveNotes(app: AppSummary) {
    if (notes === null || notes === (app.notes ?? '')) return
    try {
      await api.patch(app.id, { notes })
      setApps((prev) => prev?.map((x) => (x.id === app.id ? { ...x, notes } : x)) ?? prev)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const counts: Record<Filter, number> = { needs: 0, all: apps?.length ?? 0, progress: 0, ready: 0, flight: 0, closed: 0 }
  for (const x of apps ?? []) { counts[STAGE[x.status] ?? 'progress']++; if (needsYou(x)) counts.needs++ }
  const tabs: [Filter, string][] = [['needs', 'Needs you'], ['all', 'All'], ...GROUPS]

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-5">
        <div className="flex flex-col gap-1.5">
          <p className="eyebrow">Applications</p>
          <h1 className="font-serif text-[44px] leading-[1.1] text-ink">Every role, one dossier.</h1>
        </div>
        <div className="flex w-full items-center gap-2.5 sm:w-auto">
          <input type="search" className="field min-w-0 flex-1 text-sm sm:w-[240px] sm:flex-none" placeholder="Search company or role"
            aria-label="Search applications" value={query} onChange={(e) => setQuery(e.target.value)} />
          <Link to="/new" className="btn btn-primary shrink-0">+ New tailoring</Link>
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {apps === null && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}

      {apps?.length === 0 && (
        <div className="sheet animate-rise rounded px-10 py-16 text-center">
          <p className="font-serif text-3xl text-ink">No applications yet.</p>
          <p className="mx-auto mt-2 max-w-md text-muted">Paste a job description and AutoCV will tailor your resume to it, using only facts from your master profile.</p>
          <Link to="/new" className="btn btn-primary mt-6">Start the first one</Link>
        </div>
      )}

      {!!apps?.length && (
        <div className="flex flex-wrap items-start gap-6">
          <section className="flex min-w-0 flex-[1_1_600px] flex-col gap-3.5">
            <div className="flex gap-1 overflow-x-auto border-b border-rule [scrollbar-width:none]" role="tablist">
              {tabs.map(([k, label]) => (
                <button key={k} role="tab" aria-selected={filter === k} onClick={() => setFilter(k)}
                  className={cx('flex shrink-0 cursor-pointer items-baseline gap-1.5 whitespace-nowrap px-3 pb-2.5 pt-2 text-[13px] transition-colors hover:text-ink',
                    filter === k ? 'text-ink shadow-[inset_0_-2px_0_var(--color-rust)]' : 'text-muted')}>
                  <span>{label}</span>
                  <span className={cx('font-mono text-[11px]', filter === k ? 'text-rust' : 'text-faint')}>{counts[k]}</span>
                </button>
              ))}
            </div>

            <div className="sheet animate-rise overflow-hidden rounded">
              {GROUPS.map(([k, title]) => {
                const rows = visible.filter((x) => (STAGE[x.status] ?? 'progress') === k)
                if (!rows.length) return null
                return (
                  <div key={k}>
                    <div className="flex items-baseline gap-2.5 border-b border-rule bg-paper px-5 pb-2 pt-3.5">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">{title}</p>
                      <span className="font-mono text-[11px] text-faint">{rows.length}</span>
                    </div>
                    {rows.map((x) => {
                      const n = nextOf(x), on = x.id === selId
                      return (
                        <div key={x.id} role="button" tabIndex={0} aria-current={on ? 'true' : undefined}
                          onClick={() => select(x.id)} onDoubleClick={() => nav(`/a/${x.id}`)}
                          onKeyDown={(e) => { if (e.key === ' ') { e.preventDefault(); select(x.id) } }}
                          className={cx('grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 border-b border-rule/60 px-5 py-3.5 transition-colors last:border-b-0 hover:bg-wash md:grid-cols-[minmax(180px,1.3fr)_110px_minmax(160px,1.4fr)_64px]',
                            on && 'bg-wash')}>
                          <div className="min-w-0">
                            <p className={cx('truncate font-serif text-lg', on ? 'text-rust' : 'text-ink')}>{x.company}</p>
                            <p className="truncate text-[13px] text-muted">{x.role}</p>
                          </div>
                          <span className="justify-self-end md:justify-self-start"><StatusPill status={x.status} /></span>
                          <p className={cx('col-span-2 flex min-w-0 items-center gap-2 text-[13px] md:col-span-1', TONE[n.tone][0])}>
                            {busy?.id === x.id ? <Spinner /> : <span className={cx('size-1.5 flex-none rounded-full', TONE[n.tone][1])} />}
                            <span className="truncate">{n.short ?? n.text}</span>
                          </p>
                          <span className="hidden justify-self-end whitespace-nowrap font-mono text-[11px] text-faint md:block">{short(x.updated)}</span>
                        </div>
                      )
                    })}
                  </div>
                )
              })}
              {visible.length === 0 && (
                <div className="flex flex-col gap-1.5 px-5 py-12 text-center">
                  <p className="font-serif text-[22px] text-ink">Nothing here.</p>
                  <p className="text-muted">No application matches this filter.</p>
                </div>
              )}
            </div>
            <p className="hidden font-mono text-[11px] text-faint lg:block">↑ ↓ to move through the list · Enter to open</p>
          </section>

          {a && (
            <aside ref={aside} className="sheet flex min-w-[min(340px,100%)] max-w-full flex-[1_1_380px] scroll-mt-20 flex-col rounded lg:sticky lg:top-[84px] lg:max-w-[460px]">
              <Dossier a={a} detail={detail} busy={busy} notes={notes ?? a.notes ?? ''}
                onNotes={setNotes} onNotesBlur={() => saveNotes(a)} onStatus={(s) => setStatus(a, s)} onAct={(n) => act(a, n)} />
            </aside>
          )}
        </div>
      )}
    </div>
  )
}

function Dossier({ a, detail, busy, notes, onNotes, onNotesBlur, onStatus, onAct }: {
  a: AppSummary; detail: Application | null; busy: { id: string; kind: Kind } | null; notes: string
  onNotes: (v: string) => void; onNotesBlur: () => void; onStatus: (s: string) => void; onAct: (n: Next) => void
}) {
  const p = a.progress
  const n = nextOf(a)
  const working = busy?.id === a.id
  const built = a.files.length > 0
  const hm = detail?.critique ?? null
  const cov = detail?.ats?.coverage
  const lens = [a.industry, a.track, p?.seniority].filter(Boolean).join(' · ')
  const label = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-muted'
  const steps = [
    { label: 'Brief', note: p?.requirements ? plural(p.requirements, 'requirement') : 'not analyzed', bar: p?.requirements ? 'bg-ok' : 'bg-rule', tone: p?.requirements ? 'text-muted' : 'text-faint' },
    { label: 'Gaps', note: !p?.requirements ? '—' : p.gaps_open ? `${p.gaps_open} open` : 'answered',
      bar: !p?.requirements ? 'bg-rule' : p.gaps_open && !p.drafted ? 'bg-warn' : 'bg-ok', tone: p?.gaps_open && !p.drafted ? 'text-warn' : 'text-muted' },
    { label: 'Review', note: !p?.drafted ? '—' : p.verified === false ? 'fact-check failing' : p.critique ? p.critique.verdict : 'verified',
      bar: !p?.drafted ? 'bg-rule' : p.verified === false ? 'bg-bad' : p.critique && p.critique.open && !p.critique.stale ? 'bg-rust' : 'bg-ok',
      tone: !p?.drafted ? 'text-faint' : p.verified === false ? 'text-bad' : 'text-muted' },
    { label: 'Export', note: built ? (a.outputs_stale ? 'outdated' : a.files.map((f) => f.split('.').pop()!.toUpperCase()).join(' · ')) : 'not built',
      bar: built ? (a.outputs_stale ? 'bg-warn' : 'bg-ok') : 'bg-rule', tone: a.outputs_stale ? 'text-warn' : built ? 'text-muted' : 'text-faint' },
  ]

  return (
    <>
      <div className="flex flex-col gap-3 border-b border-rule px-6 pb-[18px] pt-[22px]">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            {lens && <p className="eyebrow">{lens}</p>}
            <h2 className="font-serif text-[30px] leading-[1.1] text-ink">{a.company}</h2>
            <p className="text-body">{a.role}</p>
          </div>
          <label className="relative inline-flex flex-none cursor-pointer items-center gap-1" title="Change status">
            <StatusPill status={a.status} /><span className="text-[9px] text-muted">▾</span>
            <select aria-label={`Status for ${a.company}`} className="absolute inset-0 cursor-pointer opacity-0" value={a.status}
              disabled={working} onChange={(e) => onStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
        </div>
        <p className="font-mono text-[11px] text-faint">
          created {short(a.created)} · updated {short(a.updated)}{a.pages ? ` · ${plural(a.pages, 'page')}` : ''}
        </p>
      </div>

      <div className="grid grid-cols-4 gap-2 border-b border-rule px-6 py-[18px]">
        {steps.map((s) => (
          <div key={s.label} className="flex min-w-0 flex-col gap-1.5">
            <span className={cx('h-[3px] rounded-full', s.bar)} />
            <p className="text-xs font-semibold text-ink">{s.label}</p>
            <p className={cx('truncate text-xs', s.tone)} title={s.note}>{s.note}</p>
          </div>
        ))}
      </div>

      {n.cta && (
        <div className={cx('mx-6 mt-[18px] flex items-center gap-3.5 rounded px-4 py-3.5', TONE[n.tone][2])}>
          <p className={cx('flex-1 text-[13px] text-pretty', TONE[n.tone][0])}>{working && BUSY_TEXT[busy!.kind] ? BUSY_TEXT[busy!.kind] : n.text}</p>
          <button className="btn btn-primary flex-none px-3 py-1.5 text-[13px]" disabled={!!busy} onClick={() => onAct(n)}>
            {working && <Spinner />}{working ? 'Working' : n.cta}
          </button>
        </div>
      )}

      {hm && (
        <div className="flex flex-col gap-3 px-6 pb-1 pt-[18px]">
          <div className="flex items-baseline justify-between gap-3">
            <p className={label}>Hiring manager read</p>
            <span className={cx('rounded-sm border-[1.5px] px-2 py-px font-mono text-[11px] font-medium uppercase tracking-[0.16em]', VERDICT[hm.latest.verdict.decision])}>
              {hm.latest.verdict.decision}
            </span>
          </div>
          <p className="font-serif text-[17px] italic leading-[1.35] text-body text-pretty">“{hm.latest.verdict.reason}”</p>
          {hm.stale && <p className="text-xs text-warn">The resume changed since this read. Re-run it in Review for fresh scores.</p>}
          <div className="grid grid-cols-2 gap-x-5 gap-y-2.5">
            {SCORES.map((k) => {
              const v = hm.latest.scores[k].score, prev = hm.previous_scores?.[k]?.score
              const d = prev === undefined ? 0 : v - prev
              return (
                <div key={k} className="flex flex-col gap-1" title={hm.latest.scores[k].why}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="capitalize text-muted">{k}</span>
                    <span className="font-mono text-ink">{v}/10 {d !== 0 && <span className={d > 0 ? 'text-ok' : 'text-bad'}>{d > 0 ? `+${d}` : d}</span>}</span>
                  </div>
                  <div className="h-1 rounded-full bg-wash"><div className="h-full rounded-full bg-rust" style={{ width: `${v * 10}%` }} /></div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {cov && (
        <div className="flex flex-col gap-2.5 px-6 pb-1 pt-[18px]">
          <p className={label}>Keyword coverage</p>
          {(['must', 'nice'] as const).map((k) => {
            const { hit, total } = cov[k]
            const pct = total ? Math.round((hit / total) * 100) : 0
            return (
              <div key={k} className="grid grid-cols-[44px_minmax(0,1fr)_48px] items-center gap-2.5 text-xs">
                <span className="capitalize text-muted">{k}</span>
                <div className="h-1 rounded-full bg-wash">
                  <div className={cx('h-full rounded-full', k === 'nice' ? 'bg-faint' : hit === total ? 'bg-ok' : 'bg-warn')} style={{ width: `${pct}%` }} />
                </div>
                <span className="justify-self-end font-mono text-ink">{hit}/{total}</span>
              </div>
            )
          })}
        </div>
      )}

      <div className="flex flex-col gap-2 px-6 py-[18px]">
        <label className={label} htmlFor={`notes-${a.id}`}>Notes</label>
        <textarea id={`notes-${a.id}`} rows={3} className="field resize-y text-[13px]" placeholder="Recruiter, interview dates, anything to remember"
          value={notes} onChange={(e) => onNotes(e.target.value)} onBlur={onNotesBlur} />
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-2 rounded-b border-t border-rule bg-paper px-6 py-3.5">
        {a.files.map((f) => (
          <a key={f} href={api.fileUrl(a.id, f, true)}
            title={a.outputs_stale ? 'Outdated: the resume changed after this was built' : f}
            className={cx('chip hover:bg-rust-soft hover:text-rust', a.outputs_stale && 'line-through opacity-60')}>↓ {f.split('.').pop()}</a>
        ))}
        {a.sent && a.sent.files.some((f) => f.endsWith('.pdf')) && (
          <a href={api.sentFileUrl(a.id, a.sent.id, a.sent.files.find((f) => f.endsWith('.pdf'))!, true)}
            title={`Exact copy sent on ${short(a.sent.created)}`} className="chip bg-ok-soft text-ok hover:bg-ok hover:text-sheet">✓ sent</a>
        )}
        {!built && !a.sent && <span className="text-xs text-faint">No files built yet</span>}
        <Link to={`/a/${a.id}`} className="btn ml-auto px-3 py-1.5 text-[13px]">Open workspace →</Link>
      </div>
    </>
  )
}
