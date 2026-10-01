import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Evidence, type Profile as P, type Track } from '../api'
import { AnswersPanel, PreferencesPanel } from './Memory'
import { HistoryPanel } from './History'
import { setUnsaved } from '../unsaved'
import { cx, ErrorNote, Spinner } from '../ui'

const TABS = ['Experience', 'Skills', 'Headlines', 'Summary & highlights', 'Projects & more', 'Synonyms', 'Answers & gaps', 'Style preferences', 'History', 'YAML'] as const
type Tab = (typeof TABS)[number]
const TRACKS: Track[] = ['manager', 'ic', 'hybrid']

function Grow({ value, onChange, className, label }: { value: string; onChange: (v: string) => void; className?: string; label: string }) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (el) { el.style.height = '0px'; el.style.height = `${el.scrollHeight + 2}px` }
  }, [value])
  return <textarea ref={ref} rows={1} aria-label={label} className={cx('field resize-none overflow-hidden leading-relaxed', className)} value={value} onChange={(e) => onChange(e.target.value)} />
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
function RawListField({ value, parse, format, label }: { value: string[] | string[][]; parse: (t: string) => void; format: () => string; label: string }) {
  const [text, setText] = useState<string | null>(null)
  void value
  return (
    <textarea className="field min-h-[220px] font-mono text-sm" aria-label={label}
      value={text ?? format()} onFocus={() => setText(format())} onChange={(e) => setText(e.target.value)}
      onBlur={() => { if (text !== null) parse(text); setText(null) }} />
  )
}

function EvidenceRow({ e, onChange, onDelete }: { e: Evidence; onChange: (e: Evidence) => void; onDelete: () => void }) {
  return (
    <div className="group grid grid-cols-[110px_1fr_auto] items-start gap-3 py-2">
      <div className="pt-2">
        <p className="font-mono text-[11px] text-rust">{e.id}</p>
        <p className="mt-0.5 text-[10px] uppercase tracking-wider text-faint">
          {e.source ?? 'resume'}{e.in_base_resume === false && ' · not in base'}
        </p>
      </div>
      <Grow label={e.id} value={e.text} onChange={(text) => onChange({ ...e, text })} />
      <button className="pt-2 text-faint opacity-0 hover:text-bad group-hover:opacity-100" onClick={onDelete} aria-label={`Delete ${e.id}`} title="Delete. Tailored resumes that cite it will fail the fact-check.">✕</button>
    </div>
  )
}

