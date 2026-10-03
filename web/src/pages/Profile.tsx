import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Evidence, type LeadItem, type Profile as P, type Track } from '../api'
import { AnswersPanel, PreferencesPanel, useKnowledge } from './Memory'
import { HistoryPanel } from './History'
import { setUnsaved } from '../unsaved'
import { cx, ErrorNote, SaveDock, Spinner } from '../ui'

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

const card = 'rounded-lg border border-rule bg-sheet'
const label = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-accent'
// Looks like plain text until hovered or focused (fields that are rarely edited).
const quiet = 'field border-transparent bg-transparent hover:border-rule focus:border-accent'

function Grow({ value, onChange, className, label }: { value: string; onChange: (v: string) => void; className?: string; label: string }) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => { el.style.height = '0px'; el.style.height = `${el.scrollHeight + 2}px` }
    fit()
    window.addEventListener('resize', fit)  // re-wrap when the window narrows or widens
    return () => window.removeEventListener('resize', fit)
  }, [value])
  return <textarea ref={ref} rows={1} aria-label={label} className={cx('field resize-none overflow-hidden py-[7px] text-sm leading-[1.45]', className)} value={value} onChange={(e) => onChange(e.target.value)} />
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
    <textarea className="field min-h-[220px] resize-y font-mono text-[13px] leading-[1.6]" aria-label={label}
      value={text ?? format()} onFocus={() => setText(format())} onChange={(e) => setText(e.target.value)}
      onBlur={() => { if (text !== null) parse(text); setText(null) }} />
  )
}

function EvidenceRow({ e, scope, idCol, onChange, onDelete }: {
  e: Evidence; scope?: boolean; idCol: string; onChange: (e: Evidence) => void; onDelete: () => void
}) {
  const source = e.source ?? 'resume'
  return (
    <div className={cx('grid items-start gap-3 border-b border-rule/60 py-2', idCol)}>
      <div className="flex min-w-0 flex-col gap-0.5 pt-1.5">
        <span className="break-all font-mono text-[11px] text-accent">{e.id}</span>
        <span className={cx('text-[10px] uppercase tracking-[0.06em]', source === 'resume' ? 'text-faint' : 'text-warn')}>
          {scope && 'scope · '}{source}{e.in_base_resume === false && ' · not in base'}
        </span>
      </div>
      <Grow label={e.id} value={e.text} className={scope ? 'italic' : undefined} onChange={(text) => onChange({ ...e, text })} />
      <button className="cursor-pointer pt-2 text-faint hover:text-bad" onClick={onDelete} aria-label={`Delete ${e.id}`}
        title="Delete. Tailored resumes that cite it will fail the fact-check.">✕</button>
    </div>
  )
}

