import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type UpdateStatus, type EngineId, type EngineInfo, type PdfEngine, type PdfEngineInfo, type Platform, type SectionKey, type Settings as SettingsData, type Targets, type ThemeInfo } from '../api'
import { cx, fmtDate, useTitle } from '../lib'
import { cacheSettings, loadSettings, thisComputer } from '../settings'
import { setUnsaved } from '../unsaved'
import { ErrorNote, Spinner } from '../ui'
import BackupCard from './Backup'
import PrivacyCard from './Privacy'
import SystemCheck from './SystemCheck'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'

type About = { lead: string; points: string[]; missing: string }

function about(id: PdfEngine, platform?: Platform): About {
  const here = thisComputer(platform)
  if (id === 'word') {
    return {
      lead: 'Word’s own layout, exactly.',
      points: platform === 'windows'
        ? ['Runs invisibly in the background; nothing appears on screen.',
           'If Word still needs activation or sign-in, open it once yourself first.']
        : ['Opens hidden in the background; its icon shows in the Dock for a few seconds.',
           'The first time, macOS may ask Word for file access or ask you to allow TailorbirdCV to control Word.'],
      missing: platform === 'linux' ? 'Microsoft Word isn’t available on Linux. Use LibreOffice.' : `Not installed on ${here}.`,
    }
  }
  return {
    lead: 'Nothing opens: about a second per resume.',
    points: [
      platform === 'macos'
        ? 'Uses the same fonts (including Word’s Calibri and Aptos when Word is installed), so line breaks match Word’s.'
        : 'Uses the same fonts as Word, or free look-alikes with identical letter widths when they’re missing, so line breaks match Word’s.',
      'Runs with its own settings, separate from any LibreOffice you open yourself.',
    ],
    missing: platform === 'linux'
      ? 'Not installed. Install it with your package manager (e.g. libreoffice-writer), then Detect again.'
      : 'Not installed. Get it free from libreoffice.org, then Detect again.',
  }
}

function EngineCard({ e, chosen, effective, busy, platform, onChoose }: {
  e: PdfEngineInfo; chosen: boolean; effective: boolean; busy: boolean; platform?: Platform; onChoose: () => void
}) {
  const info = about(e.id, platform)
  return (
    <label className={cx('relative flex min-w-0 flex-col gap-3 rounded-xl border px-5 py-[18px] transition-colors has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent',
      !e.available ? 'cursor-not-allowed border-rule bg-wash' : chosen
        ? 'cursor-pointer border-accent bg-sheet shadow-[0_0_0_3px_rgb(200_67_29/0.12)]'
        : 'cursor-pointer border-rule bg-sheet hover:border-[#a3bcb0]')}>
      <input type="radio" name="pdf-engine" value={e.id} className="sr-only" checked={chosen}
        aria-label={`${e.name}${e.available ? (e.version ? `, version ${e.version}` : '') : ', not installed'}`}
        disabled={!e.available} onChange={() => { if (!busy) onChoose() }} />
      <span className="flex items-start gap-3">
        <span aria-hidden className={cx('mt-[3px] grid size-[18px] flex-none place-items-center rounded-full border-2',
          chosen ? 'border-accent' : 'border-[#b4c2ba]')}>
          {chosen && <span className="size-2 rounded-full bg-accent" />}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className={cx('font-display text-[22px] leading-none', e.available ? 'text-ink' : 'text-faint')}>{e.name}</span>
            {e.id === 'word' && <span className="rounded bg-[#e3eae6] px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-body">Default</span>}
            {effective && <span className="rounded bg-accent-soft px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-accent">In use</span>}
          </span>
          <span className={cx('flex items-center gap-1.5 font-mono text-[11px]', e.available ? 'text-ok' : 'text-faint')}>
            <span className={cx('size-1.5 rounded-full', e.available ? 'bg-ok' : 'bg-faint')} />
            {e.available ? `Installed${e.version ? ` · ${e.version}` : ''}` : 'Not found'}
          </span>
        </span>
      </span>
      {e.available ? (
        <span className="flex min-w-0 flex-col gap-1.5 pl-[30px] text-[13px] leading-[1.45] text-body">
          <span className="font-semibold text-ink">{info.lead}</span>
          {info.points.map((p) => <span key={p} className="text-muted text-pretty">{p}</span>)}
          {e.path && <span className="truncate font-mono text-[11px] text-faint" title={e.path}>{e.path}</span>}
        </span>
      ) : (
        <span className="pl-[30px] text-[13px] text-muted text-pretty">{info.missing}</span>
      )}
    </label>
  )
}

