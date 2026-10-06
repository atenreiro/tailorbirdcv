import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Evidence, type LeadItem, type Profile as P, type Role, type Track } from '../api'
import { AnswersPanel, PreferencesPanel } from './Memory'
import { useKnowledge } from './useKnowledge'
import { HistoryPanel } from './History'
import { setUnsaved } from '../unsaved'
import { cx, useTitle } from '../lib'
import { ErrorNote, SaveDock, Spinner } from '../ui'

type Tab = 'experience' | 'summary' | 'skills' | 'headlines' | 'projects' | 'synonyms' | 'answers' | 'prefs' | 'history' | 'yaml'
const SECTIONS: [string, [Tab, string][]][] = [
  ['Resume facts', [['experience', 'Experience'], ['summary', 'Summary & highlights'], ['skills', 'Skills'], ['headlines', 'Headlines'], ['projects', 'Projects & more'], ['synonyms', 'Synonyms']]],
  ['Memory', [['answers', 'Answers & gaps'], ['prefs', 'Style preferences']]],
  ['File', [['history', 'History'], ['yaml', 'YAML']]],
]
const TABS = SECTIONS.flatMap(([, items]) => items.map(([k]) => k))
const SEARCHABLE: Tab[] = ['experience', 'summary']
const KNOWLEDGE_TABS: Tab[] = ['answers', 'prefs']
const TRACKS: Track[] = ['manager', 'ic', 'hybrid']

const card = 'rounded-[14px] border border-rule bg-sheet'
const label = 'font-mono text-[11px] uppercase tracking-[0.08em] text-muted'
const cardTitle = 'font-display text-[22px] text-ink'
// Soft grey input that turns white on focus.
const soft = 'w-full rounded-lg border border-line bg-wash outline-none transition-[border-color,background-color,box-shadow] focus:border-accent focus:bg-sheet focus:shadow-[0_0_0_3px_rgb(200_67_29/0.15)]'
// Looks like plain text until hovered or focused (fields that are rarely edited).
const quiet = 'rounded-lg border border-transparent bg-transparent outline-none transition-colors hover:border-rule focus:border-accent focus:bg-sheet'
const addBtn = 'h-8 cursor-pointer self-start rounded-lg px-2.5 font-medium text-accent hover:bg-[#fdf2ed]'

function Grow({ value, onChange, className, label, placeholder, autoFocus }: {
  value: string; onChange: (v: string) => void; className?: string; label: string; placeholder?: string; autoFocus?: boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => { el.style.height = '0px'; el.style.height = `${el.scrollHeight + 2}px` }
    fit()
    window.addEventListener('resize', fit)  // re-wrap when the window narrows or widens
    return () => window.removeEventListener('resize', fit)
  }, [value])
  return <textarea ref={ref} rows={1} aria-label={label} placeholder={placeholder} autoFocus={autoFocus}
    className={cx(soft, 'min-h-[38px] resize-none overflow-hidden px-3 py-2 text-sm leading-[1.45]', className)} value={value} onChange={(e) => onChange(e.target.value)} />
}

function nextId(prefix: string, taken: Set<string>) {
  let n = 1
  while (taken.has(`${prefix}${n}`)) n++
  return `${prefix}${n}`
}

function allIds(p: P) {
  const ids = new Set<string>()
  p.summary_facts.concat(p.highlights).forEach((e) => ids.add(e.id))
  p.roles.forEach((r) => { ids.add(r.id); if (r.scope) ids.add(r.scope.id); r.achievements.forEach((a) => ids.add(a.id)); r.sub_roles.forEach((s) => ids.add(s.id)) })
  p.projects.concat(p.education, p.extras).forEach((i) => ids.add(i.id))
  p.headlines.forEach((h) => ids.add(h.id))
  ;(p.retired_ids ?? []).forEach((id) => ids.add(id))  // deleted ids are never reused
  return ids
}

/** Textarea for list-like values, parsed only on blur so typing (new lines, commas) isn't fought. */
function RawListField({ parse, format, label }: { parse: (t: string) => void; format: () => string; label: string }) {
  const [text, setText] = useState<string | null>(null)
  return (
    <textarea className={cx(soft, 'min-h-[240px] resize-y px-3 py-2.5 font-mono text-[13px] leading-[1.6]')} aria-label={label}
      value={text ?? format()} onFocus={() => setText(format())} onChange={(e) => setText(e.target.value)}
      onBlur={() => { if (text !== null) parse(text); setText(null) }} />
  )
}

