import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api, type Claim, type Issue, type Tailored } from '../../api'
import { cx, ErrorNote, Spinner, Stamp } from '../../ui'
import type { StepProps } from '../Workspace'
import Cite from './Cite'

const clone = <T,>(x: T): T => structuredClone(x)
function move<T>(list: T[], i: number, d: number): T[] {
  const j = i + d
  if (j < 0 || j >= list.length) return list
  const out = [...list]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

function AutoText({ value, onChange, onFocus, onBlur, className, ariaLabel }: {
  value: string; onChange: (v: string) => void; onFocus?: () => void; onBlur?: () => void; className?: string; ariaLabel: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (el) { el.style.height = '0px'; el.style.height = `${el.scrollHeight}px` }
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
      className={cx('block w-full resize-none overflow-hidden rounded-sm border border-transparent bg-transparent px-1 -mx-1 leading-relaxed transition hover:border-rule focus:border-rust focus:bg-sheet focus:outline-none', className)}
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

interface Ctx {
  evidence: Record<string, string>
  roleIds: string[]
  focus: string | null
  setFocus: (path: string) => void
  issuesAt: (path: string) => Issue[]
}

function ClaimEditor({ ctx, path, claim, onChange, onRemove, onMove, roleId, className }: {
  ctx: Ctx; path: string; claim: Claim; onChange: (c: Claim) => void
  onRemove?: () => void; onMove?: (d: number) => void; roleId?: string; className?: string
}) {
  const { evidence, roleIds, focus, setFocus, issuesAt } = ctx
  const issues = issuesAt(path)
  const active = focus === path
  // A role's claims may cite that role's evidence or any non-role evidence (summary, highlights, projects…).
  const options = Object.keys(evidence).filter((id) =>
    !claim.sources.includes(id) && (!roleId || id.startsWith(roleId) || !roleIds.some((r) => id.startsWith(r))))
  return (
    <div className={cx('group/claim relative rounded-sm', issues.length > 0 && 'bg-bad-soft/60 ring-1 ring-bad/30', className)}>
      <div className="flex gap-2">
        <div className="min-w-0 flex-1">
          <AutoText ariaLabel={path} value={claim.text} onFocus={() => setFocus(path)} onChange={(text) => onChange({ ...claim, text })} />
        </div>
        {(onMove || onRemove) && (
          <div className="flex shrink-0 gap-0.5 opacity-0 transition group-hover/claim:opacity-100 group-focus-within/claim:opacity-100">
            {onMove && <button className="px-1 text-faint hover:text-ink" onClick={() => onMove(-1)} aria-label="Move up">↑</button>}
            {onMove && <button className="px-1 text-faint hover:text-ink" onClick={() => onMove(1)} aria-label="Move down">↓</button>}
            {onRemove && <button className="px-1 text-faint hover:text-bad" onClick={onRemove} aria-label="Remove">✕</button>}
          </div>
        )}
      </div>
      <div className={cx('mt-0.5 flex flex-wrap items-center gap-1', !active && 'opacity-70')}>
        {claim.sources.map((s, i) => (
          <Cite key={s} id={s} n={i + 1} text={evidence[s]} onRemove={active ? () => onChange({ ...claim, sources: claim.sources.filter((x) => x !== s) }) : undefined} />
        ))}
        {active && (
          <select
            className="chip cursor-pointer border-dashed border-rule bg-transparent"
            value=""
            onChange={(e) => e.target.value && onChange({ ...claim, sources: [...claim.sources, e.target.value] })}
            aria-label="Add a source"
          >
            <option value="">+ cite</option>
            {options.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        )}
      </div>
      <Issues list={issues} />
    </div>
  )
}

function AddFromEvidence({ evidence, ids, onAdd, label }: { evidence: Record<string, string>; ids: string[]; onAdd: (id: string) => void; label: string }) {
  return (
    <select className="mt-2 block w-auto max-w-full cursor-pointer truncate rounded border border-dashed border-rule bg-transparent px-2 py-1 text-xs text-muted hover:border-rust hover:text-rust" value="" onChange={(e) => e.target.value && onAdd(e.target.value)} aria-label={label}>
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
  return <h3 className="rule-b mb-2 mt-6 pb-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-rust">{children}</h3>
}

export default function Review({ app, profile, setApp, go, memo, setMemo }: StepProps) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [focus, setFocus] = useState<string | null>(null)

  // Local edits live in Workspace (memo.review) so they survive switching steps.
  const draft: Tailored = memo.review?.draft ?? app.tailored!
  const dirty = !!memo.review

  const p = profile.profile
  const evidence = profile.evidence
  const report = app.report
  const issuesAt = (path: string) => (dirty ? [] : report?.errors.filter((e) => e.where === path) ?? [])

  const update = (fn: (d: Tailored) => void) =>
    setMemo((m) => {
      const next = clone(m.review?.draft ?? app.tailored!)
      fn(next)
      return { ...m, review: { draft: next, rev: (m.review?.rev ?? 0) + 1 } }
    })

  const focusedClaim = useMemo(() => (focus ? claimAt(draft, focus) : null), [focus, draft])

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

  const ctx: Ctx = { evidence, roleIds: p.roles.map((r) => r.id), focus, setFocus, issuesAt }

  const ats = app.ats
  const usedProjects = new Set(draft.projects.map((x) => x.id))

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      {/* ---------------------------------------------------------------- the sheet */}
      <article className="sheet animate-rise min-w-0 rounded px-5 py-7 text-[14.5px] text-body sm:px-10 sm:py-9">
        <p className="font-serif text-4xl font-semibold text-ink">{p.contact.name}</p>
        <select
          aria-label="Headline"
          className="-mx-1 mt-1 w-full min-w-0 max-w-full cursor-pointer rounded-sm border border-transparent bg-transparent px-1 font-semibold text-rust hover:border-rule"
          value={draft.headline}
          onChange={(e) => update((d) => { d.headline = e.target.value })}
        >
          {!p.headlines.some((h) => h.id === draft.headline) && <option value={draft.headline} disabled>Choose a headline…</option>}
          {p.headlines.map((h) => <option key={h.id} value={h.id}>{h.text} ({h.tracks.join(', ')})</option>)}
        </select>
        <Issues list={issuesAt('headline')} />
        <p className="mt-1 text-xs text-muted">
          {[p.contact.location, p.contact.phone, p.contact.email, ...p.contact.links.map((l) => l.text)].filter(Boolean).join(' · ')}
          <span className="ml-2 text-faint" title="Locked: comes from your profile">🔒</span>
        </p>

        {draft.summary && (
          <>
            <H>Summary</H>
            <ClaimEditor ctx={ctx} path="summary" claim={draft.summary} onChange={(c) => update((d) => { d.summary = c })} />
          </>
        )}

        <H>Career highlights</H>
        <div className="space-y-2">
          {draft.highlights.map((h, i) => (
            <div key={i} className="flex gap-2">
              <span className="pt-0.5 text-rust">•</span>
              <ClaimEditor ctx={ctx}
                className="flex-1"
                path={`highlights[${i}]`}
                claim={h}
                onChange={(c) => update((d) => { d.highlights[i] = c })}
                onRemove={() => update((d) => { d.highlights.splice(i, 1) })}
                onMove={(dir) => update((d) => { d.highlights = move(d.highlights, i, dir) })}
              />
            </div>
          ))}
        </div>
        <AddFromEvidence evidence={evidence} label="add highlight from evidence" ids={Object.keys(evidence)} onAdd={(id) => update((d) => { d.highlights.push({ text: evidence[id].split('\n')[0], sources: [id] }) })} />

        <H>Core competencies</H>
        <div className="space-y-2">
          {draft.competencies.map((g, i) => {
            const issues = g.items.flatMap((_, j) => issuesAt(`competencies[${i}].items[${j}]`))
            return (
              <div key={i} className={cx('group/claim flex gap-2 rounded-sm', issues.length > 0 && 'bg-bad-soft/60 ring-1 ring-bad/30')}>
                <span className="pt-0.5 text-rust">•</span>
                <div className="flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 sm:flex-nowrap">
                    <input aria-label={`Competency group ${i + 1}`} style={{ width: `${Math.max(g.label.length, 6) + 1}ch` }} className="shrink-0 rounded-sm border border-transparent bg-transparent font-semibold text-ink hover:border-rule focus:border-rust focus:outline-none" value={g.label} onChange={(e) => update((d) => { d.competencies[i].label = e.target.value })} />
                    <ItemsField ariaLabel={`Competency items ${i + 1}`} items={g.items} onCommit={(items) => update((d) => { d.competencies[i].items = items })} />
                    <div className="flex shrink-0 opacity-0 group-hover/claim:opacity-100">
                      <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.competencies = move(d.competencies, i, -1) })} aria-label="Move up">↑</button>
                      <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.competencies = move(d.competencies, i, 1) })} aria-label="Move down">↓</button>
                    </div>
                  </div>
                  <Issues list={[...issuesAt(`competencies[${i}].label`), ...issuesAt(`competencies[${i}]`), ...issues]} />
                </div>
              </div>
            )
          })}
        </div>
        <p className="mt-1 text-xs text-faint">Separate items with “·”. Every item must be a skill from your profile. Remove a group by clearing its items.</p>

        <H>Professional experience</H>
        {draft.experience.map((tr, i) => {
          const role = p.roles.find((r) => r.id === tr.role)
          if (!role) return <Issues key={i} list={[{ where: '', message: `unknown role ${tr.role}` }]} />
          const roleIds = Object.keys(evidence).filter((id) => id.startsWith(`${role.id}.a`) || id === `${role.id}.scope`)
          return (
            <div key={tr.role} className="mt-4">
              <div className="flex items-baseline justify-between gap-4">
                <p className="font-semibold text-ink">{role.employer}, {role.location} <span className="text-faint" title="Locked: employer, title and dates come from your profile">🔒</span></p>
                <p className="shrink-0 text-xs text-muted">{role.dates}</p>
              </div>
              <p className="font-semibold text-rust">{role.title}</p>
              {tr.scope && (
                <ClaimEditor ctx={ctx}
                  className={cx('mt-1', role.scope?.italic !== false && 'italic text-muted')}
                  path={`experience[${i}].scope`}
                  claim={tr.scope}
                  roleId={role.id}
                  onChange={(c) => update((d) => { d.experience[i].scope = c })}
                  onRemove={() => update((d) => { d.experience[i].scope = null })}
                />
              )}
              <div className="mt-1 space-y-1.5">
                {tr.bullets.map((b, j) => (
                  <div key={j} className="flex gap-2">
                    <span className="pt-0.5 text-rust">•</span>
                    <ClaimEditor ctx={ctx}
                      className="flex-1"
                      path={`experience[${i}].bullets[${j}]`}
                      claim={b}
                      roleId={role.id}
                      onChange={(c) => update((d) => { d.experience[i].bullets[j] = c })}
                      onRemove={() => update((d) => { d.experience[i].bullets.splice(j, 1) })}
                      onMove={(dir) => update((d) => { d.experience[i].bullets = move(d.experience[i].bullets, j, dir) })}
                    />
                  </div>
                ))}
                {tr.sub_roles.map((sr) => {
                  const item = role.sub_roles.find((s) => s.id === sr.id)
                  return (
                    <div key={sr.id} className="group/claim flex gap-2">
                      <span className="pt-0.5 text-rust">•</span>
                      <p className="flex-1"><span className="font-semibold text-ink">{item?.label}</span> {sr.text?.text ?? item?.text}</p>
                      <button className="px-1 text-faint opacity-0 hover:text-bad group-hover/claim:opacity-100" onClick={() => update((d) => { d.experience[i].sub_roles = d.experience[i].sub_roles.filter((x) => x.id !== sr.id) })} aria-label="Remove sub-role">✕</button>
                    </div>
                  )
                })}
              </div>
              <AddFromEvidence evidence={evidence} label="add bullet from this role’s evidence" ids={roleIds} onAdd={(id) => update((d) => { d.experience[i].bullets.push({ text: evidence[id].split('\n')[0], sources: [id] }) })} />
              <Issues list={issuesAt(`experience[${i}]`)} />
            </div>
          )
        })}

        <H>Projects & community leadership</H>
        <div className="space-y-1.5">
          {draft.projects.map((tp, i) => {
            const item = p.projects.find((x) => x.id === tp.id)
            return (
              <div key={tp.id} className="group/claim flex gap-2">
                <span className="pt-0.5 text-rust">•</span>
                <p className="flex-1"><span className="font-semibold text-ink">{item?.label}</span> {tp.text?.text ?? item?.text}</p>
                <div className="flex shrink-0 opacity-0 group-hover/claim:opacity-100">
                  <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.projects = move(d.projects, i, -1) })} aria-label="Move up">↑</button>
                  <button className="px-1 text-faint hover:text-ink" onClick={() => update((d) => { d.projects = move(d.projects, i, 1) })} aria-label="Move down">↓</button>
                  <button className="px-1 text-faint hover:text-bad" onClick={() => update((d) => { d.projects.splice(i, 1) })} aria-label="Remove">✕</button>
                </div>
              </div>
            )
          })}
        </div>
        {p.projects.some((x) => !usedProjects.has(x.id)) && (
          <AddFromEvidence evidence={evidence} label="add project" ids={p.projects.filter((x) => !usedProjects.has(x.id)).map((x) => x.id)} onAdd={(id) => update((d) => { d.projects.push({ id }) })} />
        )}

        {(['education', 'extras'] as const).map((key) => (
          <div key={key}>
            <H>{key === 'education' ? 'Education & certifications' : 'Awards & languages'}</H>
            <div className="space-y-1">
              {p[key].map((item) => {
                const on = draft[key].includes(item.id)
                return (
                  <label key={item.id} className={cx('flex cursor-pointer gap-2', !on && 'text-faint line-through')}>
                    <input type="checkbox" className="mt-1 accent-rust" checked={on} onChange={() => update((d) => { d[key] = on ? d[key].filter((x) => x !== item.id) : p[key].map((x) => x.id).filter((x) => x === item.id || d[key].includes(x)) })} />
                    <span><span className="font-semibold">{item.label}</span> {item.text}</span>
                  </label>
                )
              })}
            </div>
          </div>
        ))}
      </article>

      {/* ---------------------------------------------------------------- margin */}
      <aside className="space-y-5 lg:sticky lg:top-20 lg:self-start">
        <div className="sheet animate-rise rounded p-5" style={{ animationDelay: '80ms' }}>
          <div className="flex items-center justify-between">
            <p className="eyebrow">Fact-check</p>
            {dirty ? <span className="text-xs text-warn">unsaved edits</span> : report && <Stamp ok={report.ok}>{report.ok ? 'Verified' : `${report.errors.length} issue${report.errors.length > 1 ? 's' : ''}`}</Stamp>}
          </div>
          <p className="mt-3 text-sm text-muted">
            {dirty ? 'Save to re-run the fact-check.' : report?.ok ? 'Every claim traces to your profile.' : 'Fix the highlighted claims: cite the right evidence, reword to match it, or remove them.'}
          </p>
          {!dirty && report && report.errors.length > 0 && (
            <ul className="mt-3 max-h-56 space-y-1 overflow-auto border-t border-rule pt-3 text-xs text-bad">
              {report.errors.map((e, i) => <li key={i}><span className="font-mono text-[10px] text-faint">{e.where}</span> {e.message}</li>)}
            </ul>
          )}
          {!dirty && report && report.warnings.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-rule pt-3 text-xs text-warn">
              {report.warnings.map((w, i) => <li key={i}>{w.message}</li>)}
            </ul>
          )}
          <div className="mt-4 flex gap-2">
            <button className="btn btn-primary flex-1 justify-center" disabled={!dirty || saving} onClick={save}>
              {saving ? <><Spinner /> Checking…</> : 'Save & re-check'}
            </button>
            {dirty && <button className="btn" onClick={() => setMemo((m) => ({ ...m, review: null }))}>Discard</button>}
          </div>
          <button className="btn mt-2 w-full justify-center" disabled={dirty || !report?.ok} onClick={() => go('export')}>Continue to export →</button>
          {app.meta.repair_rounds ? <p className="mt-2 text-xs text-faint">The AI self-repaired {app.meta.repair_rounds} fact-check round{app.meta.repair_rounds > 1 ? 's' : ''}.</p> : null}
        </div>

        <ErrorNote error={error} onDismiss={() => setError(null)} />

        <div className="sheet animate-rise rounded p-5" style={{ animationDelay: '140ms' }}>
          <p className="eyebrow">Marginalia</p>
          {focusedClaim ? (
            <ol className="mt-3 space-y-3">
              {focusedClaim.sources.map((s, i) => (
                <li key={s} className="text-sm">
                  <p className="font-mono text-[11px] text-rust"><sup className="font-serif">{i + 1}</sup> {s}</p>
                  <p className="mt-0.5 font-serif leading-snug text-body">{evidence[s]?.split('\n')[0] ?? 'unknown id'}</p>
                </li>
              ))}
              {!focusedClaim.sources.length && <li className="text-sm text-bad">No sources: this claim can’t be verified.</li>}
            </ol>
          ) : (
            <p className="mt-2 text-sm text-muted">Click into any claim to see the evidence it cites, side by side.</p>
          )}
        </div>

        {ats && (
          <div className="sheet animate-rise rounded p-5" style={{ animationDelay: '200ms' }}>
            <p className="eyebrow">ATS keywords</p>
            {(['must', 'nice'] as const).map((k) => ats.coverage[k].total > 0 && (
              <div key={k} className="mt-3">
                <div className="flex justify-between text-xs text-muted">
                  <span>{k === 'must' ? 'Must-have' : 'Nice-to-have'}</span>
                  <span className="font-mono">{ats.coverage[k].hit}/{ats.coverage[k].total}</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-wash">
                  <div className="h-full rounded-full bg-rust transition-all" style={{ width: `${(100 * ats.coverage[k].hit) / ats.coverage[k].total}%` }} />
                </div>
              </div>
            ))}
            <div className="mt-4 flex flex-wrap gap-1.5">
              {ats.keywords.map((kw) => (
                <span
                  key={kw.term}
                  title={{ in_resume: 'In the resume', unused: 'You have evidence but it isn’t used. Consider surfacing it.', gap: 'No evidence in your profile' }[kw.status]}
                  className={cx('rounded-full px-2 py-0.5 text-xs', {
                    in_resume: 'bg-ok-soft text-ok',
                    unused: 'bg-warn-soft text-warn',
                    gap: 'bg-wash text-faint line-through',
                  }[kw.status])}
                >
                  {kw.term}
                </span>
              ))}
            </div>
            <p className="mt-3 font-mono text-[11px] text-faint">{ats.words} words · green used · amber available · struck = gap</p>
          </div>
        )}
      </aside>
    </div>
  )
}