// wide enough for real ids like first-harbor-bank.scope on one line
const ROLE_ROW = 'grid-cols-[92px_minmax(0,1fr)_24px] xl:grid-cols-[150px_minmax(0,1fr)_28px]'
const SIDE_ROW = 'grid-cols-[92px_minmax(0,1fr)_24px] xl:grid-cols-[110px_minmax(0,1fr)_24px]'

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
  const [version, setVersion] = useState('')
  const [historyCount, setHistoryCount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const kn = useKnowledge()

  const load = () =>
    api.profile().then((r) => { setSaved(r.profile); setP(structuredClone(r.profile)); setVersion(r.version); setConflict(false) })
      .catch((e) => setError(e.message))
  const countHistory = () => api.history('profile').then((h) => setHistoryCount(h.length)).catch(() => setHistoryCount(null))
  useEffect(() => { void load(); void countHistory() }, [])
  const yamlDirty = yaml !== savedYaml
  useEffect(() => {
    // Reload on entering the tab, unless there are YAML edits pending from an earlier visit.
    if (tab === 'yaml' && !yamlDirty) api.profileYaml().then((r) => { setYaml(r.yaml); setSavedYaml(r.yaml); setVersion(r.version) }).catch((e) => setError(e.message))
  }, [tab])
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
        const r = await api.saveProfileYaml(yaml, version)
        setYaml(r.yaml); setSavedYaml(r.yaml)
        await load()
      } else if (profileDirty) {
        const r = await api.saveProfile(p!, version)
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
  const ids = allIds(p)
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
  const noMatches = !!q && (view === 'experience' ? roles.length === 0
    : !p.summary_facts.some(match) && !p.highlights.some(match))

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-5">
        <div className="flex max-w-[720px] flex-col gap-1.5">
          <p className={label}>Master profile</p>
          <h1 className="font-display text-[44px] leading-[0.95] sm:text-[56px] text-ink">The source of truth.</h1>
          <p className="text-muted text-pretty">
            Every tailored resume can only use what’s written here. Keep each entry exactly true. Evidence ids are what claims cite, so
            deleting one will break resumes that use it.
          </p>
        </div>
        <input type="search" className="field w-full text-sm sm:w-[260px]" placeholder="Find evidence by id or text" aria-label="Find evidence"
          value={query} disabled={yamlDirty} title={yamlDirty ? 'Save or discard your YAML edits first' : undefined}
          onChange={(e) => setQuery(e.target.value)} />
      </div>

      <div className="flex flex-col gap-6 md:flex-row md:items-start md:gap-8">
        <nav aria-label="Profile sections"
          className="-mx-4 flex gap-1 overflow-x-auto px-4 [scrollbar-width:none] md:sticky md:top-[84px] md:mx-0 md:w-[200px] md:flex-none md:flex-col md:gap-[18px] md:overflow-visible md:p-0">
          {SECTIONS.map(([title, items]) => (
            <div key={title} className="flex gap-1 md:flex-col md:gap-0.5">
              <p className="hidden px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint md:block">{title}</p>
              {items.map(([key, name]) => {
                const on = view === key
                const count = String(counts[key])
                return (
                  <button key={key} aria-current={on ? 'page' : undefined} disabled={blocked(key)} onClick={() => setTab(key)}
                    title={blocked(key) ? (yamlDirty ? 'Save or discard your YAML edits first' : 'Save or discard your edits first') : undefined}
                    className={cx('flex shrink-0 cursor-pointer items-baseline justify-between gap-2 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-wash disabled:cursor-not-allowed disabled:opacity-40',
                      on ? 'bg-wash text-ink' : 'text-muted')}>
                    <span>{name}</span>
                    <span className={cx('font-mono text-[11px]', on ? 'text-accent' : count.includes('new') ? 'text-warn' : 'text-faint')}>{count}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
          <ErrorNote error={kn.error} onDismiss={() => kn.setError(null)} />
          {conflict && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn">
              Your profile changed elsewhere (another tab, or evidence approved during a tailoring).
              <button className="btn py-1" onClick={() => { if (!dirty || window.confirm('Reload and discard your unsaved edits here?')) void load() }}>Reload latest</button>
            </div>
          )}
          {noMatches && (
            <div className={cx(card, 'px-5 py-12 text-center')}>
              <p className="font-display text-[22px] text-ink">Nothing here.</p>
              <p className="mt-1 text-muted">No evidence matches “{query.trim()}”.</p>
            </div>
          )}

          {view === 'experience' && roles.map(({ r, ri, scope, achievements, subRoles, count }, i) => (
            <section key={r.id} className="sheet animate-rise flex flex-col gap-3.5 rounded-lg px-4 py-5 sm:px-6" style={{ animationDelay: `${i * 50}ms` }}>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_180px]">
                {([['employer', 'Employer'], ['location', 'Location'], ['dates', 'Dates']] as const).map(([key, name]) => (
                  <label key={key} className="flex flex-col gap-1 text-xs text-muted">{name}
                    <input className="field py-[7px] text-sm text-ink" value={r[key]} onChange={(e) => edit((d) => { d.roles[ri][key] = e.target.value })} />
                  </label>
                ))}
              </div>
              <label className="flex flex-col gap-1 text-xs text-muted">Title (locked on every resume, so it must match your real title)
                <input className="field py-[7px] text-sm font-semibold text-accent" value={r.title} onChange={(e) => edit((d) => { d.roles[ri].title = e.target.value })} />
              </label>
              <div className="flex flex-col">
                <p className={cx(label, 'pb-1')}>Evidence · {count}</p>
                {scope && (
                  <EvidenceRow e={scope} scope idCol={ROLE_ROW}
                    onChange={(e) => edit((d) => { d.roles[ri].scope = { ...d.roles[ri].scope!, ...e } })}
                    onDelete={() => edit((d) => { delete d.roles[ri].scope })} />
                )}
                {achievements.map(({ a, ai }) => (
                  <EvidenceRow key={a.id} e={a} idCol={ROLE_ROW}
                    onChange={(e) => edit((d) => { d.roles[ri].achievements[ai] = e })}
                    onDelete={() => edit((d) => { d.roles[ri].achievements.splice(ai, 1) })} />
                ))}
                {!q && (
                  <button className="btn btn-ghost mt-2 self-start px-2 py-1.5 text-[13px] text-accent"
                    onClick={() => edit((d) => { d.roles[ri].achievements.push({ id: nextId(`${r.id}.a`, ids), text: '', source: 'interview', in_base_resume: false }) })}>
                    + Add achievement
                  </button>
                )}
              </div>
              {subRoles.length > 0 && (
                <div className="flex flex-col gap-1">
                  <p className={cx(label, 'pb-1')}>Earlier roles here</p>
                  {subRoles.map(({ s, si }) => (
                    <div key={s.id} className="grid gap-3 py-1 md:grid-cols-[220px_minmax(0,1fr)]">
                      <input className="field py-[7px] text-sm font-semibold" aria-label={`${s.id} label`} value={s.label} onChange={(e) => edit((d) => { d.roles[ri].sub_roles[si].label = e.target.value })} />
                      <Grow label={`${s.id} text`} value={s.text} onChange={(v) => edit((d) => { d.roles[ri].sub_roles[si].text = v })} />
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}

          {view === 'summary' && !noMatches && (
            <div className="grid gap-5 [grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))]">
              {(['summary_facts', 'highlights'] as const).map((key) => (
                <section key={key} className={cx(card, 'flex flex-col px-5 py-[18px]')}>
                  <p className={cx(label, 'pb-1.5')}>{key === 'summary_facts' ? 'Summary & general facts' : 'Career highlights'}</p>
                  {p[key].map((e, i) => ({ e, i })).filter(({ e }) => match(e)).map(({ e, i }) => (
                    <EvidenceRow key={e.id} e={e} idCol={SIDE_ROW} onChange={(v) => edit((d) => { d[key][i] = v })} onDelete={() => edit((d) => { d[key].splice(i, 1) })} />
                  ))}
                  {!q && (
                    <button className="btn btn-ghost mt-2 self-start px-2 py-1.5 text-[13px] text-accent"
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
              <p className="text-[13px] text-muted">Only skills you’ve used hands-on. Tailored competencies may reorder these, use approved synonyms or a sub-phrase, but never add new ones.</p>
              {p.skills.map((g, gi) => (
                <section key={gi} className={cx(card, 'grid items-start gap-4 px-[18px] py-4 md:grid-cols-[200px_minmax(0,1fr)]')}>
                  <input className={cx(quiet, '-mx-2.5 px-2.5 py-1 font-semibold text-ink')} aria-label="Category" value={g.category} onChange={(e) => edit((d) => { d.skills[gi].category = e.target.value })} />
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap gap-1.5">
                      {g.items.map((item, ii) => (
                        <span key={ii} className="inline-flex items-center gap-1.5 rounded-[3px] bg-wash px-2 py-0.5 font-mono text-xs text-body">
                          {item}
                          <button onClick={() => edit((d) => { d.skills[gi].items.splice(ii, 1) })} aria-label={`Remove ${item}`} className="cursor-pointer text-faint hover:text-bad">×</button>
                        </span>
                      ))}
                    </div>
                    <input className="field py-1.5 text-[13px]" placeholder="Add a skill and press Enter" aria-label={`Add a skill to ${g.category}`}
                      onKeyDown={(e) => {
                        const v = e.currentTarget.value.trim()
                        if (e.key === 'Enter' && v) { edit((d) => { d.skills[gi].items.push(v) }); e.currentTarget.value = '' }
                      }} />
                  </div>
                </section>
              ))}
              <button className="btn btn-ghost self-start px-2 py-1.5 text-[13px] text-accent" onClick={() => edit((d) => { d.skills.push({ category: 'New group', items: [] }) })}>+ Add skill group</button>
            </>
          )}

          {view === 'headlines' && (
            <>
              <p className="text-[13px] text-muted">The AI picks a headline from this approved list, based on the role’s track.</p>
              {p.headlines.map((h, hi) => (
                <section key={h.id} className={cx(card, 'grid items-center gap-3 px-[18px] py-3.5 md:grid-cols-[minmax(0,1fr)_auto_auto] md:gap-4')}>
                  <input className="field py-[7px] text-sm font-semibold text-accent" aria-label={`Headline ${h.id}`} value={h.text} onChange={(e) => edit((d) => { d.headlines[hi].text = e.target.value })} />
                  <div className="flex gap-1.5" role="group" aria-label="Tracks">
                    {TRACKS.map((t) => {
                      const on = h.tracks.includes(t)
                      return (
                        <button key={t} aria-pressed={on}
                          className={cx('cursor-pointer rounded-full border px-2.5 py-[3px] text-xs transition-colors', on ? 'border-accent/40 bg-accent-soft text-accent' : 'border-rule bg-sheet text-muted hover:text-ink')}
                          onClick={() => edit((d) => { const tr = d.headlines[hi].tracks; d.headlines[hi].tracks = on ? tr.filter((x) => x !== t) : [...tr, t] })}>
                          {t}
                        </button>
                      )
                    })}
                  </div>
                  <button className="cursor-pointer justify-self-start text-faint hover:text-bad disabled:cursor-not-allowed disabled:opacity-30" disabled={p.headlines.length < 2}
                    onClick={() => edit((d) => { d.headlines.splice(hi, 1) })} aria-label={`Delete headline ${h.id}`}>✕</button>
                </section>
              ))}
              <button className="btn btn-ghost self-start px-2 py-1.5 text-[13px] text-accent" onClick={() => edit((d) => { d.headlines.push({ id: nextId('h.custom', ids), text: '', tracks: ['ic'] }) })}>+ Add headline</button>
            </>
          )}

          {view === 'projects' && (['projects', 'education', 'extras'] as const).map((key) => (
            <section key={key} className={cx(card, 'flex flex-col gap-1.5 px-5 py-[18px]')}>
              <p className={label}>{{ projects: 'Projects & community', education: 'Education & certifications', extras: 'Awards & languages' }[key]}</p>
              {p[key].map((item: LeadItem, i) => (
                <div key={item.id} className="grid items-start gap-x-3 gap-y-1 py-1 md:grid-cols-[100px_220px_minmax(0,1fr)]">
                  <span className="pt-2 font-mono text-[11px] text-accent">{item.id}</span>
                  <input className={cx(quiet, 'py-1.5 text-sm font-semibold text-ink')} aria-label={`${item.id} label`} value={item.label} onChange={(e) => edit((d) => { d[key][i].label = e.target.value })} />
                  <Grow label={`${item.id} text`} className={cx(quiet, 'py-1.5')} value={item.text} onChange={(v) => edit((d) => { d[key][i].text = v })} />
                </div>
              ))}
            </section>
          ))}

          {view === 'synonyms' && (
            <div className="grid gap-5 [grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))]">
              <section className={cx(card, 'flex flex-col gap-2 px-5 py-[18px]')}>
                <p className={label}>Synonym groups</p>
                <p className="text-[13px] text-muted">Interchangeable terms, one group per line, comma-separated. Example: <span className="font-mono text-xs">WAF, Web Application Firewall</span></p>
                <RawListField label="Synonym groups" format={() => p.synonyms.map((g) => g.join(', ')).join('\n')}
                  parse={(t) => edit((d) => { d.synonyms = t.split('\n').map((l) => l.split(',').map((x) => x.trim()).filter(Boolean)).filter((g) => g.length) })} />
              </section>
              <section className={cx(card, 'flex flex-col gap-2 px-5 py-[18px]')}>
                <p className={label}>Approved vocabulary</p>
                <p className="text-[13px] text-muted">Proper nouns allowed in any claim (e.g. Singapore, APAC), one per line. Keep this short.</p>
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
              onRestored={(kind) => { if (kind === 'profile') { void load(); void countHistory() } else void kn.load() }} />
          )}

          {view === 'yaml' && (
            <>
              <p className="text-[13px] text-muted">The raw file (<span className="font-mono text-xs">private/profile.yaml</span>). It’s validated on save, and duplicate ids or a bad structure are rejected.</p>
              <textarea className="field min-h-[640px] resize-y px-4 py-3.5 font-mono text-[13px] leading-[1.6]" aria-label="Profile YAML" spellCheck={false} value={yaml} onChange={(e) => setYaml(e.target.value)} />
            </>
          )}
        </div>
      </div>

      <SaveDock dirty={dirty} text={dockText} busy={busy} flash={flash} onSave={save} onDiscard={discard}
        saveLabel={(profileDirty || yamlDirty) && kn.dirty ? 'Save all' : profileDirty || yamlDirty ? 'Save profile' : 'Save changes'} />
    </div>
  )
}