function EvidenceRow({ e, scope, idCol, onChange, onDelete, placeholder, autoFocus, hideId }: {
  e: Evidence; scope?: boolean; idCol: string; onChange: (e: Evidence) => void; onDelete: () => void
  placeholder?: string; autoFocus?: boolean; hideId?: boolean
}) {
  const source = e.source ?? 'resume'
  return (
    <div className={cx('grid items-start gap-3 border-b border-[#e9efeb] py-2 xl:gap-3.5', idCol)}>
      <div className="col-span-2 flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-[3px] sm:col-span-1 sm:flex-col sm:flex-nowrap sm:items-start sm:pt-2">
        <span className="break-all font-mono text-[11px] text-accent">{hideId ? (scope ? 'scope' : 'bullet') : e.id}</span>
        <span className={cx('font-mono text-[10px] uppercase tracking-[0.06em]', source === 'resume' ? 'text-faint' : 'text-[#7a4700]')}>
          {hideId ? 'new' : <>{scope && 'scope · '}{source}{e.in_base_resume === false && ' · not in base'}</>}
        </span>
      </div>
      <Grow label={e.id} value={e.text} className={scope ? 'italic' : undefined} placeholder={placeholder} autoFocus={autoFocus}
        onChange={(text) => onChange({ ...e, text })} />
      <button className="h-[38px] cursor-pointer text-faint hover:text-bad" onClick={onDelete} aria-label={`Delete ${e.id}`}
        title="Delete. Tailored resumes that cite it will fail the fact-check.">✕</button>
    </div>
  )
}

// wide enough for real ids like first-harbor-bank.scope on one line
// Phones: id on its own line above the text; wider screens: id column on the left.
const ROLE_ROW = 'grid-cols-[minmax(0,1fr)_24px] sm:grid-cols-[92px_minmax(0,1fr)_24px] xl:grid-cols-[150px_minmax(0,1fr)_28px]'
const SIDE_ROW = 'grid-cols-[minmax(0,1fr)_24px] sm:grid-cols-[92px_minmax(0,1fr)_24px] xl:grid-cols-[110px_minmax(0,1fr)_24px]'

const MAX_BULLETS = 10  // resume bullets a new role starts with: 1 to 10

function slug(text: string) {
  return text.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'role'
}

function blankRole(id: string): Role {
  const fresh = (eid: string): Evidence => ({ id: eid, text: '', source: 'interview', in_base_resume: false })
  return { id, employer: '', location: '', title: '', dates: '', scope: { ...fresh(`${id}.scope`), italic: true },
    achievements: [fresh(`${id}.a1`)], sub_roles: [] }
}

/** Roles added since the last save get their final ids from the company name (their evidence ids follow:
 *  `<id>.scope`, `<id>.a1`…), never an id in use or retired. Empty bullets and an empty scope are dropped.
 *  Returns what's missing instead when a new role is incomplete. */
function finalizeNewRoles(p: P, saved: P): { profile: P; problems: string[] } {
  const known = new Set(saved.roles.map((r) => r.id))
  const profile = structuredClone(p)
  const problems: string[] = []
  // Ids in the last saved profile count as taken too: one deleted in this edit is retired on save, never reused.
  const taken = new Set([...allIds(profile), ...allIds(saved)])
  profile.roles.forEach((r, i) => {
    if (known.has(r.id)) return
    for (const key of ['employer', 'location', 'title', 'dates'] as const) r[key] = r[key].trim()
    const name = r.employer || `New role ${i + 1}`
    const missing = (['employer', 'location', 'dates', 'title'] as const).filter((k) => !r[k])
      .map((k) => ({ employer: 'company name', location: 'location', dates: 'dates', title: 'title' })[k])
    r.achievements = r.achievements.map((a) => ({ ...a, text: a.text.trim() })).filter((a) => a.text)
    if (missing.length) problems.push(`${name}: add the ${missing.join(', ')}.`)
    if (r.achievements.length === 0) problems.push(`${name}: add at least one resume bullet.`)
    if (r.achievements.length > MAX_BULLETS) problems.push(`${name}: at most ${MAX_BULLETS} resume bullets.`)
    if (r.scope && !r.scope.text.trim()) delete r.scope
    // Replace the placeholder ids with ones derived from the company name.
    const own = [r.id, r.scope?.id, ...r.achievements.map((a) => a.id)]
    own.forEach((x) => x && taken.delete(x))
    let id = slug(r.employer || 'role'), n = 2
    while (taken.has(id) || [...taken].some((t) => t.startsWith(`${id}.`))) id = `${slug(r.employer || 'role')}-${n++}`
    r.id = id
    if (r.scope) r.scope = { ...r.scope, id: `${id}.scope`, text: r.scope.text.trim() }
    r.achievements = r.achievements.map((a, ai) => ({ ...a, id: `${id}.a${ai + 1}` }))
    ;[r.id, r.scope?.id, ...r.achievements.map((a) => a.id)].forEach((x) => x && taken.add(x))
  })
  return { profile, problems }
}