export default function Profile() {
  const [saved, setSaved] = useState<P | null>(null)
  const [p, setP] = useState<P | null>(null)
  const [params] = useSearchParams()
  const [tab, setTab] = useState<Tab>(params.get('tab') === 'prefs' ? 'Style preferences' : params.get('tab') === 'answers' ? 'Answers & gaps' : params.get('tab') === 'history' ? 'History' : 'Experience')
  const [yaml, setYaml] = useState('')
  const [savedYaml, setSavedYaml] = useState('')
  const [version, setVersion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)

  const load = () =>
    api.profile().then((r) => { setSaved(r.profile); setP(structuredClone(r.profile)); setVersion(r.version); setConflict(false) })
      .catch((e) => setError(e.message))
  useEffect(() => { void load() }, [])
  useEffect(() => {
    if (tab === 'YAML') api.profileYaml().then((r) => { setYaml(r.yaml); setSavedYaml(r.yaml); setVersion(r.version) }).catch((e) => setError(e.message))
  }, [tab])
  const profileDirty = !!p && JSON.stringify(p) !== JSON.stringify(saved)
  const yamlDirty = tab === 'YAML' && yaml !== savedYaml
  useEffect(() => { setUnsaved('profile', profileDirty || yamlDirty) }, [profileDirty, yamlDirty])
  useEffect(() => () => setUnsaved('profile', false), [])

  if (!p) return error ? <ErrorNote error={error} /> : <p className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>

  const dirty = profileDirty || yamlDirty
  const edit = (fn: (d: P) => void) => setP((prev) => { const next = structuredClone(prev!); fn(next); return next })

  async function save() {
    setBusy(true); setError(null)
    try {
      if (tab === 'YAML') {
        const r = await api.saveProfileYaml(yaml, version)
        setYaml(r.yaml); setSavedYaml(r.yaml)
        await load()
      } else {
        const r = await api.saveProfile(p!, version)
        setSaved(r.profile); setP(structuredClone(r.profile)); setVersion(r.version)
      }
      setFlash('Saved'); setTimeout(() => setFlash(null), 2000)
    } catch (e) {
      if ((e as { status?: number }).status === 409) setConflict(true)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const ids = allIds(p)

  return (
    <div className="space-y-8">
      <div className="animate-rise flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="eyebrow">Master profile</p>
          <h1 className="font-serif text-5xl leading-tight text-ink">The source of truth.</h1>
          <p className="mt-2 max-w-2xl text-muted">
            Every tailored resume can only use what’s written here. Keep each entry exactly true. Evidence ids are what claims cite, so
            deleting one will break resumes that use it.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {flash && <span className="animate-rise text-sm text-ok">✓ {flash}</span>}
          {(dirty || tab === 'YAML') && (
            <>
              {profileDirty && tab !== 'YAML' && <button className="btn" onClick={() => setP(structuredClone(saved!))}>Discard</button>}
              <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? <><Spinner /> Saving…</> : 'Save profile'}</button>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-rule" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            disabled={t !== tab && (yamlDirty || (profileDirty && t === 'YAML'))}
            onClick={() => setTab(t)}
            className={cx('-mb-px border-b-2 px-3 py-2 text-sm transition disabled:opacity-40', tab === t ? 'border-rust text-ink' : 'border-transparent text-muted hover:text-ink')}
          >
            {t}
          </button>
        ))}
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {conflict && (
        <div className="flex flex-wrap items-center gap-3 rounded border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn">
          Your profile changed elsewhere (another tab, or evidence approved during a tailoring).
          <button className="btn py-1" onClick={() => { if (!dirty || window.confirm('Reload and discard your unsaved edits here?')) void load() }}>Reload latest</button>
        </div>
      )}

      {tab === 'Experience' && (
        <div className="space-y-8">
          {p.roles.map((r, ri) => (
            <section key={r.id} className="sheet animate-rise rounded p-6" style={{ animationDelay: `${ri * 50}ms` }}>
              <div className="grid gap-3 md:grid-cols-[1fr_1fr_180px]">
                {([['employer', 'Employer'], ['location', 'Location'], ['dates', 'Dates']] as const).map(([k, label]) => (
                  <label key={k} className="text-xs text-muted">{label}
                    <input className="field mt-1 text-sm text-ink" value={r[k]} onChange={(e) => edit((d) => { d.roles[ri][k] = e.target.value })} />
                  </label>
                ))}
                <label className="text-xs text-muted md:col-span-3">Title (locked on every resume, so it must match your real title)
                  <input className="field mt-1 font-semibold text-rust" value={r.title} onChange={(e) => edit((d) => { d.roles[ri].title = e.target.value })} />
                </label>
              </div>
              {r.scope && (
                <div className="mt-4">
                  <p className="eyebrow mb-1">Scope</p>
                  <EvidenceRow e={r.scope} onChange={(e) => edit((d) => { d.roles[ri].scope = { ...d.roles[ri].scope!, ...e } })} onDelete={() => edit((d) => { delete d.roles[ri].scope })} />
                </div>
              )}
              <p className="eyebrow mb-1 mt-4">Achievements</p>
              <div className="divide-y divide-rule/60">
                {r.achievements.map((a, ai) => (
                  <EvidenceRow key={a.id} e={a} onChange={(e) => edit((d) => { d.roles[ri].achievements[ai] = e })} onDelete={() => edit((d) => { d.roles[ri].achievements.splice(ai, 1) })} />
                ))}
              </div>
              <button className="btn btn-ghost mt-2 text-sm text-rust" onClick={() => edit((d) => { d.roles[ri].achievements.push({ id: nextId(`${r.id}.a`, ids), text: '', source: 'interview', in_base_resume: false }) })}>
                + Add achievement
              </button>
              {r.sub_roles.length > 0 && (
                <>
                  <p className="eyebrow mb-1 mt-4">Earlier roles here</p>
                  {r.sub_roles.map((s, si) => (
                    <div key={s.id} className="grid grid-cols-[220px_1fr] gap-3 py-1">
                      <input className="field text-sm font-semibold" aria-label={`${s.id} label`} value={s.label} onChange={(e) => edit((d) => { d.roles[ri].sub_roles[si].label = e.target.value })} />
                      <Grow label={`${s.id} text`} value={s.text} onChange={(v) => edit((d) => { d.roles[ri].sub_roles[si].text = v })} />
                    </div>
                  ))}
                </>
              )}
            </section>
          ))}
        </div>
      )}

      {tab === 'Skills' && (
        <div className="space-y-4">
          <p className="text-sm text-muted">Only skills you’ve used hands-on. Tailored competencies may reorder these, use approved synonyms or a sub-phrase, but never add new ones.</p>
          {p.skills.map((g, gi) => (
            <div key={gi} className="sheet grid gap-3 rounded p-4 md:grid-cols-[200px_1fr]">
              <input className="field font-semibold" aria-label="Category" value={g.category} onChange={(e) => edit((d) => { d.skills[gi].category = e.target.value })} />
              <div>
                <div className="flex flex-wrap gap-1.5">
                  {g.items.map((item, ii) => (
                    <span key={ii} className="chip text-[12px] text-body">
                      {item}
                      <button onClick={() => edit((d) => { d.skills[gi].items.splice(ii, 1) })} aria-label={`Remove ${item}`} className="text-faint hover:text-bad">×</button>
                    </span>
                  ))}
                </div>
                <input
                  className="field mt-2 text-sm"
                  placeholder="Add a skill and press Enter"
                  onKeyDown={(e) => {
                    const v = e.currentTarget.value.trim()
                    if (e.key === 'Enter' && v) { edit((d) => { d.skills[gi].items.push(v) }); e.currentTarget.value = '' }
                  }}
                />
              </div>
            </div>
          ))}
          <button className="btn btn-ghost text-sm text-rust" onClick={() => edit((d) => { d.skills.push({ category: 'New group', items: [] }) })}>+ Add skill group</button>
        </div>
      )}

      {tab === 'Headlines' && (
        <div className="space-y-3">
          <p className="text-sm text-muted">The AI picks a headline from this approved list, based on the role’s track.</p>
          {p.headlines.map((h, hi) => (
            <div key={h.id} className="sheet grid items-center gap-3 rounded p-4 md:grid-cols-[1fr_auto_auto]">
              <input className="field font-semibold text-rust" aria-label={`Headline ${h.id}`} value={h.text} onChange={(e) => edit((d) => { d.headlines[hi].text = e.target.value })} />
              <div className="flex gap-3 text-sm">
                {TRACKS.map((t) => (
                  <label key={t} className="flex items-center gap-1.5">
                    <input type="checkbox" className="accent-rust" checked={h.tracks.includes(t)}
                      onChange={() => edit((d) => { const tr = d.headlines[hi].tracks; d.headlines[hi].tracks = tr.includes(t) ? tr.filter((x) => x !== t) : [...tr, t] })} />
                    {t}
                  </label>
                ))}
              </div>
              <button className="text-faint hover:text-bad disabled:opacity-30" disabled={p.headlines.length < 2} onClick={() => edit((d) => { d.headlines.splice(hi, 1) })} aria-label="Delete headline">✕</button>
            </div>
          ))}
          <button className="btn btn-ghost text-sm text-rust" onClick={() => edit((d) => { d.headlines.push({ id: nextId('h.custom', ids), text: '', tracks: ['ic'] }) })}>+ Add headline</button>
        </div>
      )}

      {tab === 'Summary & highlights' && (
        <div className="grid gap-8 md:grid-cols-2">
          {(['summary_facts', 'highlights'] as const).map((key) => (
            <section key={key} className="sheet rounded p-5">
              <p className="eyebrow mb-2">{key === 'summary_facts' ? 'Summary & general facts' : 'Career highlights'}</p>
              <div className="divide-y divide-rule/60">
                {p[key].map((e, i) => (
                  <EvidenceRow key={e.id} e={e} onChange={(v) => edit((d) => { d[key][i] = v })} onDelete={() => edit((d) => { d[key].splice(i, 1) })} />
                ))}
              </div>
              <button className="btn btn-ghost mt-2 text-sm text-rust" onClick={() => edit((d) => { d[key].push({ id: nextId(key === 'summary_facts' ? 'summary.s' : 'highlight.h', ids), text: '', source: 'interview', in_base_resume: false }) })}>+ Add</button>
            </section>
          ))}
        </div>
      )}

      {tab === 'Projects & more' && (
        <div className="space-y-6">
          {(['projects', 'education', 'extras'] as const).map((key) => (
            <section key={key} className="sheet rounded p-5">
              <p className="eyebrow mb-3">{{ projects: 'Projects & community', education: 'Education & certifications', extras: 'Awards & languages' }[key]}</p>
              {p[key].map((item, i) => (
                <div key={item.id} className="grid gap-3 py-1.5 md:grid-cols-[110px_220px_1fr]">
                  <p className="pt-2 font-mono text-[11px] text-rust">{item.id}</p>
                  <input className="field text-sm font-semibold" aria-label={`${item.id} label`} value={item.label} onChange={(e) => edit((d) => { d[key][i].label = e.target.value })} />
                  <Grow label={`${item.id} text`} value={item.text} onChange={(v) => edit((d) => { d[key][i].text = v })} />
                </div>
              ))}
            </section>
          ))}
        </div>
      )}

      {tab === 'Synonyms' && (
        <div className="grid gap-8 md:grid-cols-2">
          <section className="sheet rounded p-5">
            <p className="eyebrow mb-1">Synonym groups</p>
            <p className="mb-3 text-sm text-muted">Interchangeable terms, one group per line, comma-separated. Example: <span className="font-mono text-xs">WAF, Web Application Firewall</span></p>
            <RawListField label="Synonym groups" value={p.synonyms} format={() => p.synonyms.map((g) => g.join(', ')).join('\n')}
              parse={(t) => edit((d) => { d.synonyms = t.split('\n').map((l) => l.split(',').map((x) => x.trim()).filter(Boolean)).filter((g) => g.length) })} />
          </section>
          <section className="sheet rounded p-5">
            <p className="eyebrow mb-1">Approved vocabulary</p>
            <p className="mb-3 text-sm text-muted">Proper nouns allowed in any claim (e.g. Singapore, APAC), one per line. Keep this short.</p>
            <RawListField label="Vocabulary" value={p.vocabulary} format={() => p.vocabulary.join('\n')}
              parse={(t) => edit((d) => { d.vocabulary = t.split('\n').map((x) => x.trim()).filter(Boolean) })} />
          </section>
        </div>
      )}

      {tab === 'Answers & gaps' && <AnswersPanel />}
      {tab === 'Style preferences' && <PreferencesPanel />}
      {tab === 'History' && <HistoryPanel hasUnsaved={dirty} onRestored={() => { void load() }} />}

      {tab === 'YAML' && (
        <div>
          <p className="mb-2 text-sm text-muted">The raw file (<span className="font-mono text-xs">private/profile.yaml</span>). It’s validated on save, and duplicate ids or a bad structure are rejected.</p>
          <textarea className="field min-h-[640px] font-mono text-[13px] leading-relaxed" aria-label="Profile YAML" spellCheck={false} value={yaml} onChange={(e) => setYaml(e.target.value)} />
        </div>
      )}
    </div>
  )
}
