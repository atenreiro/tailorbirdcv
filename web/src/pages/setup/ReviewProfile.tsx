import { useEffect, useState, type KeyboardEvent, type ReactNode } from 'react'
import { api, ApiError, type ImportDraft, type Profile } from '../../api'
import { cx } from '../../lib'
import { ErrorNote, Spinner } from '../../ui'
import { setUnsaved } from '../../unsaved'
import { applyRemovals, finalPath, getValue, removalKey, setValue, type Lead, type Value } from './profilePaths'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'
type Resolution = 'confirmed' | 'edited'

/** Step 3: the CV as read back. Lines that aren't in the file word-for-word must be fixed, removed or
 *  confirmed before the profile is saved; any line can be edited. The server checks again on save. */
export default function ReviewProfile({ draft, onSaved, onRestart }: {
  draft: ImportDraft; onSaved: () => void; onRestart: () => void
}) {
  const [profile, setProfile] = useState<Profile>(draft.profile)
  const [flagged, setFlagged] = useState<string[]>(draft.unverified)
  const [resolved, setResolved] = useState<Record<string, Resolution>>({})
  const [removed, setRemoved] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<{ path: string; value: Value } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const touched = Object.keys(resolved).length > 0 || removed.size > 0 || profile !== draft.profile
  useEffect(() => {
    setUnsaved('setup-review', touched)
    return () => setUnsaved('setup-review', false)
  }, [touched])

  const isRemoved = (path: string) => { const k = removalKey(profile, path); return !!k && removed.has(k) }
  const open = flagged.filter((p) => !resolved[p] && !isRemoved(p))

  const jump = () => {
    const el = document.querySelector<HTMLElement>(`[data-path="${CSS.escape(open[0])}"]`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el?.querySelector<HTMLElement>('button')?.focus({ preventScroll: true })
  }
  const resolve = (path: string, how: Resolution | null) =>
    setResolved((r) => { const next = { ...r }; if (how) next[path] = how; else delete next[path]; return next })
  const toggleRemove = (key: string) =>
    setRemoved((s) => { const next = new Set(s); if (next.has(key)) next.delete(key); else next.add(key); return next })
  const saveEdit = () => {
    if (!editing) return
    setProfile((p) => setValue(p, editing.path, editing.value))
    if (flagged.includes(editing.path)) resolve(editing.path, 'edited')
    setEditing(null)
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    const final = applyRemovals(profile, removed)
    const confirmed = Object.entries(resolved).filter(([, how]) => how === 'confirmed').map(([p]) => finalPath(profile, p, removed))
    try {
      await api.createProfile({ profile: final, confirmed })
      setUnsaved('setup-review', false)
      onSaved()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'unconfirmed' && Array.isArray(e.detail?.paths)) {
        // Some edits still don't match the file: continue from the saved shape and ask about those.
        setProfile(final)
        setRemoved(new Set())
        setFlagged(e.detail.paths as string[])
        setResolved(Object.fromEntries(confirmed.map((p) => [p, 'confirmed' as const])))
        setNotice('Some edited lines still don’t match your file word-for-word. Change them, or confirm they’re correct.')
      } else {
        setError((e as Error).message)
      }
    } finally {
      setBusy(false)
    }
  }

  const row = (path: string, display: ReactNode, opts: { tag?: string; locked?: boolean } = {}) => {
    const flag = flagged.includes(path)
    const how = resolved[path]
    const key = removalKey(profile, path)
    const gone = !!key && removed.has(key)
    const isEditing = editing?.path === path
    const value = getValue(profile, path)
    return (
      <li key={path} data-path={path}
        className={cx('group flex flex-col gap-1.5 rounded-lg px-2.5 py-1.5 text-[13.5px] leading-[1.5]',
          flag && !how && !gone ? 'bg-warn-soft ring-1 ring-[#e9c98f]' : 'hover:bg-wash')}>
        <div className="flex items-start gap-2">
          {opts.tag && <span className="mt-[3px] w-16 flex-none font-mono text-[10px] uppercase tracking-[0.06em] text-faint">{opts.tag}</span>}
          <div className={cx('min-w-0 flex-1', gone && 'text-faint line-through')}>
            {isEditing ? (
              <Editor value={editing.value} onChange={(v) => setEditing({ path, value: v })} onSave={saveEdit} onCancel={() => setEditing(null)} />
            ) : display}
          </div>
          {!isEditing && (
            <div className={cx('flex flex-none items-center gap-1.5', !flag && 'opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100')}>
              {gone ? (
                <button className="text-xs text-accent hover:text-accent-strong" onClick={() => toggleRemove(key!)}>Undo remove</button>
              ) : (
                <>
                  {how && <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ok">✓ {how}</span>}
                  {how && <button className="text-xs text-muted hover:text-ink" onClick={() => resolve(path, null)}>Undo</button>}
                  {!how && value !== null && (
                    <button className="rounded px-1.5 py-0.5 text-xs text-accent hover:bg-accent-soft" onClick={() => setEditing({ path, value })}>
                      {flag ? 'Fix' : 'Edit'}</button>
                  )}
                  {!how && key && <button className="rounded px-1.5 py-0.5 text-xs text-muted hover:bg-wash hover:text-bad" onClick={() => toggleRemove(key)}>Remove</button>}
                  {flag && !how && (
                    <button className="rounded border border-[#d9b36b] bg-sheet px-2 py-0.5 text-xs font-medium text-warn hover:border-warn"
                      onClick={() => resolve(path, 'confirmed')}>It’s correct</button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        {flag && !how && !gone && !isEditing && (
          <p className="text-xs text-warn">Not found word-for-word in your file{opts.locked ? ' — this appears on every resume exactly as written' : ''}.</p>
        )}
      </li>
    )
  }

  const p = profile
  const bullets = p.roles.reduce((n, r) => n + r.achievements.length, 0)
  const section = (title: string, items: ReactNode[], hint?: string) => items.length > 0 && (
    <section className="flex flex-col gap-1">
      <p className={cx(label, 'px-2.5 text-muted')}>{title}</p>
      {hint && <p className="px-2.5 text-xs text-faint">{hint}</p>}
      <ul className="flex flex-col gap-0.5">{items}</ul>
    </section>
  )
  const lead = (l: Lead) => <><strong className="text-ink">{l.label}</strong> {l.text}</>

  return (
    <div className="flex flex-col gap-5">
      <div className="sticky top-14 z-10 -mx-1 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-rule bg-sheet/95 px-4 py-3 shadow-[0_8px_24px_-18px_rgb(15_61_46/0.5)] backdrop-blur">
        <span className="text-[13px] text-body">
          {p.roles.length} role{p.roles.length === 1 ? '' : 's'} · {bullets} achievement{bullets === 1 ? '' : 's'} · {p.skills.length} skill group{p.skills.length === 1 ? '' : 's'}
        </span>
        {open.length > 0 ? (
          <>
            <span className="font-semibold text-warn">{open.length} line{open.length > 1 ? 's' : ''} need{open.length > 1 ? '' : 's'} your attention</span>
            <button className="btn !py-1 text-[13px]" onClick={jump}>Jump to next</button>
          </>
        ) : (
          <span className="font-semibold text-ok">✓ Every line matches your file or is confirmed</span>
        )}
        <span className="ml-auto flex gap-2">
          <button className="btn" onClick={onRestart} disabled={busy}>Start over</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || open.length > 0}
            title={open.length ? 'Fix, remove or confirm the highlighted lines first' : undefined}>
            {busy && <Spinner />}Save my profile</button>
        </span>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {notice && <p role="status" className="rounded-lg bg-warn-soft px-4 py-3 text-[13.5px] text-warn">{notice}</p>}
      <p className="max-w-[760px] text-[13px] leading-[1.5] text-muted text-pretty">
        Everything TailorbirdCV writes later comes only from this profile. Highlighted lines didn’t match your file word-for-word
        (the AI may have misread them): fix, remove, or confirm each one. You can edit any line, and refine everything later
        under Master profile.
      </p>

      <div className="flex flex-col gap-5 rounded-[14px] border border-rule bg-sheet px-3 py-5 sm:px-5">
        {section('You', [
          row('contact.name', <span className="font-display text-[22px] text-ink">{p.contact.name}</span>, { tag: 'Name', locked: true }),
          ...p.headlines.map((h, i) => row(`headlines[${i}]`, <span className="font-semibold text-accent">{h.text}</span>, { tag: 'Headline' })),
          ...(['location', 'phone', 'email'] as const).filter((k) => p.contact[k]).map((k) => row(`contact.${k}`, p.contact[k], { tag: k })),
          ...p.contact.links.flatMap((l, i) => [row(`contact.links[${i}].text`, l.text, { tag: 'Link' }), row(`contact.links[${i}].url`, <span className="font-mono text-xs">{l.url}</span>, { tag: 'URL' })]),
        ])}
        {section('Summary', p.summary_facts.map((f) => row(f.id, f.text)))}
        {section('Highlights', p.highlights.map((f) => row(f.id, <>• {f.text}</>)))}
        {section('Skills', p.skills.flatMap((g, gi) => [
          row(`skills[${gi}].category`, <strong className="text-ink">{g.category}</strong>, { tag: 'Group' }),
          ...g.items.map((item, j) => row(`skills[${gi}].items[${j}]`, item, { tag: '' })),
        ]))}
        {p.roles.map((r) => (
          <section key={r.id} className="flex flex-col gap-1 border-t border-line pt-4">
            <ul className="flex flex-col gap-0.5">
              {row(`${r.id}.employer`, <strong className="text-ink">{r.employer}</strong>, { tag: 'Employer', locked: true })}
              {r.location && row(`${r.id}.location`, r.location, { tag: 'Where', locked: true })}
              {row(`${r.id}.title`, <strong className="text-accent">{r.title}</strong>, { tag: 'Title', locked: true })}
              {r.dates && row(`${r.id}.dates`, <span className="font-mono text-xs">{r.dates}</span>, { tag: 'Dates', locked: true })}
              {r.scope && row(r.scope.id, <em>{r.scope.text}</em>, { tag: 'Scope' })}
              {r.achievements.map((a) => row(a.id, <>• {a.text}</>))}
              {r.sub_roles.map((s) => row(s.id, <>• {lead(s)}</>))}
            </ul>
          </section>
        ))}
        {section('Projects', p.projects.map((i) => row(i.id, <>• {lead(i)}</>)))}
        {section('Education & certifications', p.education.map((i) => row(i.id, <>• {lead(i)}</>)), 'Appears on every resume exactly as written.')}
        {section('Awards, languages & more', p.extras.map((i) => row(i.id, <>• {lead(i)}</>)))}
      </div>
    </div>
  )
}

function Editor({ value, onChange, onSave, onCancel }: {
  value: Value; onChange: (v: Value) => void; onSave: () => void; onCancel: () => void
}) {
  const keys = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSave() }
    if (e.key === 'Escape') { e.preventDefault(); onCancel() }
  }
  return (
    <div className="flex flex-col gap-2">
      {typeof value === 'string' ? (
        <textarea className="field min-h-[60px] resize-y text-[13.5px]" value={value} autoFocus aria-label="Edit line"
          onChange={(e) => onChange(e.target.value)} onKeyDown={keys} />
      ) : (
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <input className="field text-[13.5px] font-semibold" value={value.label} autoFocus aria-label="Label" placeholder="Label"
            onChange={(e) => onChange({ ...value, label: e.target.value })} onKeyDown={keys} />
          <input className="field text-[13.5px]" value={value.text} aria-label="Text" placeholder="Details"
            onChange={(e) => onChange({ ...value, text: e.target.value })} onKeyDown={keys} />
        </div>
      )}
      <div className="flex items-center gap-2">
        <button className="btn btn-primary !py-1 text-[13px]" onClick={onSave}>Save line</button>
        <button className="btn !py-1 text-[13px]" onClick={onCancel}>Cancel</button>
        <span className="text-xs text-faint">Enter to save · Esc to cancel</span>
      </div>
    </div>
  )
}
