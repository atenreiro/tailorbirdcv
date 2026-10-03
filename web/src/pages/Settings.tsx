import { useEffect, useState } from 'react'
import { api, type PdfEngine, type PdfEngineInfo, type Settings as SettingsData } from '../api'
import { cx, useTitle } from '../lib'
import { cacheSettings, loadSettings } from '../settings'
import { ErrorNote, Spinner } from '../ui'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'

const ABOUT: Record<PdfEngine, { lead: string; points: string[]; missing: string }> = {
  word: {
    lead: 'Word’s own layout, exactly.',
    points: [
      'Opens hidden in the background; its icon shows in the Dock for a few seconds.',
      'The first time, macOS may ask Word for file access or ask you to allow AutoCV to control Word.',
    ],
    missing: 'Not installed on this Mac.',
  },
  libreoffice: {
    lead: 'Nothing opens: about a second per resume.',
    points: [
      'Uses the same fonts (including Word’s Calibri and Aptos when Word is installed), so line breaks match Word’s.',
      'Runs with its own settings, separate from any LibreOffice you open yourself.',
    ],
    missing: 'Not installed. Get it free from libreoffice.org, then Detect again.',
  },
}

function EngineCard({ e, chosen, effective, busy, onChoose }: {
  e: PdfEngineInfo; chosen: boolean; effective: boolean; busy: boolean; onChoose: () => void
}) {
  const about = ABOUT[e.id]
  return (
    <label className={cx('relative flex min-w-0 flex-col gap-3 rounded-xl border px-5 py-[18px] transition-colors has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent',
      !e.available ? 'cursor-not-allowed border-rule bg-wash' : chosen
        ? 'cursor-pointer border-accent bg-sheet shadow-[0_0_0_3px_rgb(31_63_209/0.12)]'
        : 'cursor-pointer border-rule bg-sheet hover:border-[#9aa3b5]')}>
      <input type="radio" name="pdf-engine" value={e.id} className="sr-only" checked={chosen}
        aria-label={`${e.name}${e.available ? (e.version ? `, version ${e.version}` : '') : ', not installed'}`}
        disabled={!e.available || busy} onChange={onChoose} />
      <span className="flex items-start gap-3">
        <span aria-hidden className={cx('mt-[3px] grid size-[18px] flex-none place-items-center rounded-full border-2',
          chosen ? 'border-accent' : 'border-[#b8c0cc]')}>
          {chosen && <span className="size-2 rounded-full bg-accent" />}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className={cx('font-display text-[22px] leading-none', e.available ? 'text-ink' : 'text-faint')}>{e.name}</span>
            {e.id === 'word' && <span className="rounded bg-[#e6e9ef] px-[7px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-body">Default</span>}
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
          <span className="font-semibold text-ink">{about.lead}</span>
          {about.points.map((p) => <span key={p} className="text-muted text-pretty">{p}</span>)}
          {e.path && <span className="truncate font-mono text-[11px] text-faint" title={e.path}>{e.path}</span>}
        </span>
      ) : (
        <span className="pl-[30px] text-[13px] text-muted text-pretty">{about.missing}</span>
      )}
    </label>
  )
}

export default function Settings() {
  useTitle(['Settings'])
  const [s, setS] = useState<SettingsData | null>(null)
  const [busy, setBusy] = useState<'detect' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  useEffect(() => { loadSettings(true).then(setS).catch((e) => setError(e.message)) }, [])
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
        <p className="text-lg text-body">How AutoCV works on this Mac.</p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {!s && !error && <p className="flex items-center gap-2 text-muted"><Spinner /> Looking for Word and LibreOffice…</p>}

      {s && (
        <section aria-labelledby="pdf-title" className="animate-rise flex min-w-0 max-w-[980px] flex-col gap-5 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="flex max-w-[640px] flex-col gap-1.5">
              <p className={cx(label, 'text-accent')}>PDF export</p>
              <h2 id="pdf-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Which app makes your PDF</h2>
              <p className="text-sm leading-[1.5] text-muted text-pretty">
                AutoCV renders your resume as a Word document (.docx), then an app on this Mac converts it to PDF and
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
                busy={!!busy} onChoose={() => choose(e.id)} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