function initialTab(param: string | null): Tab {
  return TABS.includes(param as Tab) ? (param as Tab) : 'experience'
}

export default function Profile() {
  const [saved, setSaved] = useState<P | null>(null)
  const [p, setP] = useState<P | null>(null)
  const [params, setParams] = useSearchParams()
  const [tab, setTabState] = useState<Tab>(initialTab(params.get('tab')))
  const [query, setQuery] = useState('')
  const [yaml, setYaml] = useState('')
  const [savedYaml, setSavedYaml] = useState('')
  const [version, setVersion] = useState('')  // of the profile the form edits
  // Of the file the YAML editor was loaded from: a YAML save is checked against this, so text
  // loaded before an external change can never overwrite it (the save gets a 409 instead).
  const [yamlVersion, setYamlVersion] = useState('')
  const [historyCount, setHistoryCount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const kn = useKnowledge()
  useTitle(['Master profile'])

  const load = () =>
    api.profile().then((r) => { setSaved(r.profile); setP(structuredClone(r.profile)); setVersion(r.version); setConflict(false) })
      .catch((e) => setError(e.message))
  const countHistory = () => api.history('profile').then((h) => setHistoryCount(h.length)).catch(() => setHistoryCount(null))
  useEffect(() => { void load(); void countHistory() }, [])
  // Replaces the YAML editor's content (and any edits in it) with the file on disk.
  const loadYaml = () =>
    api.profileYaml().then((r) => { setYaml(r.yaml); setSavedYaml(r.yaml); setYamlVersion(r.version) }).catch((e) => setError(e.message))
  const yamlDirty = yaml !== savedYaml
  useEffect(() => {
    // Reload on entering the tab, unless there are YAML edits pending from an earlier visit.
    if (tab === 'yaml' && !yamlDirty) void loadYaml()
  }, [tab, yamlDirty])
  /** The latest profile from disk, for the form and the YAML editor alike (discarding edits in both). */
  const reloadAll = async () => {
    await load()
    if (tab === 'yaml' || yaml !== '') await loadYaml()
  }
  const profileDirty = !!p && JSON.stringify(p) !== JSON.stringify(saved)
  useEffect(() => { setUnsaved('profile', profileDirty || yamlDirty) }, [profileDirty, yamlDirty])
  useEffect(() => () => setUnsaved('profile', false), [])
  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 1800)
    return () => clearTimeout(t)
  }, [flash])

  if (!p) return error ? <ErrorNote error={error} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>

  const dirty = profileDirty || yamlDirty || kn.dirty
  const edit = (fn: (d: P) => void) => setP((prev) => { const next = structuredClone(prev!); fn(next); return next })
  const setTab = (t: Tab) => {
    setTabState(t); setQuery('')
    setParams(t === 'experience' ? {} : { tab: t }, { replace: true })
  }
  // YAML and form edits can't both be pending: saving one would overwrite the other.
  const blocked = (t: Tab) =>
    t !== tab && ((yamlDirty && t !== 'yaml' && !KNOWLEDGE_TABS.includes(t)) || (profileDirty && t === 'yaml'))

  async function save() {
    setBusy(true); setError(null)
    try {
      if (yamlDirty) {
        const r = await api.saveProfileYaml(yaml, yamlVersion)
        setYaml(r.yaml); setSavedYaml(r.yaml); setYamlVersion(r.version)
        await load()
      } else if (profileDirty) {
        const { profile, problems } = finalizeNewRoles(p!, saved!)
        if (problems.length) { setError(`Not saved yet. ${problems.join(' ')}`); return }
        const r = await api.saveProfile(profile, version)
        setSaved(r.profile); setP(structuredClone(r.profile)); setVersion(r.version)
      }
      if (kn.dirty && !(await kn.save())) return
      setFlash('Saved')
      void countHistory()
    } catch (e) {
      if ((e as { status?: number }).status === 409) setConflict(true)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const discard = () => { setP(structuredClone(saved!)); setYaml(savedYaml); kn.discard() }

  const q = query.trim().toLowerCase()
  const match = (e: { id: string; text: string; label?: string }) => !q || `${e.id} ${e.label ?? ''} ${e.text}`.toLowerCase().includes(q)
  const view: Tab = q && !SEARCHABLE.includes(tab) ? 'experience' : tab
  const ids = new Set([...allIds(p), ...allIds(saved!)])  // incl. ids deleted in this edit (retired on save)
  const k = kn.k
  const proposed = k?.preferences.filter((x) => x.status === 'proposed').length ?? 0
  const counts: Record<Tab, string | number> = {
    experience: p.roles.reduce((n, r) => n + (r.scope ? 1 : 0) + r.achievements.length, 0),
    summary: p.summary_facts.length + p.highlights.length,
    skills: p.skills.reduce((n, g) => n + g.items.length, 0),
    headlines: p.headlines.length,
    projects: p.projects.length + p.education.length + p.extras.length,
    synonyms: p.synonyms.length,
    answers: k?.answers.length ?? '',
    prefs: !k ? '' : proposed ? `${proposed} new` : k.preferences.filter((x) => x.status === 'active').length,
    history: historyCount ?? '',
    yaml: '',
  }
  const dockText = yamlDirty ? 'Unsaved YAML edits'
    : profileDirty && kn.dirty ? 'Unsaved profile, answer & preference changes'
    : profileDirty ? 'Unsaved profile changes' : 'Unsaved answers & preferences'

  const roles = p.roles.map((r, ri) => {
    const scope = r.scope && match(r.scope) ? r.scope : null
    const achievements = r.achievements.map((a, ai) => ({ a, ai })).filter(({ a }) => match(a))
    const subRoles = r.sub_roles.map((s, si) => ({ s, si })).filter(({ s }) => match(s))
    return { r, ri, scope, achievements, subRoles, count: (scope ? 1 : 0) + achievements.length }
  }).filter((x) => !q || x.count + x.subRoles.length > 0)
  const savedRoleIds = new Set(saved!.roles.map((r) => r.id))
  const addRole = () => edit((d) => { d.roles.unshift(blankRole(nextId('new-role-', ids))) })
  const moveRole = (ri: number, by: number) => edit((d) => { const [r] = d.roles.splice(ri, 1); d.roles.splice(ri + by, 0, r) })
  const deleteRole = (r: Role, ri: number) => {
    const n = (r.scope ? 1 : 0) + r.achievements.length + r.sub_roles.length
    if (savedRoleIds.has(r.id) && !window.confirm(`Delete ${r.employer || 'this role'} and its ${n} evidence item${n === 1 ? '' : 's'}? `
      + 'Their ids are retired, and tailored resumes that cite them will fail the fact-check until you edit them.')) return
    edit((d) => { d.roles.splice(ri, 1) })
  }
  const noMatches = !!q && (view === 'experience' ? roles.length === 0
    : !p.summary_facts.some(match) && !p.highlights.some(match))

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <div className="flex max-w-[760px] flex-col gap-2.5">
          <h1 className="font-display text-[48px] leading-[0.92] tracking-[-0.02em] text-ink sm:text-[64px]">Master profile</h1>
          <p className="text-base leading-[1.5] text-body text-pretty">
            Every tailored resume can only use what’s written here. Keep each entry exactly true. Evidence ids are what claims cite, so
            deleting one will break resumes that use it.
          </p>
        </div>
        <input type="search" className="field h-10 w-full text-sm disabled:opacity-50 sm:w-[280px]" placeholder="Find evidence by id or text" aria-label="Find evidence"
          value={query} disabled={yamlDirty} title={yamlDirty ? 'Save or discard your YAML edits first' : undefined}
          onChange={(e) => setQuery(e.target.value)} />
      </div>

      <div className="flex flex-col gap-6 md:flex-row md:items-start md:gap-8">
        <nav aria-label="Profile sections"
          className="-mx-4 flex gap-1 overflow-x-auto px-4 [scrollbar-width:none] md:sticky md:top-[84px] md:mx-0 md:w-[224px] md:flex-none md:flex-col md:gap-5 md:overflow-visible md:p-0">
          {SECTIONS.map(([title, items]) => (
            <div key={title} className="flex gap-1 md:flex-col md:gap-0.5">
              <p className="hidden px-3 pb-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-faint md:block">{title}</p>
              {items.map(([key, name]) => {
                const on = view === key
                const count = String(counts[key])
                return (
                  <button key={key} aria-current={on ? 'page' : undefined} disabled={blocked(key)} onClick={() => setTab(key)}
                    title={blocked(key) ? (yamlDirty ? 'Save or discard your YAML edits first' : 'Save or discard your edits first') : undefined}
                    className={cx('flex h-9 shrink-0 cursor-pointer items-center justify-between gap-2 whitespace-nowrap rounded-lg px-3 text-left transition-colors hover:bg-sheet disabled:cursor-not-allowed disabled:opacity-40',
                      on ? 'bg-sheet font-semibold text-ink shadow-[inset_3px_0_0_var(--color-accent),0_1px_2px_rgb(15_61_46/0.06)]' : 'text-body')}>
                    <span>{name}</span>
                    <span className={cx('font-mono text-[11px]', on ? 'text-accent' : count.includes('new') ? 'text-[#7a4700]' : 'text-faint')}>{count}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="flex min-w-0 flex-1 flex-col gap-[18px]">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
          <ErrorNote error={kn.error} onDismiss={() => kn.setError(null)} />
          {conflict && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn">
              Your profile changed elsewhere (another tab, or evidence approved during a tailoring).
              <button className="btn py-1" onClick={() => {
              if (!(profileDirty || yamlDirty) || window.confirm('Reload the latest profile and discard your unsaved profile and YAML edits here?')) void reloadAll().then(() => setError(null))
            }}>Reload latest</button>
            </div>
          )}
          {noMatches && (
            <div className={cx(card, 'px-5 py-12 text-center')}>
              <p className="font-display text-[28px] text-ink">Nothing here.</p>
              <p className="mt-1 text-muted">No evidence matches “{query.trim()}”.</p>
            </div>
          )}

          {view === 'experience' && !q && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted text-pretty">Roles print in this order, most recent first. Use ↑ ↓ to reorder.</p>
              <button className={cx(addBtn, 'hover:bg-sheet')} onClick={addRole}>+ Add role</button>
            </div>
          )}
          {view === 'experience' && roles.map(({ r, ri, scope, achievements, subRoles, count }, i) => {
            const isNew = !savedRoleIds.has(r.id)
            const ghost = isNew ? 'border-rule bg-wash placeholder:text-faint' : ''
            return (
            <section key={r.id} className={cx(card, 'animate-rise overflow-hidden', isNew && 'border-accent/50 shadow-[0_0_0_3px_rgb(200_67_29/0.08)]')} style={{ animationDelay: `${i * 50}ms` }}>
              <div className="flex flex-col gap-3 border-b border-line px-4 pb-[18px] pt-5 sm:px-6">
                {isNew && <p className={cx(label, 'text-accent')}>New role · company, location, dates, title, scope and 1–{MAX_BULLETS} resume bullets</p>}
                <div className="flex flex-wrap items-end gap-x-4 gap-y-2.5">
                  <input aria-label="Employer" placeholder="Company name" autoFocus={isNew && !r.employer}
                    className={cx(quiet, ghost, '-ml-2.5 h-11 min-w-0 flex-[1_1_260px] px-2.5 font-display text-[30px] tracking-[-0.01em] text-ink')}
                    value={r.employer} onChange={(e) => edit((d) => { d.roles[ri].employer = e.target.value })} />
                  <input aria-label="Location" placeholder="City, Country" className={cx(quiet, ghost, 'h-[34px] min-w-0 max-w-full flex-none px-2.5 text-sm text-muted focus:text-ink')}
                    style={{ width: `calc(${Math.max(isNew ? 14 : 8, r.location.length)}ch + 22px)` }}
                    value={r.location} onChange={(e) => edit((d) => { d.roles[ri].location = e.target.value })} />
                  <input aria-label="Dates" placeholder="Jan 2020 – Present" className={cx(quiet, ghost, 'h-[34px] min-w-0 max-w-full flex-none px-2.5 font-mono text-[13px] text-muted focus:text-ink')}
                    style={{ width: `calc(${Math.max(isNew ? 18 : 12, r.dates.length + 1)}ch + 22px)` }}
                    value={r.dates} onChange={(e) => edit((d) => { d.roles[ri].dates = e.target.value })} />
                  {!q && (
                    <div className="ml-auto flex items-center gap-0.5 self-center" role="group" aria-label={`Arrange ${r.employer || 'new role'}`}>
                      <button className="size-8 cursor-pointer rounded-md text-faint hover:bg-wash hover:text-ink disabled:cursor-not-allowed disabled:opacity-30"
                        disabled={ri === 0} onClick={() => moveRole(ri, -1)} aria-label="Move role up" title="Move up">↑</button>
                      <button className="size-8 cursor-pointer rounded-md text-faint hover:bg-wash hover:text-ink disabled:cursor-not-allowed disabled:opacity-30"
                        disabled={ri === p.roles.length - 1} onClick={() => moveRole(ri, 1)} aria-label="Move role down" title="Move down">↓</button>
                      <button className="size-8 cursor-pointer rounded-md text-faint hover:bg-wash hover:text-bad" onClick={() => deleteRole(r, ri)}
                        aria-label={`Delete ${r.employer || 'new role'}`} title={isNew ? 'Remove this new role' : 'Delete this role and its evidence'}>✕</button>
                    </div>
                  )}
                </div>
                <label className="flex flex-col gap-1.5">
                  <span className="text-xs text-muted">Title (locked on every resume, so it must match your real title)</span>
                  <input className={cx(soft, 'h-10 border-rule px-3 text-[15px] font-semibold text-accent placeholder:font-normal placeholder:text-faint')} placeholder="e.g. Senior Security Engineer"
                    value={r.title} onChange={(e) => edit((d) => { d.roles[ri].title = e.target.value })} />
                </label>
              </div>
              <div className="flex flex-col px-4 pb-[18px] pt-3.5 sm:px-6">
                <p className={cx(label, 'pb-1.5')}>{isNew ? `Scope and resume bullets · ${r.achievements.length} of ${MAX_BULLETS}` : `Evidence · ${count}`}</p>
                {scope && (
                  <EvidenceRow e={scope} scope idCol={ROLE_ROW} hideId={isNew}
                    placeholder="Scope: the team, budget, users or systems you were responsible for"
                    onChange={(e) => edit((d) => { d.roles[ri].scope = { ...d.roles[ri].scope!, ...e } })}
                    onDelete={() => edit((d) => { delete d.roles[ri].scope })} />
                )}
                {!r.scope && !q && (
                  <button className={cx(addBtn, 'mt-1')}
                    onClick={() => edit((d) => { d.roles[ri].scope = { id: `${r.id}.scope`, text: '', source: 'interview', in_base_resume: false, italic: true } })}
                    disabled={!isNew && ids.has(`${r.id}.scope`)}
                    title={!isNew && ids.has(`${r.id}.scope`) ? 'This role’s scope id was used before and is retired; add it as an achievement or in YAML instead' : undefined}>
                    + Add scope line
                  </button>
                )}
                {achievements.map(({ a, ai }) => (
                  <EvidenceRow key={a.id} e={a} idCol={ROLE_ROW} hideId={isNew}
                    placeholder={isNew ? 'A resume bullet: what you did and the result, exactly as it happened' : undefined}
                    onChange={(e) => edit((d) => { d.roles[ri].achievements[ai] = e })}
                    onDelete={() => edit((d) => { d.roles[ri].achievements.splice(ai, 1) })} />
                ))}
                {!q && (
                  <button className={cx(addBtn, 'mt-2.5 disabled:cursor-not-allowed disabled:opacity-40')}
                    disabled={isNew && r.achievements.length >= MAX_BULLETS}
                    title={isNew && r.achievements.length >= MAX_BULLETS ? `A new role starts with at most ${MAX_BULLETS} bullets` : undefined}
                    onClick={() => edit((d) => { d.roles[ri].achievements.push({ id: nextId(`${r.id}.a`, ids), text: '', source: 'interview', in_base_resume: false }) })}>
                    {isNew ? '+ Add bullet' : '+ Add achievement'}
                  </button>
                )}
              {subRoles.length > 0 && (
                <div className="flex flex-col gap-1">
                  <p className={cx(label, 'pb-1.5 pt-[18px]')}>Earlier roles here</p>
                  {subRoles.map(({ s, si }) => (
                    <div key={s.id} className="grid gap-3 py-1 md:grid-cols-[minmax(0,220px)_minmax(0,1fr)]">
                      <input className={cx(soft, 'h-[38px] px-3 text-sm font-semibold')} aria-label={`${s.id} label`} value={s.label} onChange={(e) => edit((d) => { d.roles[ri].sub_roles[si].label = e.target.value })} />
                      <Grow label={`${s.id} text`} value={s.text} onChange={(v) => edit((d) => { d.roles[ri].sub_roles[si].text = v })} />
                    </div>
                  ))}
                </div>
              )}
              </div>
            </section>
            )
          })}

          {view === 'summary' && !noMatches && (
            <div className="grid items-start gap-[18px] [grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr))]">
              {(['summary_facts', 'highlights'] as const).map((key) => (
                <section key={key} className={cx(card, 'flex flex-col px-[22px] py-[18px]')}>
                  <p className={cx(cardTitle, 'pb-2')}>{key === 'summary_facts' ? 'Summary & general facts' : 'Career highlights'}</p>
                  {p[key].map((e, i) => ({ e, i })).filter(({ e }) => match(e)).map(({ e, i }) => (
                    <EvidenceRow key={e.id} e={e} idCol={SIDE_ROW} onChange={(v) => edit((d) => { d[key][i] = v })} onDelete={() => edit((d) => { d[key].splice(i, 1) })} />
                  ))}
                  {!q && (
                    <button className={cx(addBtn, 'mt-2.5')}
                      onClick={() => edit((d) => { d[key].push({ id: nextId(key === 'summary_facts' ? 'summary.s' : 'highlight.h', ids), text: '', source: 'interview', in_base_resume: false }) })}>
                      + Add {key === 'summary_facts' ? 'fact' : 'highlight'}
                    </button>
                  )}
                </section>
              ))}
            </div>
          )}

          {view === 'skills' && (
            <>
              <p className="text-sm text-muted text-pretty">Only skills you’ve used hands-on. Tailored competencies may reorder these, use approved synonyms or a sub-phrase, but never add new ones.</p>
              {p.skills.map((g, gi) => (
                <section key={gi} className={cx(card, 'grid items-start gap-x-5 gap-y-3 px-5 py-4 md:grid-cols-[220px_minmax(0,1fr)]')}>
                  <input className={cx(quiet, '-ml-2.5 h-9 px-2.5 font-display text-xl text-ink')} aria-label="Category" value={g.category} onChange={(e) => edit((d) => { d.skills[gi].category = e.target.value })} />
                  <div className="flex min-w-0 flex-col gap-2.5">
                    <div className="flex flex-wrap gap-1.5">
                      {g.items.map((item, ii) => (
                        <span key={ii} className="inline-flex h-7 items-center gap-2 rounded-md bg-[#e3eae6] pl-2.5 pr-1.5 font-mono text-xs text-ink">
                          {item}
                          <button onClick={() => edit((d) => { d.skills[gi].items.splice(ii, 1) })} aria-label={`Remove ${item}`} className="size-[18px] cursor-pointer rounded text-faint hover:bg-sheet hover:text-bad">×</button>
                        </span>
                      ))}
                    </div>
                    <input className={cx(soft, 'h-9 px-3 text-[13px]')} placeholder="Add a skill and press Enter" aria-label={`Add a skill to ${g.category}`}
                      onKeyDown={(e) => {
                        const v = e.currentTarget.value.trim()
                        if (e.key === 'Enter' && v) { edit((d) => { d.skills[gi].items.push(v) }); e.currentTarget.value = '' }
                      }} />
                  </div>
                </section>
              ))}
              <button className={cx(addBtn, 'hover:bg-sheet')} onClick={() => edit((d) => { d.skills.push({ category: 'New group', items: [] }) })}>+ Add skill group</button>
            </>
          )}

          {view === 'headlines' && (
            <>
              <p className="text-sm text-muted">The AI picks a headline from this approved list, based on the role’s track.</p>
              {p.headlines.map((h, hi) => (
                <section key={h.id} className={cx(card, 'flex flex-wrap items-center gap-x-4 gap-y-3 px-[18px] py-3.5')}>
                  <input className={cx(soft, 'h-10 min-w-0 flex-[1_1_360px] px-3 text-[15px] font-semibold text-accent')} aria-label={`Headline ${h.id}`} value={h.text} onChange={(e) => edit((d) => { d.headlines[hi].text = e.target.value })} />
                  <div className="inline-flex gap-0.5 rounded-lg bg-paper p-[3px]" role="group" aria-label="Tracks">
                    {TRACKS.map((t) => {
                      const on = h.tracks.includes(t)
                      return (
                        <button key={t} aria-pressed={on}
                          className={cx('h-[30px] cursor-pointer rounded-md px-3 text-[13px] font-medium transition-colors', on ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(15_61_46/0.12)]' : 'text-muted hover:text-ink')}
                          onClick={() => edit((d) => { const tr = d.headlines[hi].tracks; d.headlines[hi].tracks = on ? tr.filter((x) => x !== t) : [...tr, t] })}>
                          {t}
                        </button>
                      )
                    })}
                  </div>
                  <button className="h-9 w-7 cursor-pointer text-faint hover:text-bad disabled:cursor-not-allowed disabled:opacity-30" disabled={p.headlines.length < 2}
                    onClick={() => edit((d) => { d.headlines.splice(hi, 1) })} aria-label={`Delete headline ${h.id}`}>✕</button>
                </section>
              ))}
              <button className={cx(addBtn, 'hover:bg-sheet')} onClick={() => edit((d) => { d.headlines.push({ id: nextId('h.custom', ids), text: '', tracks: ['ic'] }) })}>+ Add headline</button>
            </>
          )}

          {view === 'projects' && (['projects', 'education', 'extras'] as const).map((key) => (
            <section key={key} className={cx(card, 'flex flex-col gap-1 px-[22px] py-[18px]')}>
              <p className={cx(cardTitle, 'pb-1.5')}>{{ projects: 'Projects & community', education: 'Education & certifications', extras: 'Awards & languages' }[key]}</p>
              {p[key].map((item: LeadItem, i) => (
                <div key={item.id} className="grid items-start gap-x-3 gap-y-1 py-[3px] md:grid-cols-[100px_minmax(0,220px)_minmax(0,1fr)]">
                  <span className="break-all pt-2.5 font-mono text-[11px] text-accent">{item.id}</span>
                  <input className={cx(quiet, 'h-9 px-2.5 text-sm font-semibold text-ink')} aria-label={`${item.id} label`} value={item.label} onChange={(e) => edit((d) => { d[key][i].label = e.target.value })} />
                  <Grow label={`${item.id} text`} className={cx(quiet, 'min-h-9 px-2.5 py-[7px]')} value={item.text} onChange={(v) => edit((d) => { d[key][i].text = v })} />
                </div>
              ))}
            </section>
          ))}

          {view === 'synonyms' && (
            <div className="grid gap-[18px] [grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr))]">
              <section className={cx(card, 'flex flex-col gap-2 px-[22px] py-[18px]')}>
                <p className={cardTitle}>Synonym groups</p>
                <p className="text-[13px] text-muted">Interchangeable terms, one group per line, comma-separated. Example: <span className="font-mono text-xs">CRM, Customer Relationship Management</span></p>
                <RawListField label="Synonym groups" format={() => p.synonyms.map((g) => g.join(', ')).join('\n')}
                  parse={(t) => edit((d) => { d.synonyms = t.split('\n').map((l) => l.split(',').map((x) => x.trim()).filter(Boolean)).filter((g) => g.length) })} />
              </section>
              <section className={cx(card, 'flex flex-col gap-2 px-[22px] py-[18px]')}>
                <p className={cardTitle}>Approved vocabulary</p>
                <p className="text-[13px] text-muted">Proper nouns allowed in any claim (e.g. a city or region you work in), one per line. Keep this short.</p>
                <RawListField label="Vocabulary" format={() => p.vocabulary.join('\n')}
                  parse={(t) => edit((d) => { d.vocabulary = t.split('\n').map((x) => x.trim()).filter(Boolean) })} />
              </section>
            </div>
          )}

          {KNOWLEDGE_TABS.includes(view) && !k && (
            kn.error ? null : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>
          )}
          {view === 'answers' && k && <AnswersPanel k={k} setK={kn.setK} />}
          {view === 'prefs' && k && <PreferencesPanel k={k} setK={kn.setK} />}
          {view === 'history' && (
            <HistoryPanel hasUnsaved={dirty}
              onRestored={(kind) => { if (kind === 'profile') { void reloadAll(); void countHistory() } else void kn.load() }} />
          )}

          {view === 'yaml' && (
            <>
              <p className="text-sm text-muted">The raw file (<span className="font-mono text-xs">profile.yaml</span> in your data folder; Settings → System check shows where). It’s validated on save, and duplicate ids or a bad structure are rejected.</p>
              <textarea className="min-h-[640px] resize-y rounded-[14px] border border-ink bg-ink px-5 py-[18px] font-mono text-[13px] leading-[1.65] text-[#f6dacf] outline-none focus:shadow-[0_0_0_3px_rgb(77_107_255/0.45)]" aria-label="Profile YAML" spellCheck={false} value={yaml} onChange={(e) => setYaml(e.target.value)} />
            </>
          )}
        </div>
      </div>

      <SaveDock dirty={dirty} text={dockText} busy={busy} flash={flash} onSave={save} onDiscard={discard}
        saveLabel={(profileDirty || yamlDirty) && kn.dirty ? 'Save all' : profileDirty || yamlDirty ? 'Save profile' : 'Save changes'} />
    </div>
  )
}
