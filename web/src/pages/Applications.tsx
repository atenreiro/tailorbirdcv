import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type RefObject } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Application, type AppSummary, type Outcome, type ScoreKey } from '../api'
import { cx, OUTCOME_GROUPS, OUTCOMES, statusLabel, useTitle } from '../lib'
import { ErrorNote, Spinner, StatusPill, StatusSelect } from '../ui'
import { changeStatus, sentAsApplied } from '../status'
import { setPendingSave } from '../unsaved'
import { useIdentifyPdf } from './useIdentifyPdf'

type Stage = 'progress' | 'ready' | 'flight' | 'closed'
type View = 'board' | 'table'
const STAGE: Record<string, Stage> = {
  draft: 'progress', analyzed: 'progress', composed: 'progress', built: 'ready',
  applied: 'flight', interview: 'flight', offer: 'flight', closed: 'closed',
}
const COLS: [Stage, string][] = [['progress', 'In progress'], ['ready', 'Ready to send'], ['flight', 'In flight'], ['closed', 'Closed']]
const STAGE_TITLE = Object.fromEntries(COLS) as Record<Stage, string>
const LANE_LIMIT = 5

type Tone = 'warn' | 'act' | 'ok' | 'mute'
type Kind = 'brief' | 'gaps' | 'review' | 'rebuild' | 'build' | 'critique' | 'apply' | 'status' | 'delete'
interface Next { text: string; short?: string; tone: Tone; cta?: string; kind?: Kind }
// text colour, dot colour, soft background
const TONE: Record<Tone, [string, string, string]> = {
  warn: ['text-[#7a4700]', 'bg-[#c47a00]', 'bg-warn-soft'], act: ['text-accent', 'bg-accent', 'bg-accent-soft'],
  ok: ['text-ok', 'bg-ok', 'bg-ok-soft'], mute: ['text-muted', 'bg-[#b8c0cd]', 'bg-[#f2f4f7]'],
}
// progress meter segment colours
const BAR = { ok: 'bg-ok', warn: 'bg-[#c47a00]', act: 'bg-accent', bad: 'bg-bad', off: 'bg-rule' }
const VERDICT = { interview: 'text-ok', borderline: 'text-warn', pass: 'text-bad' }
const SCORES: ScoreKey[] = ['fit', 'impact', 'clarity', 'seniority']

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
const short = (iso?: string) => (iso ? new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short' }) : '')
const hasPdf = (a: AppSummary) => a.files.some((f) => f.endsWith('.pdf'))
const recent = (x: AppSummary, y: AppSummary) => (y.updated ?? '').localeCompare(x.updated ?? '') || (y.created ?? '').localeCompare(x.created ?? '')

/** The one thing to do next for an application, derived from its real state. */
function nextOf(a: AppSummary): Next {
  const p = a.progress
  if (a.status === 'closed') {
    return a.outcome === 'accepted_offer' ? { text: 'Offer accepted', tone: 'ok' }
      : { text: a.closed_at ? `Closed ${short(a.closed_at)}` : 'Closed', tone: 'mute' }  // the pill says how
  }
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

/** Brief · Gaps · Review · Export, each with a bar colour and a short note. */
function steps(a: AppSummary) {
  const p = a.progress, built = a.files.length > 0, r = p?.requirements, d = p?.drafted
  return [
    { label: 'Brief', note: r ? plural(r, 'requirement') : 'not analyzed', bar: r ? BAR.ok : BAR.off, tone: r ? 'text-muted' : 'text-faint' },
    { label: 'Gaps', note: !r ? '—' : p!.gaps_open ? `${p!.gaps_open} open` : 'answered',
      bar: !r ? BAR.off : p!.gaps_open && !d ? BAR.warn : BAR.ok, tone: !r ? 'text-faint' : p!.gaps_open && !d ? 'text-[#7a4700]' : 'text-muted' },
    { label: 'Review', note: !d ? '—' : p!.verified === false ? 'fact-check failing' : p!.critique ? p!.critique.verdict : 'verified',
      bar: !d ? BAR.off : p!.verified === false ? BAR.bad : p!.critique && p!.critique.open && !p!.critique.stale ? BAR.act : BAR.ok,
      tone: !d ? 'text-faint' : p!.verified === false ? 'text-bad' : 'text-muted' },
    { label: 'Export', note: built ? (a.outputs_stale ? 'outdated' : a.files.map((f) => f.split('.').pop()!.toUpperCase()).join(' · ')) : 'not built',
      bar: built ? (a.outputs_stale ? BAR.warn : BAR.ok) : BAR.off, tone: a.outputs_stale ? 'text-[#7a4700]' : built ? 'text-muted' : 'text-faint' },
  ]
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
/** Keep Tab / Shift+Tab cycling through the panel's controls while it's open. */
function trapFocus(e: KeyboardEvent, root: HTMLElement) {
  const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement)
  if (!items.length) return
  const first = items[0], last = items[items.length - 1], active = document.activeElement as HTMLElement | null
  if (!active || !root.contains(active)) { e.preventDefault(); (e.shiftKey ? last : first).focus() }
  else if (e.shiftKey && active === first) { e.preventDefault(); last.focus() }
  else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
}

function Meter({ a }: { a: AppSummary }) {
  return (
    <div title="Brief · Gaps · Review · Export" className="grid flex-1 grid-cols-4 gap-[3px]">
      {steps(a).map((s) => <span key={s.label} className={cx('h-1 rounded-sm', s.bar)} />)}
    </div>
  )
}

function NextLine({ a, working }: { a: AppSummary; working: boolean }) {
  const n = nextOf(a)
  return (
    <p className={cx('flex min-w-0 items-center gap-2 text-[13px]', TONE[n.tone][0])}>
      {working ? <Spinner className="size-[11px]" /> : <span className={cx('size-1.5 flex-none rounded-full', TONE[n.tone][1])} />}
      <span className="truncate">{n.short ?? n.text}</span>
    </p>
  )
}

const BUSY_TEXT: Partial<Record<Kind, string>> = {
  rebuild: 'Rebuilding the PDF and DOCX from the current resume…',
  build: 'Building the PDF and DOCX…',
  critique: 'Reading the resume as the hiring manager. This takes about a minute…',
  apply: 'Building a fresh PDF and freezing the copy you’re sending…',  // only while marking applied runs a build
  status: 'Saving…',
}

const VIEW_KEY = 'autocv.view'
function savedView(): View {
  try {
    const old = localStorage.getItem('acv3.view')  // the key's earlier name: migrate it once
    if (old !== null) {
      if (localStorage.getItem(VIEW_KEY) === null) localStorage.setItem(VIEW_KEY, old)
      localStorage.removeItem('acv3.view')
    }
    return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'board'
  } catch { return 'board' }
}
const noModifier = (e: { ctrlKey: boolean; metaKey: boolean; altKey: boolean }) => !e.ctrlKey && !e.metaKey && !e.altKey

export default function Applications() {
  useTitle(['Applications'])
  const nav = useNavigate()
  const [apps, setApps] = useState<AppSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setViewState] = useState<View>(savedView)
  const identify = useIdentifyPdf()
  const [query, setQuery] = useState('')
  const [needs, setNeeds] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [fetched, setFetched] = useState<Application | null>(null)
  const [busy, setBusy] = useState<{ id: string; kind: Kind } | null>(null)
  const [draft, setDraft] = useState<{ id: string; text: string } | null>(null)  // notes as typed (saved debounced)
  const [drag, setDrag] = useState<string | null>(null)
  const [over, setOver] = useState<Stage | null>(null)
  // how many cards each lane shows: the newest LANE_LIMIT, then LANE_LIMIT more per "Show more"
  const [shownIn, setShownIn] = useState<Partial<Record<Stage, number>>>({})
  const laneLimit = (k: Stage) => shownIn[k] ?? LANE_LIMIT
  const [asking, setAsking] = useState<string | null>(null)  // the application whose closing outcome we're asking for
  const [confirming, setConfirming] = useState(false)  // the delete confirmation is showing
  // What the panel keeps showing while it slides out after a delete (the application is gone).
  const [ghost, setGhost] = useState<{ a: AppSummary; detail: Application | null } | null>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const deleteBtn = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const opener = useRef<HTMLElement | null>(null)  // the card/row that opened the panel; focus returns there

  const reload = useCallback(() => api.applications().then(setApps).catch((e) => setError(e.message)), [])
  useEffect(() => { void reload() }, [reload])

  const setView = (v: View) => { try { localStorage.setItem(VIEW_KEY, v) } catch { /* private mode */ } setViewState(v) }

  // Notes save while typing (debounced), and right away on blur, close or switching cards.
  // Saves run one after another so an older one never lands last.
  const notesTimer = useRef<number | undefined>(undefined)
  const pendingNotes = useRef<{ id: string; text: string } | null>(null)
  const notesChain = useRef<Promise<unknown>>(Promise.resolve())
  const flushNotes = useCallback(() => {
    window.clearTimeout(notesTimer.current)
    const p = pendingNotes.current
    if (!p) return
    pendingNotes.current = null
    const tail = notesChain.current = notesChain.current
      .then(() => api.patch(p.id, { notes: p.text }))
      .then(() => setApps((prev) => prev?.map((x) => (x.id === p.id ? { ...x, notes: p.text } : x)) ?? prev))
      .catch((e) => setError((e as Error).message))
      .finally(() => { if (notesChain.current === tail && !pendingNotes.current) setPendingSave('notes', false) })
  }, [])
  const typeNotes = (id: string, text: string) => {
    setDraft({ id, text })
    pendingNotes.current = { id, text }
    setPendingSave('notes', true)  // closing the tab mid-save asks first
    window.clearTimeout(notesTimer.current)
    notesTimer.current = window.setTimeout(flushNotes, 800)
  }
  useEffect(() => () => flushNotes(), [flushNotes])  // leaving the page saves what's typed

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (apps ?? []).filter((a) => !q || `${a.company} ${a.role}`.toLowerCase().includes(q)).sort(recent)
  }, [apps, query])
  // What ↑/↓ walk through: the table order, or the board's visible cards column by column.
  const visible = useMemo(() => view === 'table' ? list : COLS.flatMap(([k]) => {
    const rows = list.filter((a) => STAGE[a.status] === k)
    return rows.slice(0, shownIn[k] ?? LANE_LIMIT)
  }), [list, view, shownIn])
  const a = (apps ?? []).find((x) => x.id === sel) ?? null

  // Full details (scores, keyword coverage) for the open application. State is tagged with the
  // application it belongs to, so switching cards never shows another card's details or notes.
  useEffect(() => {
    if (!sel) return
    let live = true
    api.get(sel).then((d) => { if (live) setFetched(d) }).catch(() => {})
    return () => { live = false }
  }, [sel, apps])
  const detail = fetched?.id === sel ? fetched : null
  const shown = a ?? ghost?.a ?? null
  const shownDetail = a ? detail : ghost?.detail ?? null

  // On open (and after switching cards, which remounts the sheet), focus Close, or the first
  // outcome when we're asking how an application ended. Cancelling the delete confirmation
  // returns focus to its trigger.
  const wasConfirming = useRef(false)
  useEffect(() => {
    const was = wasConfirming.current
    wasConfirming.current = confirming
    if (!open || confirming) return  // the confirmation focuses its own Cancel
    const first = asking ? panel.current?.querySelector<HTMLElement>('[data-outcome]') : null
    ;(first ?? (was ? deleteBtn.current : null) ?? closeBtn.current)?.focus({ preventScroll: true })
  }, [open, asking, sel, confirming])

  const show = useCallback((id: string, from?: HTMLElement | null) => {
    flushNotes()
    opener.current = from ?? document.querySelector<HTMLElement>(`[data-app-id="${CSS.escape(id)}"]`)
    setSel(id)
    setOpen(true)
    setAsking(null)
    setConfirming(false)
    setGhost(null)
  }, [flushNotes])
  // Close and hand focus back to whatever opened the panel (or the search box if it's gone).
  // After a delete the content is kept as it was while the panel slides out.
  const close = useCallback((keepContent = false) => {
    flushNotes()
    setOpen(false)
    if (!keepContent) { setAsking(null); setConfirming(false) }
    const back = opener.current
    setTimeout(() => (back?.isConnected ? back : search.current)?.focus({ preventScroll: true }), 0)
  }, [flushNotes])

  // Esc cancels the delete confirmation or the outcome picker first, then closes; Tab stays in the
  // open panel. ↑ ↓ (or j k) move between applications and open the sheet, but only while a card
  // or row is focused or the panel is open (never hijacking page scroll). Enter opens the workspace.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return  // already handled (e.g. Enter on a card just opened the panel)
      const active = document.activeElement as HTMLElement | null
      if (e.key === 'Escape') {
        if (!open) return
        e.preventDefault()
        if (confirming) setConfirming(false)
        else if (asking) setAsking(null)
        else close()
        return
      }
      if (e.key === 'Tab' && open && panel.current) { trapFocus(e, panel.current); return }
      if (!noModifier(e) || /INPUT|TEXTAREA|SELECT/.test(active?.tagName ?? '')) return
      const inPanel = open && !!active && !!panel.current?.contains(active)
      // Enter on another control inside the panel (a link, the action button) keeps its own meaning.
      const ownEnter = !!active && active !== closeBtn.current && /^(BUTTON|A)$/.test(active.tagName) && inPanel
      if (e.key === 'Enter' && open && sel && !ownEnter) { e.preventDefault(); nav(`/a/${sel}`); return }
      if (!['ArrowDown', 'ArrowUp', 'j', 'k'].includes(e.key) || !visible.length) return
      const card = open ? null : active?.closest<HTMLElement>('[data-app-id]')
      if (!inPanel && !card) return
      e.preventDefault()
      const i = visible.findIndex((x) => x.id === (card ? card.dataset.appId : sel))
      const d = e.key === 'ArrowDown' || e.key === 'j' ? 1 : -1
      show(visible[Math.max(0, Math.min(visible.length - 1, i < 0 ? 0 : i + d))].id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [visible, sel, open, asking, confirming, nav, show, close])

  /** Runs an action for one application, then refreshes the list. Returns whether it succeeded. */
  async function run(app: AppSummary, kind: Kind, fn: () => Promise<unknown>): Promise<boolean> {
    if (busy) return false
    setError(null)
    setBusy({ id: app.id, kind })
    try {
      await fn()
      await reload()
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  function act(app: AppSummary, n: Next) {
    if (!n.kind) return
    if (n.kind === 'brief' || n.kind === 'gaps' || n.kind === 'review') { nav(`/a/${app.id}?step=${n.kind}`); return }
    if (n.kind === 'rebuild' || n.kind === 'build') {
      void run(app, n.kind, async () => {
        const r = await api.build(app.id)
        if (r.build?.too_long) setError(`${app.company}: the PDF came out at ${r.build.pages} pages. Open the workspace to trim it.`)
      })
    } else if (n.kind === 'critique') void run(app, 'critique', () => api.critique(app.id))
    else if (n.kind === 'apply') void setStatus(app, 'applied')
  }

  // A plain "Saving…" unless marking it applied has to build a fresh PDF first.
  const setStatus = (app: AppSummary, status: string, outcome?: Outcome) => {
    const sent = detail?.id === app.id ? detail.sent : [app.sent]
    return run(app, 'status', () => changeStatus(app.id, status, {
      outcome, alreadySent: sentAsApplied(sent),
      onBuilding: (on) => { if (on) setBusy({ id: app.id, kind: 'apply' }) },
    })).then((ok) => { if (ok) setAsking(null) })
  }

  // Dropping a card on a column changes the status; it never claims work that hasn't happened.
  function drop(app: AppSummary, to: Stage) {
    if (STAGE[app.status] === to) return
    const p = app.progress
    if (to === 'progress') void setStatus(app, !p?.requirements ? 'draft' : !p.drafted ? 'analyzed' : 'composed')
    else if (to === 'ready') {
      if (!hasPdf(app) || app.outputs_stale) setError(`${app.company}: build an up-to-date PDF first (Export step), then move it to Ready to send.`)
      else void setStatus(app, 'built')
    } else if (to === 'flight') void setStatus(app, 'applied')
    else { show(app.id); setAsking(app.id) }  // closing: ask how it ended
  }

  // Only called after the user confirms in the panel. The card is gone afterwards, so focus
  // falls back to the search box. The selection is cleared before the list reloads, so the
  // deleted application is never fetched again; the panel shows a snapshot while it slides out.
  async function remove(app: AppSummary) {
    if (pendingNotes.current?.id === app.id) { window.clearTimeout(notesTimer.current); pendingNotes.current = null }
    const snapshot = { a: app, detail }
    const ok = await run(app, 'delete', async () => {
      await api.remove(app.id)
      setGhost(snapshot)
      setSel(null)
    })
    if (ok) close(true)
  }

  const all = apps ?? []
  const needsCount = all.filter(needsYou).length
  const active = all.filter((x) => STAGE[x.status] !== 'closed').length
  const dim = (x: AppSummary) => (needs && !needsYou(x) ? 'opacity-[.38]' : drag === x.id ? 'opacity-50' : '')

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <div className="flex flex-col gap-2.5">
          <h1 className="font-display text-[48px] leading-[0.92] tracking-[-0.02em] text-ink sm:text-[64px]">Applications</h1>
          {apps && <p className="font-mono text-xs text-muted">{active} active · {needsCount} need{needsCount === 1 ? 's' : ''} you · {all.length} total</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <div role="group" aria-label="View" className="inline-flex h-10 gap-0.5 rounded-lg bg-lane p-[3px]">
            {(['board', 'table'] as const).map((v) => (
              <button key={v} aria-pressed={view === v} onClick={() => setView(v)}
                className={cx('h-[34px] cursor-pointer rounded-md px-3.5 font-medium capitalize transition-colors',
                  view === v ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(14_20_34/0.12)]' : 'text-muted hover:text-ink')}>
                {v}
              </button>
            ))}
          </div>
          <input ref={search} type="search" className="field h-10 w-[240px] max-w-full text-sm" placeholder="Search company or role" aria-label="Search applications"
            value={query} onChange={(e) => setQuery(e.target.value)} />
          <button aria-pressed={needs} onClick={() => setNeeds((x) => !x)}
            className={cx('inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg border px-3.5 font-medium transition-colors',
              needs ? 'border-ink bg-ink text-white' : 'border-[#cfd5de] bg-sheet text-ink hover:border-ink')}>
            <span>Needs you</span>
            <span className={cx('inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1 font-mono text-[11px]', needs ? 'bg-[#4d6bff] text-white' : 'bg-accent-soft text-accent')}>{needsCount}</span>
          </button>
          <button className="btn h-10 px-3.5" onClick={identify.pick}
            title="Which application did a resume PDF come from? Compared with your sent copies; the PDF is never stored">
            Identify a PDF
          </button>
          {identify.picker}
          <Link to="/new" className="btn btn-primary h-10 px-4 hover:text-white">New tailoring</Link>
        </div>
      </div>
      {identify.panel}

      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {apps === null && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>}

      {apps?.length === 0 && (
        <div className="animate-rise rounded-[14px] border border-rule bg-sheet px-10 py-16 text-center">
          <p className="font-display text-[36px] leading-none text-ink">No applications yet.</p>
          <p className="mx-auto mt-3 max-w-md text-muted">Paste a job description and AutoCV will tailor your resume to it, using only facts from your master profile.</p>
          <Link to="/new" className="btn btn-primary mt-6 hover:text-white">Start the first one</Link>
        </div>
      )}

      {!!apps?.length && view === 'board' && (
        <>
          <div className="grid items-start gap-4 [grid-template-columns:repeat(auto-fit,minmax(272px,1fr))]">
            {COLS.map(([k, title]) => {
              const rows = list.filter((x) => STAGE[x.status] === k)
              const limit = laneLimit(k)
              const shown = rows.slice(0, limit)
              return (
                <section key={k} aria-label={title}
                  onDragOver={(e) => { if (!drag) return; e.preventDefault(); if (over !== k) setOver(k) }}
                  onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(null) }}
                  onDrop={(e) => { e.preventDefault(); const x = all.find((y) => y.id === drag); setDrag(null); setOver(null); if (x) drop(x, k) }}
                  className={cx('flex min-w-0 flex-col gap-2.5 rounded-[14px] bg-lane p-3 transition-shadow', over === k && 'shadow-[inset_0_0_0_2px_var(--color-accent)]')}>
                  <div className="flex items-baseline justify-between gap-2.5 px-1 pb-1.5 pt-1">
                    <h2 className="font-display text-xl tracking-[-0.005em] text-ink">{title}</h2>
                    <span className="font-mono text-xs text-muted">{rows.length}</span>
                  </div>
                  {shown.map((x) => {
                    const on = open && x.id === sel
                    return (
                      <div key={x.id} data-app-id={x.id} draggable role="button" tabIndex={0} aria-haspopup="dialog" aria-current={on ? 'true' : undefined}
                        aria-label={`${x.company}, ${x.role}. ${statusLabel(x.status, x.outcome)}. ${nextOf(x).short ?? nextOf(x).text}`}
                        onDragStart={(e: DragEvent) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', x.id); setDrag(x.id) }}
                        onDragEnd={() => { setDrag(null); setOver(null) }}
                        onClick={(e) => show(x.id, e.currentTarget)} onDoubleClick={() => nav(`/a/${x.id}`)}
                        onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && noModifier(e)) { e.preventDefault(); show(x.id, e.currentTarget) } }}
                        className={cx('flex cursor-pointer flex-col gap-2.5 rounded-[10px] border border-rule bg-sheet px-3.5 pb-3 pt-3.5 transition hover:border-[#aeb7c6]',
                          on ? 'shadow-[0_0_0_2px_var(--color-accent)]' : 'shadow-[0_1px_2px_rgb(14_20_34/0.05)]', dim(x))}>
                        <div className="flex items-baseline justify-between gap-2.5">
                          <p className="min-w-0 truncate text-base font-semibold leading-[1.2] text-ink">{x.company}</p>
                          <span className="flex-none font-mono text-[11px] text-faint">{short(x.updated)}</span>
                        </div>
                        <p className="text-[13px] leading-[1.3] text-muted text-pretty">{x.role}</p>
                        <div className="flex items-center gap-2.5"><StatusPill status={x.status} outcome={x.outcome} /><Meter a={x} /></div>
                        <div className={cx('-mx-1 -mb-1 mt-0.5 rounded-md px-2 py-[7px]', TONE[nextOf(x).tone][2])}>
                          <NextLine a={x} working={busy?.id === x.id} />
                        </div>
                      </div>
                    )
                  })}
                  {rows.length === 0 && (
                    <div className="rounded-[10px] border-[1.5px] border-dashed border-[#b8c0cd] px-3 py-[22px] text-center text-[13px] text-faint">
                      {query ? 'No matches' : 'Drop a card here'}
                    </div>
                  )}
                  {(rows.length > limit || limit > LANE_LIMIT) && (
                    <div className="flex gap-2">
                      {rows.length > limit && (
                        <button onClick={() => setShownIn((s) => ({ ...s, [k]: limit + LANE_LIMIT }))}
                          title={`${rows.length - limit} more in ${title}`}
                          className="h-9 flex-1 cursor-pointer rounded-lg border border-dashed border-[#aeb7c6] font-medium text-body hover:border-solid hover:bg-sheet">
                          Show {Math.min(LANE_LIMIT, rows.length - limit)} more
                        </button>
                      )}
                      {limit > LANE_LIMIT && (
                        <button onClick={() => setShownIn((s) => ({ ...s, [k]: LANE_LIMIT }))}
                          className="h-9 flex-1 cursor-pointer rounded-lg border border-dashed border-[#aeb7c6] font-medium text-body hover:border-solid hover:bg-sheet">
                          Show fewer
                        </button>
                      )}
                    </div>
                  )}
                </section>
              )
            })}
          </div>
          <p className="hidden font-mono text-[11px] text-faint lg:block">Newest first · drag a card to another column to change its stage · ↑ ↓ to move · Enter to open · Esc to close</p>
        </>
      )}

      {!!apps?.length && view === 'table' && (
        <>
          <div className="overflow-x-auto rounded-[14px] border border-rule bg-sheet">
            <div role="table" aria-label="Applications" className="min-w-[860px]">
              <div role="row" className="grid grid-cols-[minmax(220px,1.6fr)_120px_110px_92px_minmax(200px,1.5fr)_72px] items-center gap-4 border-b border-line bg-wash px-5 py-3 font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-muted">
                <span role="columnheader">Application</span><span role="columnheader">Stage</span><span role="columnheader">Status</span>
                <span role="columnheader">Progress</span><span role="columnheader">Next step</span><span role="columnheader" className="justify-self-end text-accent">Updated ↓</span>
              </div>
              {list.map((x) => {
                const on = open && x.id === sel
                return (
                  <div key={x.id} data-app-id={x.id} role="row" tabIndex={0} aria-haspopup="dialog" aria-current={on ? 'true' : undefined}
                    onClick={(e) => show(x.id, e.currentTarget)} onDoubleClick={() => nav(`/a/${x.id}`)}
                    onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && noModifier(e)) { e.preventDefault(); show(x.id, e.currentTarget) } }}
                    className={cx('grid cursor-pointer grid-cols-[minmax(220px,1.6fr)_120px_110px_92px_minmax(200px,1.5fr)_72px] items-center gap-4 border-b border-[#eef0f4] px-5 py-[13px] transition last:border-b-0 hover:bg-wash',
                      on && 'bg-[#eef1fd] shadow-[inset_3px_0_0_var(--color-accent)]', dim(x))}>
                    <div role="cell" className="min-w-0">
                      <p className="truncate text-[15px] font-semibold text-ink">{x.company}</p>
                      <p className="truncate text-[13px] text-muted">{x.role}</p>
                    </div>
                    <span role="cell" className="text-[13px] text-body">{STAGE_TITLE[STAGE[x.status] ?? 'progress']}</span>
                    <span role="cell" className="justify-self-start"><StatusPill status={x.status} outcome={x.outcome} /></span>
                    <div role="cell" className="flex"><Meter a={x} /></div>
                    <div role="cell" className="min-w-0"><NextLine a={x} working={busy?.id === x.id} /></div>
                    <span role="cell" className="justify-self-end whitespace-nowrap font-mono text-[11px] text-faint">{short(x.updated)}</span>
                  </div>
                )
              })}
              {list.length === 0 && <p className="px-5 py-10 text-center text-faint">No application matches this search.</p>}
            </div>
          </div>
          <p className="hidden font-mono text-[11px] text-faint lg:block">Newest first · ↑ ↓ to move · Enter to open · Esc to close</p>
        </>
      )}

      <div onClick={() => close()} aria-hidden
        className={cx('fixed inset-0 z-40 bg-[rgb(14_20_34/0.28)] transition-opacity duration-200', open ? 'opacity-100' : 'pointer-events-none opacity-0')} />
      <aside ref={panel} role="dialog" aria-modal="true" aria-labelledby="app-detail-title" aria-hidden={!open} inert={!open}
        className={cx('fixed inset-y-0 right-0 z-50 flex w-[min(480px,100%)] flex-col bg-sheet transition-[translate,box-shadow] duration-[280ms] ease-[cubic-bezier(.2,.7,.2,1)]',
          open ? 'translate-x-0 shadow-[-24px_0_60px_-30px_rgb(14_20_34/0.5)]' : 'translate-x-[105%] shadow-none')}>
        {shown && (
          <Sheet key={shown.id} a={shown} detail={shownDetail} busy={busy} notes={(draft?.id === shown.id ? draft.text : null) ?? shown.notes ?? ''}
            closeRef={closeBtn} deleteRef={deleteBtn} confirming={confirming} onConfirming={setConfirming}
            onClose={() => close()} onNotes={(text) => typeNotes(shown.id, text)} onNotesBlur={flushNotes}
            onStatus={(st, o) => void setStatus(shown, st, o)} onAct={(n) => act(shown, n)} onDelete={() => void remove(shown)}
            asking={asking === shown.id} onStopAsking={() => setAsking(null)} />
        )}
      </aside>
    </div>
  )
}

