import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { api, type AppAnswer, type Claim, type CritiqueIssue, type Issue, type Profile, type Tailored } from '../../api'
import { cx } from '../../lib'
import { pageLimit, pagesText, useSettings } from '../../settings'
import { ErrorNote, SaveDock, Spinner, Stamp } from '../../ui'
import type { StepProps } from '../Workspace'
import { applyIssue, findsTarget, issueTargets, openIssues } from './critique'
import { btn, btnPrimary, label, sheetCard } from './v3'
import { HiringManagerCard, ReviewIssue, type ReviewActions } from './HiringManager'

const clone = <T,>(x: T): T => structuredClone(x)
function move<T>(list: T[], i: number, d: number): T[] {
  const j = i + d
  if (j < 0 || j >= list.length) return list
  const out = [...list]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

const card = 'rounded-xl border border-rule bg-sheet'
// The sheet reads like the real resume (Calibri), not like the app chrome.
const SHEET_FONT: CSSProperties = { fontFamily: "Calibri, Carlito, sans-serif" }

/** Textarea that grows with its content (and re-fits when the window resizes). */
function AutoText({ value, onChange, onFocus, onBlur, className, ariaLabel }: {
  value: string; onChange: (v: string) => void; onFocus?: () => void; onBlur?: () => void; className?: string; ariaLabel: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => { el.style.height = '0px'; el.style.height = `${el.scrollHeight + 2}px` }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [value])
  return (
    <textarea
      ref={ref}
      rows={1}
      aria-label={ariaLabel}
      value={value}
      onFocus={onFocus}
      onBlur={onBlur}
      onChange={(e) => onChange(e.target.value)}
      className={cx('block w-full resize-none overflow-hidden', className)}
    />
  )
}

function Issues({ list }: { list: Issue[] }) {
  if (!list.length) return null
  return (
    <ul className="mt-1 space-y-0.5">
      {list.map((e, i) => <li key={i} className="text-xs text-bad">⚠ {e.message}</li>)}
    </ul>
  )
}

/** Resolve "experience[0].bullets[2]"-style paths without eval. */
function claimAt(root: unknown, path: string): Claim | null {
  let cur: unknown = root
  for (const [, key, index] of path.matchAll(/([A-Za-z_]+)(?:\[(\d+)\])?/g)) {
    if (cur === null || typeof cur !== 'object') return null
    cur = (cur as Record<string, unknown>)[key]
    if (index !== undefined) cur = Array.isArray(cur) ? cur[Number(index)] : undefined
  }
  return cur && typeof cur === 'object' && 'sources' in cur ? (cur as Claim) : null
}

/** An editable claim on the sheet: where it sits, and how to change it. */
interface Line {
  path: string
  where: string
  claim: Claim
  roleId?: string
  italic?: boolean
  set: (d: Tailored, c: Claim) => void
  remove?: (d: Tailored) => void
  move?: (d: Tailored, dir: number) => void
  index?: number
  count?: number
}

function linesOf(t: Tailored, p: Profile): Line[] {
  const out: Line[] = []
  if (t.summary) out.push({ path: 'summary', where: 'Summary', claim: t.summary, set: (d, c) => { d.summary = c } })
  t.highlights.forEach((h, i) => out.push({
    path: `highlights[${i}]`, where: `Career highlight ${i + 1}`, claim: h, index: i, count: t.highlights.length,
    set: (d, c) => { d.highlights[i] = c },
    remove: (d) => { d.highlights.splice(i, 1) },
    move: (d, dir) => { d.highlights = move(d.highlights, i, dir) },
  }))
  t.experience.forEach((tr, i) => {
    const role = p.roles.find((r) => r.id === tr.role)
    const name = role?.employer ?? tr.role
    if (tr.scope) out.push({
      path: `experience[${i}].scope`, where: `${name} · scope`, claim: tr.scope, roleId: role?.id, italic: role?.scope?.italic !== false,
      set: (d, c) => { d.experience[i].scope = c },
      remove: (d) => { d.experience[i].scope = null },
    })
    tr.bullets.forEach((b, j) => out.push({
      path: `experience[${i}].bullets[${j}]`, where: `${name} · bullet ${j + 1}`, claim: b, roleId: role?.id, index: j, count: tr.bullets.length,
      set: (d, c) => { d.experience[i].bullets[j] = c },
      remove: (d) => { d.experience[i].bullets.splice(j, 1) },
      move: (d, dir) => { d.experience[i].bullets = move(d.experience[i].bullets, j, dir) },
    }))
  })
  return out
}

const lineDomId = (path: string) => `line-${path.replace(/[^a-z0-9]+/gi, '-')}`
const withIndex = (path: string, n: number) => path.replace(/\[\d+\]$/, `[${n}]`)

/** The "Selected line" editor: the wording, the evidence it cites, its fact-check and review notes. */
function LineEditor({ line, evidence, roleIds, issues, review, actions, onChange, onRemove, onMove }: {
  line: Line; evidence: Record<string, string>; roleIds: string[]; issues: Issue[]
  review: CritiqueIssue[]; actions: ReviewActions
  onChange: (c: Claim) => void; onRemove?: () => void; onMove?: (dir: number) => void
}) {
  const { claim, roleId } = line
  // A role's claims may cite that role's evidence or any non-role evidence (summary, highlights, projects…).
  const options = Object.keys(evidence).filter((id) =>
    !claim.sources.includes(id) && (!roleId || id.startsWith(roleId) || !roleIds.some((r) => id.startsWith(r))))
  return (
    <div className="flex flex-col gap-2.5">
      <AutoText ariaLabel={`Edit ${line.where}`} value={claim.text} onChange={(text) => onChange({ ...claim, text })}
        className={cx('field min-h-[76px] px-2.5 text-sm leading-[1.45]', line.italic && 'italic')} />
      <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Cites</p>
      {claim.sources.map((s) => (
        <div key={s} className="grid grid-cols-[minmax(0,100px)_minmax(0,1fr)_14px] items-start gap-2.5 text-xs">
          <span className={cx('break-all font-mono', evidence[s] ? 'text-accent' : 'text-bad')}>{s}</span>
          <span className="text-body">{evidence[s]?.split('\n')[0] ?? 'Unknown evidence id'}</span>
          <button className="cursor-pointer text-faint hover:text-bad" onClick={() => onChange({ ...claim, sources: claim.sources.filter((x) => x !== s) })}
            aria-label={`Remove source ${s}`}>×</button>
        </div>
      ))}
      {!claim.sources.length && <p className="text-xs text-bad">No sources: this claim can’t be verified.</p>}
      <select
        className="chip w-auto max-w-full cursor-pointer self-start border-dashed border-rule bg-transparent hover:border-accent hover:text-accent"
        value=""
        onChange={(e) => e.target.value && onChange({ ...claim, sources: [...claim.sources, e.target.value] })}
        aria-label="Add a source"
      >
        <option value="">+ cite evidence</option>
        {options.map((id) => <option key={id} value={id}>{id}: {(evidence[id] ?? '').split('\n')[0].slice(0, 70)}</option>)}
      </select>
      <Issues list={issues} />
      {review.map((i) => <ReviewIssue key={i.id} issue={i} actions={actions} compact />)}
      {(onMove || onRemove) && (
        <div className="flex flex-wrap gap-1 border-t border-rule pt-2 text-xs">
          {onMove && <button className="btn btn-ghost px-2 py-1 text-xs" disabled={line.index === 0} onClick={() => onMove(-1)}>↑ Up</button>}
          {onMove && <button className="btn btn-ghost px-2 py-1 text-xs" disabled={line.index === (line.count ?? 0) - 1} onClick={() => onMove(1)}>↓ Down</button>}
          {onRemove && <button className="btn btn-ghost ml-auto px-2 py-1 text-xs text-bad" onClick={onRemove}>Remove line</button>}
        </div>
      )}
    </div>
  )
}

function AddFromEvidence({ evidence, ids, onAdd, label }: { evidence: Record<string, string>; ids: string[]; onAdd: (id: string) => void; label: string }) {
  return (
    <select className="mt-1 block w-auto max-w-full cursor-pointer truncate rounded-lg border border-dashed border-rule bg-transparent px-2 py-1 font-sans text-xs text-muted hover:border-accent hover:text-accent" value="" onChange={(e) => e.target.value && onAdd(e.target.value)} aria-label={label}>
      <option value="">+ {label}</option>
      {ids.map((id) => <option key={id} value={id}>{id}: {(evidence[id] ?? id).split('\n')[0].slice(0, 90)}</option>)}
    </select>
  )
}

/** Free-typing field for "a · b · c" lists: parsed only on blur, so typing isn't fought. */
function ItemsField({ items, onCommit, ariaLabel }: { items: string[]; onCommit: (items: string[]) => void; ariaLabel: string }) {
  const joined = items.join(' · ')
  const [text, setText] = useState(joined)
  const [editing, setEditing] = useState(false)
  const value = editing ? text : joined
  return (
    <AutoText
      ariaLabel={ariaLabel}
      value={value}
      className="-mx-1 rounded-[5px] border border-transparent bg-transparent px-1 leading-[1.45] hover:border-rule focus:border-accent focus:bg-sheet focus:outline-none"
      onFocus={() => { setText(joined); setEditing(true) }}
      onChange={setText}
      onBlur={() => {
        setEditing(false)
        const next = text.split('·').map((x) => x.trim()).filter(Boolean)
        if (next.join(' · ') !== joined) onCommit(next)
      }}
    />
  )
}

function H({ children }: { children: string }) {
  return <p className="border-b border-ink pb-[3px] text-xs font-semibold uppercase tracking-[0.14em] text-ink">{children}</p>
}

export default function Review({ app, profile, setApp, go, run, memo, setMemo }: StepProps) {
  const settings = useSettings()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [focus, setFocusState] = useState<string | null>(null)

  // Local edits live in Workspace (memo.review) so they survive switching steps.
  const draft: Tailored = memo.review?.draft ?? app.tailored!
  const dirty = !!memo.review

  const p = profile.profile
  const evidence = profile.evidence
  const roleIds = p.roles.map((r) => r.id)
  const report = app.report
  const issuesAt = (path: string) => (dirty ? [] : report?.errors.filter((e) => e.where === path) ?? [])

  const update = (fn: (d: Tailored) => void) =>
    setMemo((m) => {
      const next = clone(m.review?.draft ?? app.tailored!)
      fn(next)
      return { ...m, review: { ...m.review, draft: next, rev: (m.review?.rev ?? 0) + 1 } }
    })

  const lines = useMemo(() => linesOf(draft, p), [draft, p])
  const byPath = useMemo(() => Object.fromEntries(lines.map((l) => [l.path, l])), [lines])
  const selected = focus ? byPath[focus] : undefined
  const changed = (path: string) => dirty && JSON.stringify(claimAt(app.tailored, path)) !== JSON.stringify(claimAt(draft, path))
  const setFocus = (path: string | null, scroll = false) => {
    setFocusState(path)
    if (path && scroll) requestAnimationFrame(() => document.getElementById(lineDomId(path))?.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }))
  }

  async function save() {
    const sentRev = memo.review?.rev
    setSaving(true)
    setError(null)
    try {
      setApp(await api.saveTailored(app.id, draft))
      // Keep anything typed while the save was in flight.
      setMemo((m) => (m.review && m.review.rev === sentRev ? { ...m, review: null } : m))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }
  const discard = () => setMemo((m) => ({ ...m, review: null }))

  // ---- hiring-manager review -----------------------------------------------------------
  const critique = app.critique
  const open = openIssues(critique)
  const reviewFor = (claim: Claim) => open.filter((i) => i.original && issueTargets(i, claim))
  const isInline = (i: CritiqueIssue) => !!i.original && findsTarget(draft, i)

  async function saveDecisions(decisions: Record<string, 'accepted' | 'rejected'>) {
    try {
      const c = await api.saveCritiqueDecisions(app.id, decisions)
      setApp((prev) => ({ ...prev, critique: c }))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const reviewActions: ReviewActions = {
    decide: (issue, decision) => {
      if (decision === 'accepted' && issue.action !== 'advice') {
        if (!findsTarget(draft, issue)) { setError('That line has changed since the review. Re-run the review.'); return }
        update((d) => applyIssue(d, issue))
        // Keep the selection on the same line when the fix moves or removes it.
        if (focus && selected && issueTargets(issue, selected.claim)) {
          if (issue.action === 'remove') setFocus(null)
          else if (issue.action === 'move_to_top') setFocus(withIndex(focus, 0))
        }
      }
      void saveDecisions({ [issue.id]: decision })
    },
    answer: async (issue) => {
      const qid = `hm-${issue.id}`
      const entry: AppAnswer = { question_id: qid, requirement: 'Hiring-manager review', question: issue.question!, answer: '', status: 'draft' }
      try {
        const saved = await api.saveAnswers(app.id, [...app.answers.filter((a) => a.question_id !== qid), entry])
        setApp((prev) => ({ ...prev, answers: saved }))
        setMemo((m) => ({ ...m, gaps: null, gapFocus: qid }))  // re-seed Gaps so the new question shows, opened
        await saveDecisions({ [issue.id]: 'accepted' })
        go('gaps')
      } catch (e) {
        setError((e as Error).message)
      }
    },
  }

  function acceptAll() {
    const next = clone(draft)
    const decided: Record<string, 'accepted'> = {}
    for (const i of open.filter((x) => x.action !== 'advice')) {
      if (findsTarget(next, i)) { applyIssue(next, i); decided[i.id] = 'accepted' }
    }
    setMemo((m) => ({ ...m, review: { ...m.review, draft: next, rev: (m.review?.rev ?? 0) + 1 } }))
    setFocus(null)
    void saveDecisions(decided)
  }

  const runReview = () =>
    run('Reviewing as the hiring manager', [
      'Reading it as the hiring manager for this role…',
      'Skimming the top third like a recruiter…',
      'Writing specific fixes and fact-checking each one…',
    ], async () => setApp(await api.critique(app.id)))

  const ats = app.ats
  const usedProjects = new Set(draft.projects.map((x) => x.id))
  const length = app.length

  const editorFor = (l: Line) => (
    <LineEditor line={l} evidence={evidence} roleIds={roleIds} issues={issuesAt(l.path)} review={reviewFor(l.claim)} actions={reviewActions}
      onChange={(c) => update((d) => l.set(d, c))}
      onRemove={l.remove && (() => { update((d) => l.remove!(d)); setFocus(null) })}
      onMove={l.move && ((dir: number) => {
        const to = (l.index ?? 0) + dir
        if (to < 0 || to >= (l.count ?? 0)) return
        update((d) => l.move!(d, dir))
        setFocus(withIndex(l.path, to))
      })} />
  )

  /** One claim on the sheet: click to select it; selected lines get their editor (inline below lg). */
  const line = (path: string, bullet = true) => {
    const l = byPath[path]
    if (!l) return null
    const on = focus === path
    const errs = issuesAt(path)
    const hm = reviewFor(l.claim).length
    return (
      <div key={path}>
        <div id={lineDomId(path)} role="button" tabIndex={0} aria-pressed={on}
          onClick={() => setFocus(path)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFocus(path) } }}
          className={cx('-mx-1.5 flex cursor-pointer gap-2 rounded-[5px] px-1.5 py-[3px] leading-[1.45] text-body transition-colors',
            on ? 'bg-accent-soft ring-1 ring-inset ring-accent/30' : errs.length ? 'bg-bad-soft/60 ring-1 ring-inset ring-bad/30 hover:bg-bad-soft' : 'hover:bg-wash')}>
          {bullet && <span className="flex-none text-faint">•</span>}
          <span className={cx('min-w-0 flex-1 break-words', l.italic && 'italic text-muted')}>{l.claim.text || <span className="italic text-faint">(empty line)</span>}</span>
          {(changed(path) || errs.length > 0 || hm > 0) && (
            <span className="flex flex-none items-center gap-1 self-start pt-[5px]">
              {changed(path) && <span title="Unsaved edit" className="size-1.5 rounded-full bg-warn" />}
              {errs.length > 0 && <span title={errs.map((e) => e.message).join('\n')} className="rounded-[5px] bg-bad-soft px-[5px] font-mono text-[10px] leading-4 text-bad">FIX</span>}
              {hm > 0 && <span title="Hiring-manager suggestion" className="rounded-[5px] border border-accent/30 bg-accent-soft px-[5px] font-mono text-[10px] leading-4 text-accent">HM</span>}
            </span>
          )}
        </div>
        {on && <div className={cx(card, 'my-2 p-3 font-sans text-[14px] lg:hidden')}>{editorFor(l)}</div>}
      </div>
    )
  }

  const stamp = dirty
    ? <span className="animate-stamp inline-block rounded border-2 border-warn px-3 py-1 font-mono text-xs font-medium uppercase tracking-[0.2em] text-warn">Unsaved</span>
    : report && <Stamp ok={report.ok}>{report.ok ? 'Verified' : `${report.errors.length} issue${report.errors.length > 1 ? 's' : ''}`}</Stamp>

  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_360px]">
      {memo.review?.notice && (
        <p role="status" className="animate-rise rounded-lg bg-accent-soft px-4 py-3 text-[13px] text-accent text-pretty lg:col-span-2">{memo.review.notice}</p>
      )}
      {/* ---------------------------------------------------------------- the sheet */}
      <article className={`${sheetCard} animate-rise flex min-w-0 flex-col gap-[18px] px-4 py-7 text-[14px] sm:px-12 sm:py-10`} style={SHEET_FONT}>
        {app.sent.length > 0 && (
          <p className="rounded-lg bg-ok-soft px-3 py-2 font-sans text-xs text-ok">
            You sent a frozen copy on {new Date(app.sent[0].created).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })}.
            Edits here won’t change it. Find it under Export → Sent copies.
          </p>
        )}
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="text-2xl font-semibold uppercase tracking-[0.04em] text-ink">{p.contact.name}</p>
          <p className="text-xs text-muted">
            {[p.contact.location, p.contact.phone, p.contact.email, ...p.contact.links.map((l) => l.text)].filter(Boolean).join(' · ')}
            <span className="ml-1.5 text-faint" title="Locked: comes from your profile">🔒</span>
          </p>
          <select
            aria-label="Headline"
            className="mt-1.5 w-auto min-w-0 max-w-full cursor-pointer rounded-[5px] border border-transparent bg-transparent px-1 text-center text-[14px] font-semibold text-accent [text-align-last:center] hover:border-rule"
            value={draft.headline}
            onChange={(e) => update((d) => { d.headline = e.target.value })}
          >
            {!p.headlines.some((h) => h.id === draft.headline) && <option value={draft.headline} disabled>Choose a headline…</option>}
            {p.headlines.map((h) => <option key={h.id} value={h.id}>{h.text} ({h.tracks.join(', ')})</option>)}
          </select>
          <Issues list={issuesAt('headline')} />
        </div>

        {draft.summary && (
          <section className="flex flex-col gap-1.5">
            <H>Summary</H>
            {line('summary', false)}
          </section>
        )}

        <section className="flex flex-col gap-1.5">
          <H>Career highlights</H>
          <div className="flex flex-col gap-0.5">
            {draft.highlights.map((_, i) => line(`highlights[${i}]`))}
          </div>
          <AddFromEvidence evidence={evidence} label="add highlight from evidence" ids={Object.keys(evidence)}
            onAdd={(id) => { update((d) => { d.highlights.push({ text: evidence[id].split('\n')[0], sources: [id] }) }); setFocus(`highlights[${draft.highlights.length}]`) }} />
        </section>

        <section className="flex flex-col gap-1.5">
          <H>Core competencies</H>
          {draft.competencies.map((g, i) => {
            const issues = g.items.flatMap((_, j) => issuesAt(`competencies[${i}].items[${j}]`))
            return (
              <div key={i} className={cx('group/claim -mx-1.5 rounded-[5px] px-1.5', issues.length > 0 && 'bg-bad-soft/60 ring-1 ring-inset ring-bad/30')}>
                <div className="flex flex-wrap items-baseline gap-x-1 sm:flex-nowrap">
                  <span className="flex shrink-0 items-baseline font-semibold text-ink">
                    {/* the invisible copy sizes the input to its text */}
                    <span className="inline-grid">
                      <span className="invisible col-start-1 row-start-1 whitespace-pre border border-transparent px-px" aria-hidden>{g.label || 'Group'}</span>
                      <input aria-label={`Competency group ${i + 1}`} size={1}
                        className="col-start-1 row-start-1 w-full min-w-0 rounded-[5px] border border-transparent bg-transparent px-px hover:border-rule focus:border-accent focus:outline-none"
                        value={g.label} onChange={(e) => update((d) => { d.competencies[i].label = e.target.value })} />
                    </span>
                    :
                  </span>
                  <div className="min-w-0 flex-1"><ItemsField ariaLabel={`Competency items ${i + 1}`} items={g.items} onCommit={(items) => update((d) => { d.competencies[i].items = items })} /></div>
                  <div className="flex shrink-0 opacity-0 transition group-focus-within/claim:opacity-100 group-hover/claim:opacity-100">
                    <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.competencies = move(d.competencies, i, -1) })} aria-label="Move up">↑</button>
                    <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.competencies = move(d.competencies, i, 1) })} aria-label="Move down">↓</button>
                  </div>
                </div>
                <Issues list={[...issuesAt(`competencies[${i}].label`), ...issuesAt(`competencies[${i}]`), ...issues]} />
              </div>
            )
          })}
          <p className="font-sans text-xs text-faint">Separate items with “·”. Every item must be a skill from your profile. Remove a group by clearing its items.</p>
        </section>

        <section className="flex flex-col gap-1.5">
          <H>Professional experience</H>
          {draft.experience.map((tr, i) => {
            const role = p.roles.find((r) => r.id === tr.role)
            if (!role) return <Issues key={i} list={[{ where: '', message: `unknown role ${tr.role}` }]} />
            const ids = Object.keys(evidence).filter((id) => id.startsWith(`${role.id}.a`) || id === `${role.id}.scope`)
            return (
              <div key={tr.role} className="flex flex-col gap-0.5">
                <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3">
                  <p className="text-ink">
                    <span className="font-semibold">{role.employer}</span> · {role.location}
                    <span className="ml-1.5 text-faint" title="Locked: employer, title and dates come from your profile">🔒</span>
                  </p>
                  <p className="shrink-0 text-[13px] text-muted">{role.dates}</p>
                </div>
                <p className="font-semibold text-accent">{role.title}</p>
                {tr.scope && line(`experience[${i}].scope`, false)}
                {tr.bullets.map((_, j) => line(`experience[${i}].bullets[${j}]`))}
                {tr.sub_roles.map((sr) => {
                  const item = role.sub_roles.find((s) => s.id === sr.id)
                  return (
                    <div key={sr.id} className="group/claim -mx-1.5 flex gap-2 px-1.5 py-[3px] leading-[1.45]">
                      <span className="flex-none text-faint">•</span>
                      <p className="min-w-0 flex-1"><span className="font-semibold text-ink">{item?.label}</span> {sr.text?.text ?? item?.text}</p>
                      <button className="px-1 text-faint opacity-0 transition hover:text-bad focus:opacity-100 group-hover/claim:opacity-100" onClick={() => update((d) => { d.experience[i].sub_roles = d.experience[i].sub_roles.filter((x) => x.id !== sr.id) })} aria-label="Remove sub-role">✕</button>
                    </div>
                  )
                })}
                <AddFromEvidence evidence={evidence} label="add bullet from this role’s evidence" ids={ids}
                  onAdd={(id) => { update((d) => { d.experience[i].bullets.push({ text: evidence[id].split('\n')[0], sources: [id] }) }); setFocus(`experience[${i}].bullets[${tr.bullets.length}]`) }} />
                <Issues list={issuesAt(`experience[${i}]`)} />
              </div>
            )
          })}
        </section>

        <section className="flex flex-col gap-1.5">
          <H>Projects & community leadership</H>
          {draft.projects.map((tp, i) => {
            const item = p.projects.find((x) => x.id === tp.id)
            return (
              <div key={tp.id} className="group/claim -mx-1.5 flex gap-2 px-1.5 py-[3px] leading-[1.45]">
                <span className="flex-none text-faint">•</span>
                <p className="min-w-0 flex-1"><span className="font-semibold text-ink">{item?.label}</span> {tp.text?.text ?? item?.text}</p>
                <div className="flex shrink-0 opacity-0 transition group-focus-within/claim:opacity-100 group-hover/claim:opacity-100">
                  <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.projects = move(d.projects, i, -1) })} aria-label="Move up">↑</button>
                  <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.projects = move(d.projects, i, 1) })} aria-label="Move down">↓</button>
                  <button className="px-1 text-faint hover:text-bad" onClick={() => update((d) => { d.projects.splice(i, 1) })} aria-label="Remove">✕</button>
                </div>
              </div>
            )
          })}
          {p.projects.some((x) => !usedProjects.has(x.id)) && (
            <AddFromEvidence evidence={evidence} label="add project" ids={p.projects.filter((x) => !usedProjects.has(x.id)).map((x) => x.id)} onAdd={(id) => update((d) => { d.projects.push({ id }) })} />
          )}
        </section>

        {(['education', 'extras'] as const).map((key) => (
          <section key={key} className="flex flex-col gap-1.5">
            <H>{key === 'education' ? 'Education & certifications' : 'Awards & languages'}</H>
            {p[key].map((item) => {
              const on = draft[key].includes(item.id)
              return (
                <label key={item.id} className={cx('flex cursor-pointer gap-2 leading-[1.45]', !on && 'text-faint line-through')}>
                  <input type="checkbox" className="mt-1 accent-accent" checked={on} onChange={() => update((d) => { d[key] = on ? d[key].filter((x) => x !== item.id) : p[key].map((x) => x.id).filter((x) => x === item.id || d[key].includes(x)) })} />
                  <span><span className="font-semibold">{item.label}</span> {item.text}</span>
                </label>
              )
            })}
          </section>
        ))}
      </article>

      {/* ---------------------------------------------------------------- margin */}
      <aside className="animate-rise flex min-w-0 flex-col gap-4 lg:sticky lg:top-[76px] lg:-mx-1 lg:max-h-[calc(100vh-92px)] lg:overflow-y-auto lg:px-1 lg:pb-2" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between gap-3 pt-1">
          {stamp}
          {length && (
            <span className={cx('font-mono text-[11px]', length.lines > length.budget ? 'text-warn' : 'text-faint')}
              title={`Estimated lines, against the budget for ${pagesText(pageLimit(settings))}`}>
              ~{length.lines} of {length.budget} lines
            </span>
          )}
        </div>
        <p className="-mt-1 text-[13px] text-muted">
          {dirty ? 'Save to re-run the fact-check.' : report?.ok ? 'Every claim traces to your profile.' : report ? 'Fix the flagged lines: cite the right evidence, reword to match it, or remove them.' : ''}
          {app.meta.repair_rounds ? <span className="block text-xs text-faint">The AI self-repaired {app.meta.repair_rounds} fact-check round{app.meta.repair_rounds > 1 ? 's' : ''}.</span> : null}
        </p>
        {!dirty && report && (report.errors.length > 0 || report.warnings.length > 0) && (
          <section className={cx(card, 'flex flex-col gap-2 px-[18px] py-3.5 text-xs')}>
            {report.errors.length > 0 && (
              <ul className="max-h-56 space-y-1 overflow-auto text-bad">
                {report.errors.map((e, i) => (
                  <li key={i}>
                    {byPath[e.where]
                      ? <button className="cursor-pointer text-left hover:underline" onClick={() => setFocus(e.where, true)}><span className="font-mono text-[10px] text-faint">{e.where}</span> {e.message}</button>
                      : <><span className="font-mono text-[10px] text-faint">{e.where}</span> {e.message}</>}
                  </li>
                ))}
              </ul>
            )}
            {report.warnings.length > 0 && (
              <ul className={cx('space-y-1 text-warn', report.errors.length > 0 && 'border-t border-rule pt-2')}>
                {report.warnings.map((w, i) => <li key={i}>{w.message}</li>)}
              </ul>
            )}
          </section>
        )}

        <ErrorNote error={error} onDismiss={() => setError(null)} />

        <section className={cx(card, 'hidden flex-col gap-2.5 px-[18px] py-4 lg:flex')}>
          <div className="flex items-baseline justify-between gap-3">
            <p className={label}>Selected line</p>
            {selected && <span className="truncate text-xs text-faint">{selected.where}</span>}
          </div>
          {selected ? editorFor(selected) : (
            <p className="text-[13px] text-muted">Click any line on the resume to edit it and see the evidence it cites, side by side.</p>
          )}
        </section>

        <HiringManagerCard critique={critique} dirty={dirty} canRun={!dirty && !!report?.ok}
          onRun={runReview} onAcceptAll={acceptAll} actions={reviewActions} isInline={isInline} />

        {ats && (
          <section className="flex flex-col gap-2">
            <p className={label}>
              Keywords · must {ats.coverage.must.hit}/{ats.coverage.must.total}
              {ats.coverage.nice.total > 0 && <span className="text-muted"> · nice {ats.coverage.nice.hit}/{ats.coverage.nice.total}</span>}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {ats.keywords.map((kw) => (
                <span
                  key={kw.term}
                  title={{ in_resume: 'In the resume', unused: 'You have evidence but it isn’t used. Consider surfacing it.', gap: 'No evidence in your profile' }[kw.status]}
                  className={cx('rounded-full border px-[9px] py-0.5 text-xs', {
                    in_resume: 'border-transparent bg-[#dcefe5] text-ok',
                    unused: 'border-warn bg-sheet text-warn',
                    gap: 'border-rule bg-sheet text-faint',
                  }[kw.status])}
                >
                  {kw.term}
                </span>
              ))}
            </div>
            <p className="font-mono text-[11px] text-faint">{ats.words} words · green in resume · amber evidence unused · grey no evidence</p>
          </section>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          {dirty ? (
            <>
              <button className={btn} onClick={discard} disabled={saving}>Discard</button>
              <button className={btnPrimary} onClick={save} disabled={saving}>{saving ? <><Spinner /> Checking…</> : 'Save & fact-check'}</button>
            </>
          ) : (
            <button className={btnPrimary} disabled={!report?.ok} onClick={() => go('export')}
              title={report?.ok ? undefined : 'Fix the fact-check issues first'}>Continue to export →</button>
          )}
        </div>
      </aside>

      {/* the margin's Save sits far below the sheet on small screens */}
      <div className="lg:hidden">
        <SaveDock dirty={dirty} text="Unsaved edits" busy={saving} flash={null} onSave={save} onDiscard={discard} saveLabel="Save & check" />
      </div>
    </div>
  )
}