const PACK_NAMES: Record<string, string> = {
  general: 'General', cybersecurity: 'Cybersecurity', software_engineering: 'Software engineering',
  data_ai: 'Data & AI', product_management: 'Product management', project_management: 'Project management',
  technical_program_management: 'Technical program management',
}

function Segmented<T extends string | number>({ label: name, options, value, onChange }: {
  label: string; options: [T, string][]; value: T; onChange: (v: T) => void
}) {
  return (
    <div role="group" aria-label={name} className="inline-flex h-9 gap-0.5 rounded-lg bg-lane p-[3px]">
      {options.map(([k, text]) => (
        <button key={String(k)} type="button" aria-pressed={value === k} onClick={() => onChange(k)}
          className={cx('h-[30px] cursor-pointer rounded-md px-3 text-[13px] font-medium transition-colors',
            value === k ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(15_61_46/0.12)]' : 'text-muted hover:text-ink')}>
          {text}
        </button>
      ))}
    </div>
  )
}

/** Who the resume is for. Steers the AI (what to emphasise, which vocabulary, spelling, length);
 *  it's never a source of facts. */
/** Who the resume is for. With `onContinue` (the setup wizard) it starts from `initial` (suggested
 *  from the CV) and saves on "Save and continue". */
export function YourTargets({ settings, onSaved, initial, onContinue }: {
  settings: SettingsData; onSaved: (s: SettingsData) => void; initial?: Targets; onContinue?: () => void | Promise<void>
}) {
  const [t, setT] = useState<Targets>(initial ?? settings.targets)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState(false)
  const dirty = JSON.stringify(t) !== JSON.stringify(settings.targets)
  useEffect(() => {
    if (onContinue) return
    setUnsaved('settings-targets', dirty)
    return () => setUnsaved('settings-targets', false)
  }, [dirty, onContinue])
  const set = <K extends keyof Targets>(k: K, v: Targets[K]) => { setT((x) => ({ ...x, [k]: v })); setFlash(false) }
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const next = await api.saveSettings({ targets: t })
      cacheSettings(next)
      onSaved(next)
      setT(next.targets)
      setFlash(true)
      await onContinue?.()  // the wizard's next step: its errors show here too
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const field = (k: 'field' | 'seniority' | 'roles' | 'region', name: string, placeholder: string, wide = false) => (
    <label className={cx('flex flex-col gap-1.5', wide && 'sm:col-span-2')}>
      <span className="text-[13px] font-semibold text-ink">{name}</span>
      <input className="field" value={t[k]} placeholder={placeholder} maxLength={k === 'roles' ? 240 : 80}
        onChange={(e) => set(k, e.target.value)} />
    </label>
  )
  return (
    <section aria-labelledby="targets-title" className={onContinue ? 'flex min-w-0 flex-col gap-5' : 'animate-rise flex min-w-0 max-w-[980px] flex-col gap-5 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7'}>
      <div className={cx('flex max-w-[640px] flex-col gap-1.5', onContinue && 'sr-only')}>
        <p className={cx(label, 'text-accent')}>Your targets</p>
        <h2 id="targets-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Who the resume is for</h2>
        <p className="text-sm leading-[1.5] text-muted text-pretty">
          Tells the AI what to emphasise and which vocabulary to use. It never adds facts: everything on your resume
          still comes from your profile.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {field('field', 'Your field', 'e.g. Software engineering, Nursing, Marketing')}
        {field('seniority', 'Seniority', 'e.g. Senior, Mid-level, Executive')}
        {field('roles', 'Roles you’re aiming for', 'e.g. Engineering manager roles in fintech and SaaS', true)}
        {field('region', 'Region', 'e.g. London, Remote (EU), Singapore/APAC')}
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">Domain pack</span>
          <select className="field" value={t.pack} onChange={(e) => set('pack', e.target.value)}>
            {settings.packs.map((p) => <option key={p} value={p}>{PACK_NAMES[p] ?? p}</option>)}
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">Spelling</span>
          <Segmented label="Spelling" options={[['US', 'US English'], ['UK', 'UK English']]} value={t.spelling} onChange={(v) => set('spelling', v)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">Page limit</span>
          <Segmented label="Page limit" options={[[1, '1 page'], [2, '2 pages'], [3, '3 pages']]} value={t.pages} onChange={(v) => set('pages', v)} />
        </div>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" onClick={save} disabled={(!dirty && !onContinue) || busy}>
          {busy && <Spinner />}{onContinue ? 'Save and continue' : 'Save targets'}</button>
        {dirty && !onContinue && <button className="btn btn-ghost" onClick={() => setT(settings.targets)} disabled={busy}>Discard</button>}
        {flash && !dirty && <span role="status" className="font-mono text-xs text-ok">✓ Saved</span>}
      </div>
    </section>
  )
}

const FONT_STACK: Record<string, string> = { Georgia: 'Georgia, Gelasio, serif', Calibri: 'Calibri, Carlito, "Instrument Sans", sans-serif' }

/** A miniature of the theme: name, headline, a heading with its rule and a few text lines. */
function ThemeSample({ t }: { t: ThemeInfo }) {
  const body = FONT_STACK.Calibri
  return (
    <span aria-hidden className="flex flex-col gap-[3px] rounded-md border border-line bg-white px-3 py-2.5">
      <span style={{ fontFamily: FONT_STACK[t.name_font] ?? body, color: `#${t.ink}` }} className="text-[15px] font-bold leading-none">Alex Morgan</span>
      <span style={{ fontFamily: body, color: `#${t.accent}` }} className="text-[8px] font-bold">Senior Product Manager</span>
      <span style={{ fontFamily: body, color: `#${t.accent}`, borderColor: `#${t.rule}` }} className="mt-1 border-b pb-[2px] text-[7px] font-bold tracking-[0.04em]">PROFESSIONAL EXPERIENCE</span>
      {[92, 80, 86].map((w) => <span key={w} className="h-[3px] rounded-full bg-[#d6dfda]" style={{ width: `${w}%` }} />)}
    </span>
  )
}

export function ResumeDesign({ settings, onSaved, bare }: { settings: SettingsData; onSaved: (s: SettingsData) => void; bare?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async (patch: Parameters<typeof api.saveSettings>[0]) => {
    setBusy(true)
    setError(null)
    try {
      const next = await api.saveSettings(patch)
      cacheSettings(next)
      onSaved(next)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const current = settings.themes.find((t) => t.id === settings.theme) ?? settings.themes[0]
  const [theme, chooseTheme] = useSettledChoice<string>(settings.theme, (id) => id !== settings.theme && save({ theme: id }))
  const paper = settings.paper ?? current?.paper ?? 'letter'
  return (
    <section aria-labelledby="design-title" className={bare ? 'flex min-w-0 flex-col gap-5' : 'animate-rise flex min-w-0 max-w-[980px] flex-col gap-5 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7'}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className={cx('flex max-w-[640px] flex-col gap-1.5', bare && 'sr-only')}>
          <p className={cx(label, 'text-accent')}>Resume design</p>
          <h2 id="design-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">How your resume looks</h2>
          <p className="text-sm leading-[1.5] text-muted text-pretty">Applies to the next build. Already-built files and sent copies keep the design they were made with.</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">Paper</span>
          <Segmented label="Paper size" options={[['letter', 'US Letter'], ['a4', 'A4']]} value={paper}
            onChange={(v) => { if (!busy) void save({ paper: v as 'letter' | 'a4' }) }} />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">Text size</span>
          <Segmented label="Text size" options={[['comfortable', 'Comfortable'], ['standard', 'Standard']]} value={settings.text_size ?? 'comfortable'}
            onChange={(v) => { if (!busy) void save({ text_size: v as 'standard' | 'comfortable' }) }} />
          <span className="max-w-[260px] text-xs text-faint">{(settings.text_size ?? 'comfortable') === 'comfortable'
            ? 'Body text 1 pt larger (10.5 pt in Classic and Modern): easier to read, a little less per page.'
            : 'Each design as drawn (9.5 pt body in Classic and Modern): fits the most per page.'}</span>
        </div>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <div role="radiogroup" aria-labelledby="design-title" className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        {settings.themes.map((t) => {
          const chosen = t.id === theme
          return (
            <label key={t.id} className={cx('flex min-w-0 cursor-pointer flex-col gap-3 rounded-xl border px-4 py-4 transition-colors has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent',
              chosen ? 'border-accent shadow-[0_0_0_3px_rgb(200_67_29/0.12)]' : 'border-rule hover:border-[#a3bcb0]')}>
              <input type="radio" name="theme" className="sr-only" checked={chosen} aria-label={t.name}
                onChange={() => chooseTheme(t.id)} />
              <ThemeSample t={t} />
              <span className="flex items-center gap-2">
                <span aria-hidden className={cx('grid size-4 flex-none place-items-center rounded-full border-2', chosen ? 'border-accent' : 'border-[#b4c2ba]')}>
                  {chosen && <span className="size-1.5 rounded-full bg-accent" />}
                </span>
                <span className="font-display text-xl leading-none text-ink">{t.name}</span>
              </span>
              <span className="text-[13px] leading-[1.45] text-muted text-pretty">{t.description}</span>
              <span className="font-mono text-[11px] text-faint">{t.fonts.join(' · ')}</span>
            </label>
          )
        })}
      </div>
      <SectionHeadings key={JSON.stringify(settings.section_titles)} settings={settings} busy={busy} save={save} />
    </section>
  )
}

const SECTION_NAMES: [SectionKey, string][] = [
  ['summary', 'Summary'], ['highlights', 'Highlights'], ['competencies', 'Skills'], ['experience', 'Experience'],
  ['projects', 'Projects'], ['education', 'Education'], ['extras', 'Everything else (awards, certificates, languages…)'],
]

/** What each section is called on the resume. A blank field prints the design's own heading. */
function SectionHeadings({ settings, busy, save }: { settings: SettingsData; busy: boolean; save: (p: { section_titles: Partial<Record<SectionKey, string>> }) => Promise<void> }) {
  const [draft, setDraft] = useState(settings.section_titles)  // the parent remounts this when the saved headings change
  const commit = (k: SectionKey) => {
    const value = draft[k].trim()
    if (!busy && value !== settings.section_titles[k]) void save({ section_titles: { [k]: value } })
  }
  return (
    <div className="flex flex-col gap-3 border-t border-rule pt-5">
      <div className="flex max-w-[640px] flex-col gap-1">
        <span className="text-[13px] font-semibold text-ink">Section headings</span>
        <span className="text-xs leading-[1.5] text-faint text-pretty">What each section is called on your resume. Leave one blank for the design’s own heading.</span>
      </div>
      <div className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
        {SECTION_NAMES.map(([k, name]) => (
          <label key={k} className="flex min-w-0 flex-col gap-1.5">
            <span className="text-[13px] text-muted">{name}</span>
            <input className="field" value={draft[k]} placeholder={settings.section_defaults[k]} maxLength={60}
              onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} onBlur={() => commit(k)}
              onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
          </label>
        ))}
      </div>
    </div>
  )
}

/** A radio group that follows the keyboard at once and saves only the option it settles on (arrowing through
 *  the options doesn't fire a save per step, and the selection never lags behind the focus). */
function useSettledChoice<T extends string>(current: T, save: (v: T) => unknown, delay = 350) {
  const [pending, setPending] = useState<T | null>(null)
  const timer = useRef(0)
  const choose = (v: T) => {
    setPending(v)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => {
      try { await save(v) } finally { setPending(null) }
    }, delay)
  }
  return [pending ?? current, choose] as const
}

const code = 'font-mono text-[12.5px]'
/** What each engine card says (the list of engines and their defaults comes from the server). */
const ENGINE_COPY: Record<EngineId, { lead: string; detail: ReactNode; keyUrl?: string }> = {
  'claude-cli': { lead: 'Your Claude subscription. No extra cost.',
    detail: <>Uses the <code className={code}>claude</code> command on this computer: install Claude Code, run <code className={code}>claude</code>, then <code className={code}>/login</code>.</> },
  'codex-cli': { lead: 'Your ChatGPT subscription. No extra cost.',
    detail: <>Uses OpenAI’s <code className={code}>codex</code> command: install it (macOS: <code className={code}>brew install --cask codex</code>; elsewhere: <code className={code}>npm i -g @openai/codex</code>), then run <code className={code}>codex login</code> and sign in with ChatGPT. Privacy: on ChatGPT plans OpenAI may use what you send to improve its models unless you turn off “Improve the model for everyone” in ChatGPT’s Data controls. API keys aren’t used for training.</> },
  'anthropic-api': { lead: 'Pay per use on your Anthropic account.', keyUrl: 'console.anthropic.com',
    detail: 'Claude through your own key, without Claude Code.' },
  'openai-api': { lead: 'Pay per use on your OpenAI account.', keyUrl: 'platform.openai.com',
    detail: 'OpenAI’s models through your own key. TailorbirdCV asks OpenAI not to store the requests.' },
  'openrouter-api': { lead: 'Pay per use. Claude by default.', keyUrl: 'openrouter.ai',
    detail: 'One key for many models; uses the same Claude model as the Anthropic option unless you choose another.' },
}
const GROUPS: [EngineInfo['kind'], string][] = [['subscription', 'Your subscription'], ['api', 'API key · pay per use']]

export function AIEngine({ settings, onSaved, bare }: { settings: SettingsData; onSaved: (s: SettingsData) => void; bare?: boolean }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<{ ready: boolean; detail: string } | null>(null)
  const apply = async (kind: string, call: () => Promise<SettingsData>) => {
    setBusy(kind)
    setError(null)
    setStatus(null)
    try {
      const next = await call()
      cacheSettings(next)
      onSaved(next)
      return next
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const test = async () => {
    setBusy('test')
    setError(null)
    try {
      const st = await api.engine()
      setStatus({ ready: st.ready, detail: st.detail })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const engines = settings.engines ?? []
  const [selected, choose] = useSettledChoice<EngineId>(settings.ai_engine,
    (id) => id !== settings.ai_engine && apply('engine', () => api.saveSettings({ ai_engine: id })))
  const current = engines.find((e) => e.id === settings.ai_engine)
  return (
    <section aria-labelledby="ai-title" className={bare ? 'flex min-w-0 flex-col gap-5' : 'animate-rise flex min-w-0 max-w-[980px] flex-col gap-5 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7'}>
      <div className={cx('flex flex-wrap items-start justify-between gap-x-6 gap-y-3', bare && 'hidden')}>
        <div className="flex max-w-[640px] flex-col gap-1.5">
          <p className={cx(label, 'text-accent')}>AI engine</p>
          <h2 id="ai-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Which AI does the writing</h2>
          <p className="text-sm leading-[1.5] text-muted text-pretty">Whichever you choose, the AI only sees what TailorbirdCV sends it for the task at hand, and every claim is fact-checked against your profile.</p>
        </div>
        <div className="flex items-center gap-3">
          {status && <span role="status" className={cx('max-w-[260px] text-xs', status.ready ? 'text-ok' : 'text-bad')}>{status.ready ? '✓ ' : '✗ '}{status.detail}</span>}
          <button className="btn" onClick={test} disabled={!!busy}>{busy === 'test' && <Spinner />}Test</button>
        </div>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <div role="radiogroup" aria-labelledby="ai-title" className="flex flex-col gap-4">
        {GROUPS.map(([kind, title]) => (
          <div key={kind} className="flex flex-col gap-2">
            <p className={label}>{title}</p>
            <div className={cx('grid grid-cols-1 gap-3.5', kind === 'api' ? 'md:grid-cols-3' : 'md:grid-cols-2')}>
              {engines.filter((e) => e.kind === kind).map((e) => {
                const chosen = selected === e.id
                const copy = ENGINE_COPY[e.id]
                return (
                  <label key={e.id} className={cx('flex min-w-0 cursor-pointer flex-col gap-2 rounded-xl border px-5 py-[18px] transition-colors has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent',
                    chosen ? 'border-accent shadow-[0_0_0_3px_rgb(200_67_29/0.12)]' : 'border-rule hover:border-[#a3bcb0]')}>
                    <input type="radio" name="ai-engine" className="sr-only" checked={chosen} aria-label={e.label}
                      onChange={() => choose(e.id)} />
                    <span className="flex flex-wrap items-center gap-2.5">
                      <span aria-hidden className={cx('grid size-[18px] flex-none place-items-center rounded-full border-2', chosen ? 'border-accent' : 'border-[#b4c2ba]')}>
                        {chosen && <span className="size-2 rounded-full bg-accent" />}
                      </span>
                      <span className="font-display text-[22px] leading-none text-ink">{e.label}</span>
                      {chosen && <span className="rounded bg-accent-soft px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-accent">In use</span>}
                    </span>
                    <span className="pl-[28px] text-[13px] font-semibold text-ink">{copy.lead}</span>
                    <span className="pl-[28px] text-[13px] leading-[1.45] text-muted text-pretty">{copy.detail}</span>
                  </label>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      {current && (current.provider || current.model_setting) && (
        <EngineOptions key={current.id} engine={current} settings={settings} busy={busy} apply={apply} />
      )}
    </section>
  )
}

/** The chosen engine's key (API engines), model, and OpenRouter's privacy routing. */
function EngineOptions({ engine, settings, busy, apply }: {
  engine: EngineInfo; settings: SettingsData; busy: string | null
  apply: (kind: string, call: () => Promise<SettingsData>) => Promise<SettingsData | undefined>
}) {
  const [key, setKey] = useState('')
  const saved = engine.model_setting ? settings[engine.model_setting] : null
  const [model, setModel] = useState(saved ?? '')
  const provider = engine.provider
  const k = provider ? settings.api_keys?.[provider] ?? settings.api_key : null
  const copy = ENGINE_COPY[engine.id]
  const fallback = engine.default_model ?? (engine.id === 'codex-cli' ? 'Codex’s own default' : 'the provider’s default')
  return (
    <div className="flex flex-col gap-4 rounded-xl bg-wash px-5 py-4">
      {provider && k && settings.keychain?.available === false && !k.configured && (
        <p className="text-[13px] text-warn text-pretty">This computer has no system keychain, so TailorbirdCV can’t save the key.
          Start TailorbirdCV with it in an environment variable instead: <code className="font-mono text-[12.5px]">{settings.platform === 'windows' ? `$env:${k.env}="…"; tailorbirdcv serve` : `${k.env}=… tailorbirdcv serve`}</code>
          {settings.platform === 'linux' && ' (or install GNOME Keyring / KWallet and log in again)'}.</p>
      )}
      {provider && k?.source === 'locked' && (
        <p className="text-[13px] text-warn text-pretty">TailorbirdCV can’t read your keychain right now (it’s locked, or access was
          denied). Unlock it, or click Allow when your system asks, then Test again.</p>
      )}
      {provider && k && settings.keychain?.available !== false && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">{engine.label} key</span>
          {k.configured && (
            <p className="flex flex-wrap items-center gap-3 text-[13px] text-body">
              <span className="font-mono">{k.masked}</span>
              <span className="text-muted">{k.source === 'keychain' ? 'stored in your keychain' : `from ${k.env ?? 'the environment'}`}</span>
              {k.source === 'keychain' && <button className="text-accent hover:text-accent-strong" disabled={!!busy}
                onClick={() => apply('delete', () => api.deleteApiKey(provider))}>Remove</button>}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <input className="field max-w-[420px] font-mono text-[13px]" type="password" autoComplete="off" spellCheck={false}
              placeholder={k.configured ? 'Replace with a new key…' : `${k.prefix ?? ''}…`} value={key} onChange={(e) => setKey(e.target.value)} aria-label={`${engine.label} API key`} />
            <button className="btn btn-primary" disabled={!key.trim() || !!busy}
              onClick={async () => { if (await apply('key', () => api.saveApiKey(key, provider))) setKey('') }}>{busy === 'key' && <Spinner />}Save key</button>
          </div>
          <span className="text-xs text-faint">Create a key at {copy.keyUrl}. TailorbirdCV keeps it in your system’s secure credential store (Keychain, Credential Manager or Secret Service), never in its files.</span>
        </div>
      )}
      {engine.id === 'openrouter-api' && (
        <label className="flex cursor-pointer items-start gap-3 text-[13px]">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={settings.openrouter_zdr} disabled={!!busy}
            onChange={(e) => void apply('zdr', () => api.saveSettings({ openrouter_zdr: e.target.checked }))} />
          <span className="flex flex-col gap-0.5">
            <span className="font-semibold text-ink">Zero data retention only</span>
            <span className="text-muted text-pretty">{settings.openrouter_zdr
              ? 'Only providers that keep nothing serve your requests, so Claude runs on Google Vertex or Amazon Bedrock.'
              : 'Requests go to Anthropic itself (Anthropic’s usual API retention applies). OpenRouter is still told not to collect your data.'}</span>
          </span>
        </label>
      )}
      {engine.model_setting && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">Model</span>
          <div className="flex flex-wrap gap-2">
            <input className="field max-w-[340px] font-mono text-[13px]" value={model} placeholder={engine.default_model ?? 'default'}
              onChange={(e) => setModel(e.target.value)} aria-label={`${engine.label} model`} />
            <button className="btn" disabled={(model.trim() || null) === (saved || null) || !!busy}
              onClick={() => apply('model', () => api.saveSettings({ [engine.model_setting!]: model.trim() || null }))}>Save model</button>
          </div>
          <span className="text-xs text-faint">Leave empty for the default ({fallback}).</span>
        </div>
      )}
    </div>
  )
}

const KIND_LABEL: Record<UpdateStatus['kind'], string> = {
  'uv-tool': 'Installed with the one-line installer: upgrades with one click',
  'uv-tool-local': 'Installed with uv from a file: upgrade with the command below',
  checkout: 'Running from a copy of the repository: upgrade with the command below',
  other: 'Installed some other way: upgrade with the command below',
}

/** Settings → Applications: company icons on the board, and learning style preferences when applying. */
function ApplicationsSettings({ settings, onSaved }: { settings: SettingsData; onSaved: (s: SettingsData) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(String(settings.auto_close.days))
  const save = (patch: Parameters<typeof api.saveSettings>[0]) => {
    setBusy(true); setError(null)
    api.saveSettings(patch).then(onSaved).catch((e) => setError((e as Error).message)).finally(() => setBusy(false))
  }
  return (
    <section id="applications" aria-labelledby="apps-title" className="animate-rise flex min-w-0 max-w-[980px] flex-col gap-4 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7">
      <div className="flex flex-col gap-1.5">
        <p className={cx(label, 'text-accent')}>Applications</p>
        <h2 id="apps-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Icons, learning and closing</h2>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <label className="flex cursor-pointer items-start gap-2.5 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={settings.company_icons} disabled={busy}
          onChange={(e) => save({ company_icons: e.target.checked })} />
        <span className="flex flex-col gap-0.5">
          <span className="font-medium text-ink">Show company icons</span>
          <span className="text-muted text-pretty">
            Shows each company’s site icon on your applications. TailorbirdCV fetches it once from the company’s own website
            (never a job board’s logo); turn this off to show no icons and fetch none.
          </span>
        </span>
      </label>
      <label className="flex cursor-pointer items-start gap-2.5 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={settings.learn_style} disabled={busy}
          onChange={(e) => save({ learn_style: e.target.checked })} />
        <span className="flex flex-col gap-0.5">
          <span className="font-medium text-ink">Learn my style when I apply</span>
          <span className="text-muted text-pretty">
            When you mark an application applied, TailorbirdCV compares what you sent with the AI’s drafts (resume and
            cover letter) and suggests style preferences for future drafts, using your AI once. Nothing is used until you
            approve it in Master profile → Style preferences.
          </span>
        </span>
      </label>
      <div className="flex items-start gap-2.5 text-sm">
        <input id="auto-close" type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={settings.auto_close.enabled}
          disabled={busy} onChange={(e) => save({ auto_close: { enabled: e.target.checked } })} />
        <span className="flex flex-col gap-1.5">
          <label htmlFor="auto-close" className="cursor-pointer font-medium text-ink">Close applications with no response</label>
          <span className="flex flex-wrap items-center gap-2 text-muted">
            <span>Close an application as <em>No response</em> when it’s still at Applied</span>
            <input type="number" min={7} max={365} inputMode="numeric" aria-label="Days after applying" value={days}
              disabled={busy || !settings.auto_close.enabled} className="field h-8 w-[72px] px-2 text-center"
              onChange={(e) => setDays(e.target.value)}
              onBlur={() => {
                const n = Math.round(Number(days))
                if (n >= 7 && n <= 365 && n !== settings.auto_close.days) save({ auto_close: { days: n } })
                else setDays(String(settings.auto_close.days))
              }}
              onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
            <span>days after you applied (7–365).</span>
          </span>
          <span className="text-muted text-pretty">
            Off by default. Applications that reached an interview or an offer are never touched, and one you reopen stays
            open. Closing doesn’t change Results: it still counts as applied.
          </span>
        </span>
      </div>
    </section>
  )
}

/** Settings → About TailorbirdCV: the version, update checks (PyPI, at most daily) and how this copy upgrades. */
function AboutTailorbirdCV({ settings, onSaved }: { settings: SettingsData; onSaved: (s: SettingsData) => void }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [busy, setBusy] = useState<'check' | 'toggle' | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.updateStatus().then(setStatus).catch((e) => setError((e as Error).message)) }, [])
  const changed = (s: UpdateStatus) => { setStatus(s); window.dispatchEvent(new Event('tailorbirdcv:update')) }
  const check = () => {
    setBusy('check'); setError(null)
    api.checkUpdate().then(changed).catch((e) => setError((e as Error).message)).finally(() => setBusy(null))
  }
  const toggle = (on: boolean) => {
    setBusy('toggle'); setError(null)
    api.saveSettings({ update_check: on })
      .then((s) => { onSaved(s); return api.updateStatus() }).then(changed)
      .catch((e) => setError((e as Error).message)).finally(() => setBusy(null))
  }
  return (
    <section id="about" aria-labelledby="about-title" className="animate-rise flex min-w-0 max-w-[980px] flex-col gap-4 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7">
      <div className="flex flex-col gap-1.5">
        <p className={cx(label, 'text-accent')}>About TailorbirdCV</p>
        <h2 id="about-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">
          {status ? `Version ${status.current}` : 'Version'}
        </h2>
        {status && <p className="text-sm leading-[1.5] text-muted text-pretty">{KIND_LABEL[status.kind]}.</p>}
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {status && status.enabled && (
        <p className="text-sm text-body">
          {status.newer ? <><strong>TailorbirdCV {status.latest} is available.</strong> </> : status.latest ? 'You have the latest version. ' : ''}
          {status.checked_at ? `Last checked ${fmtDate(status.checked_at)}, ${new Date(status.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.` : 'Not checked yet.'}
          {status.error ? <span className="text-warn"> {status.error}</span> : null}
        </p>
      )}
      {status?.command && <p className="text-sm text-body">To upgrade: <code className="rounded bg-wash px-1.5 py-0.5 font-mono text-[12.5px]">{status.command}</code></p>}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <label className="flex cursor-pointer items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={settings.update_check} disabled={!!busy}
            onChange={(e) => toggle(e.target.checked)} />
          <span className="flex flex-col gap-0.5">
            <span className="font-medium text-ink">Check for updates</span>
            <span className="text-muted text-pretty">Asks PyPI, where TailorbirdCV is published, for the latest version: when TailorbirdCV opens, at most once a day. It sends nothing about you or your resumes.</span>
          </span>
        </label>
        {settings.update_check && (
          <button className="btn" onClick={check} disabled={!!busy}>{busy === 'check' && <Spinner />}Check now</button>
        )}
      </div>
      <p className="text-sm text-muted text-pretty">
        Free software under the{' '}
        <a className="text-accent hover:underline" href="https://github.com/atenreiro/tailorbirdcv/blob/main/LICENSE" target="_blank" rel="noreferrer">GNU AGPL v3.0 or later</a>,
        with no warranty.{' '}
        <a className="text-accent hover:underline" href="https://github.com/atenreiro/tailorbirdcv" target="_blank" rel="noreferrer">Source code</a>
      </p>
    </section>
  )
}

export default function Settings() {
  useTitle(['Settings'])
  const [s, setS] = useState<SettingsData | null>(null)
  const [busy, setBusy] = useState<'detect' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  useEffect(() => { loadSettings(true).then(setS).catch((e) => setError(e.message)) }, [])
  // Saves can overlap (different sections): show the server's latest state, not whichever answer came last.
  const onSaved = (next: SettingsData) => {
    setS(next)
    loadSettings(true).then((latest) => { cacheSettings(latest); setS(latest) }).catch(() => {})
  }
  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 2200)
    return () => clearTimeout(t)
  }, [flash])

  const update = async (kind: 'detect' | 'save', call: () => Promise<SettingsData>, done: string) => {
    setBusy(kind)
    setError(null)
    try {
      const next = await call()
      cacheSettings(next)
      setS(next)
      setFlash(done)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const choose = (id: PdfEngine) => update('save', () => api.saveSettings({ pdf_engine: id }), 'Saved')
  const detect = () => update('detect', () => loadSettings(true), 'Detected')

  const chosen = s?.pdf_effective ?? null
  const missingChoice = s?.pdf_engine && s.pdf_effective && s.pdf_engine !== s.pdf_effective
    ? s.pdf_engines.find((e) => e.id === s.pdf_engine)?.name : null
  const none = s && !s.pdf_effective

  return (
    <div className="flex flex-col gap-7">
      <div className="animate-rise flex flex-col gap-2.5">
        <h1 className="font-display text-[48px] leading-[0.92] tracking-[-0.02em] text-ink sm:text-[64px]">Settings</h1>
        <p className="text-lg text-body">How TailorbirdCV works on {s ? thisComputer(s.platform) : 'this computer'}. <Link to="/setup" className="text-[15px] text-accent hover:text-accent-strong">Run the setup wizard again</Link></p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {!s && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Looking for Word and LibreOffice…</p>}

      {s && <YourTargets settings={s} onSaved={onSaved} />}

      {s && <ResumeDesign settings={s} onSaved={onSaved} />}

      {s && <AIEngine settings={s} onSaved={onSaved} />}

      {s && (
        <section aria-labelledby="pdf-title" className="animate-rise flex min-w-0 max-w-[980px] flex-col gap-5 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="flex max-w-[640px] flex-col gap-1.5">
              <p className={cx(label, 'text-accent')}>PDF export</p>
              <h2 id="pdf-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Which app makes your PDF</h2>
              <p className="text-sm leading-[1.5] text-muted text-pretty">
                TailorbirdCV renders your resume as a Word document (.docx), then an app on {thisComputer(s.platform)} converts it to PDF and
                counts the pages. When both are installed, Microsoft Word is the default.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {flash && <span role="status" className="font-mono text-xs text-ok">✓ {flash}</span>}
              <button className="btn" onClick={detect} disabled={!!busy}>
                {busy === 'detect' && <Spinner />}Detect again
              </button>
            </div>
          </div>

          {missingChoice && (
            <p className="rounded-lg bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn">
              You chose {missingChoice}, but it isn’t installed any more, so {s.pdf_engines.find((e) => e.id === s.pdf_effective)?.name} is used instead.
            </p>
          )}
          {none && (
            <p className="rounded-lg bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">
              Neither app was found, so only the .docx can be built. Install Microsoft Word or LibreOffice, then Detect again.
            </p>
          )}

          <div role="radiogroup" aria-labelledby="pdf-title" className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
            {s.pdf_engines.map((e) => (
              <EngineCard key={e.id} e={e} chosen={chosen === e.id} effective={s.pdf_effective === e.id}
                busy={!!busy} platform={s.platform} onChoose={() => choose(e.id)} />
            ))}
          </div>
        </section>
      )}

      {s && <ApplicationsSettings settings={s} onSaved={onSaved} />}

      {s && <PrivacyCard settings={s} onSaved={onSaved} />}

      <BackupCard />

      <SystemCheck />

      {s && <AboutTailorbirdCV settings={s} onSaved={onSaved} />}
    </div>
  )
}