function Sheet({ a, detail, busy, notes, closeRef, deleteRef, confirming, onConfirming: setConfirming, onClose, onNotes, onNotesBlur, onStatus, onAct, onDelete, asking, onStopAsking }: {
  a: AppSummary; detail: Application | null; busy: { id: string; kind: Kind } | null; notes: string
  closeRef: RefObject<HTMLButtonElement | null>; deleteRef: RefObject<HTMLButtonElement | null>
  confirming: boolean; onConfirming: (on: boolean) => void
  onClose: () => void; onNotes: (v: string) => void; onNotesBlur: () => void; onStatus: (s: string, outcome?: Outcome) => void; onAct: (n: Next) => void
  onDelete: () => void; asking: boolean; onStopAsking: () => void
}) {
  const deleting = busy?.id === a.id && busy.kind === 'delete'
  const sentCount = detail?.sent.length ?? (a.sent ? 1 : 0)
  const p = a.progress
  const n = nextOf(a)
  const working = busy?.id === a.id
  const hm = detail?.critique ?? null
  const cov = detail?.ats?.coverage
  const lens = [a.industry, a.track, p?.seniority].filter(Boolean).join(' · ')
  const label = 'font-mono text-[11px] uppercase tracking-[0.08em] text-muted'
  const sentPdf = a.sent?.files.find((f) => f.endsWith('.pdf'))

  return (
    <>
      <div className="flex flex-col gap-3.5 border-b border-line px-[26px] pb-5 pt-[22px]">
        <div className="flex items-center justify-between gap-3">
          <p className="eyebrow">{lens || 'not analyzed yet'}</p>
          <button ref={closeRef} onClick={onClose} aria-label="Close"
            className="size-8 cursor-pointer rounded-lg border border-rule bg-sheet text-base leading-none text-muted hover:border-ink hover:text-ink">×</button>
        </div>
        <div className="flex flex-col gap-1">
          <h2 id="app-detail-title" className="font-display text-[40px] leading-[0.95] text-ink">{a.company}</h2>
          <p className="text-[15px] text-body">{a.role}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <StatusSelect label={`Status for ${a.company}`} status={a.status} outcome={a.outcome} disabled={working} onChange={onStatus} />
          <span className="font-mono text-[11px] text-faint">
            Created {short(a.created)} · updated {short(a.updated)}{a.pages ? ` · ${plural(a.pages, 'page')}` : ''}
          </span>
        </div>
      </div>

      {asking && (
        <div role="group" aria-labelledby={`outcome-title-${a.id}`} className="flex flex-col gap-3 border-b border-line bg-wash px-[26px] py-4">
          <div className="flex items-baseline justify-between gap-3">
            <p id={`outcome-title-${a.id}`} className="font-semibold text-ink">How did it end?</p>
            <button className="cursor-pointer text-[13px] text-muted hover:text-ink" onClick={onStopAsking}>Cancel</button>
          </div>
          {OUTCOME_GROUPS.map(([who, title]) => (
            <div key={who} className="flex flex-col gap-1.5">
              <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-faint">{title}</p>
              <div className="flex flex-wrap gap-1.5">
                {OUTCOMES.filter((o) => o.who === who).map((o) => (
                  <button key={o.key} data-outcome={o.key} disabled={working}
                    className="btn h-8 px-3 py-0 text-[13px]" onClick={() => onStatus('closed', o.key)}>{o.label}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-y-auto">
        <div className="grid grid-cols-4 gap-2.5 border-b border-line px-[26px] py-5">
          {steps(a).map((s) => (
            <div key={s.label} className="flex min-w-0 flex-col gap-1.5">
              <span className={cx('h-1 rounded-sm', s.bar)} />
              <p className="text-[13px] font-semibold text-ink">{s.label}</p>
              <p className={cx('truncate text-xs', s.tone)} title={s.note}>{s.note}</p>
            </div>
          ))}
        </div>

        {n.cta && (
          <div className={cx('mx-[26px] mt-5 flex items-center gap-3.5 rounded-[10px] px-4 py-3.5', TONE[n.tone][2])}>
            <p className={cx('flex-1 text-sm text-pretty', TONE[n.tone][0])}>{working && BUSY_TEXT[busy!.kind] ? BUSY_TEXT[busy!.kind] : n.text}</p>
            <button className="btn btn-primary h-9 flex-none px-3.5" disabled={!!busy} onClick={() => onAct(n)}>
              {working && <Spinner />}{working ? 'Working' : n.cta}
            </button>
          </div>
        )}

        {hm && (
          <div className="flex flex-col gap-3.5 px-[26px] pb-1 pt-[22px]">
            <p className={label}>Hiring manager read</p>
            <span className={cx('font-display text-[32px] capitalize leading-none', VERDICT[hm.latest.verdict.decision])}>{hm.latest.verdict.decision}</span>
            <p className="text-[15px] leading-[1.45] text-body text-pretty">“{hm.latest.verdict.reason}”</p>
            {hm.stale && <p className="text-[13px] text-[#7a4700]">The resume changed since this read. Re-run it in Review for fresh scores.</p>}
            <div className="grid grid-cols-4 rounded-[10px] border border-line">
              {SCORES.map((k, i) => {
                const v = hm.latest.scores[k].score, prev = hm.previous_scores?.[k]?.score
                const d = prev === undefined ? 0 : v - prev
                return (
                  <div key={k} title={hm.latest.scores[k].why} className={cx('flex flex-col gap-1 p-3', i > 0 && 'shadow-[inset_1px_0_0_var(--color-line)]')}>
                    <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-faint">{k}</span>
                    <span className="flex items-baseline gap-1.5">
                      <span className="font-display text-[28px] leading-none text-ink">{v}</span>
                      {d !== 0 && <span className={cx('font-mono text-[11px]', d > 0 ? 'text-ok' : 'text-bad')}>{d > 0 ? `+${d}` : d}</span>}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {cov && (
          <div className="flex flex-col gap-3 px-[26px] pb-1 pt-[22px]">
            <p className={label}>Keyword coverage</p>
            {(['must', 'nice'] as const).map((k) => {
              const { hit, total } = cov[k]
              const pct = total ? Math.round((hit / total) * 100) : 0
              return (
                <div key={k} className="grid grid-cols-[48px_minmax(0,1fr)_48px] items-center gap-3 text-[13px]">
                  <span className="capitalize text-muted">{k}</span>
                  <div className="h-1.5 rounded-[3px] bg-paper">
                    <div className={cx('h-full rounded-[3px]', k === 'nice' ? 'bg-faint' : hit === total ? 'bg-ok' : 'bg-[#c47a00]')} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="justify-self-end font-mono text-xs text-ink">{hit}/{total}</span>
                </div>
              )
            })}
          </div>
        )}

        <div className="flex flex-col gap-2 px-[26px] py-[22px]">
          <label className={label} htmlFor={`notes-${a.id}`}>Notes</label>
          <textarea id={`notes-${a.id}`} rows={3} className="field resize-y bg-wash px-3 py-2.5 text-sm focus:bg-sheet"
            placeholder="Recruiter, interview dates, anything to remember" value={notes}
            onChange={(e) => onNotes(e.target.value)} onBlur={onNotesBlur} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-line bg-wash px-[26px] py-3.5">
        {a.files.map((f) => (
          <a key={f} href={api.fileUrl(a.id, f, true)} title={a.outputs_stale ? 'Outdated: the resume changed after this was built' : f}
            className={cx('inline-flex h-[30px] items-center rounded-md border border-rule bg-sheet px-2.5 font-mono text-[11px] uppercase text-body hover:border-accent hover:text-accent',
              a.outputs_stale && 'line-through opacity-55')}>
            ↓ {f.split('.').pop()}
          </a>
        ))}
        {a.sent && sentPdf && (
          <a href={api.sentFileUrl(a.id, a.sent.id, sentPdf, true)} title={`Exact copy sent on ${short(a.sent.created)}`}
            className="inline-flex h-[30px] items-center rounded-md bg-[#dcefe5] px-2.5 font-mono text-[11px] uppercase text-ok hover:bg-ok hover:text-white">✓ sent</a>
        )}
        {!a.files.length && !a.sent && <span className="text-[13px] text-faint">No files built yet</span>}
        <Link to={`/a/${a.id}`} className="btn btn-dark ml-auto h-9 px-3.5 hover:text-white">Open workspace →</Link>
      </div>

      {confirming ? (
        <div role="alertdialog" aria-labelledby={`del-title-${a.id}`} aria-describedby={`del-desc-${a.id}`}
          className="flex flex-col gap-3 border-t border-bad/30 bg-bad-soft px-[26px] py-4">
          <p id={`del-title-${a.id}`} className="font-semibold text-bad">Delete {a.company} — {a.role}?</p>
          <p id={`del-desc-${a.id}`} className="text-[13px] leading-[1.45] text-body text-pretty">
            This permanently removes its job description, analysis, tailored resume and built files
            {sentCount ? <>, and <strong>{sentCount === 1 ? 'the read-only copy you sent' : `${sentCount} read-only sent copies`}</strong></> : null}.
            Your master profile and remembered answers are kept. This can’t be undone.
          </p>
          <div className="flex flex-wrap gap-2">
            <button autoFocus className="btn h-9 px-3.5" disabled={deleting} onClick={() => setConfirming(false)}>Cancel</button>
            <button className="btn h-9 border-bad bg-bad px-3.5 font-semibold text-white hover:border-[#8f1c13] hover:bg-[#8f1c13]"
              disabled={deleting} onClick={onDelete}>
              {deleting && <Spinner />}{deleting ? 'Deleting…' : 'Delete permanently'}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex justify-end border-t border-line px-[26px] py-2">
          <button ref={deleteRef} className="cursor-pointer rounded-md px-2 py-1 text-[13px] text-muted hover:bg-bad-soft hover:text-bad disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!!busy} onClick={() => setConfirming(true)}>
            Delete application…
          </button>
        </div>
      )}
    </>
  )
}
