import { useState } from 'react'
import { api, type Settings as SettingsData } from '../api'
import { cx } from '../lib'
import { ErrorNote, Spinner } from '../ui'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'

/** Settings → Privacy: hide contact details from the AI (privacy.py). Experimental, and says so. */
export default function PrivacyCard({ settings, onSaved }: { settings: SettingsData; onSaved: (s: SettingsData) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [address, setAddress] = useState(settings.private_address ?? '')
  const [preview, setPreview] = useState<{ on: boolean; text: string; hidden: Record<string, string> } | null>(null)
  const save = (patch: Partial<SettingsData>) => {
    setBusy(true); setError(null)
    api.saveSettings(patch).then((s) => { onSaved(s); setPreview(null) }).catch((e) => setError((e as Error).message)).finally(() => setBusy(false))
  }
  const show = () => {
    setBusy(true); setError(null)
    api.privacyPreview().then(setPreview).catch((e) => setError((e as Error).message)).finally(() => setBusy(false))
  }
  const hidden = preview ? Object.entries(preview.hidden) : []
  return (
    <section aria-labelledby="privacy-title" className="animate-rise flex min-w-0 max-w-[980px] flex-col gap-4 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7">
      <div className="flex flex-col gap-1.5">
        <p className={cx(label, 'text-accent')}>Privacy</p>
        <h2 id="privacy-title" className="flex flex-wrap items-center gap-3 font-display text-[28px] leading-none tracking-[-0.01em] text-ink">
          What the AI sees
          <span className="rounded bg-warn-soft px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-warn">Experimental</span>
        </h2>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <label className="flex cursor-pointer items-start gap-2.5 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={settings.hide_personal} disabled={busy}
          onChange={(e) => save({ hide_personal: e.target.checked })} />
        <span className="flex flex-col gap-0.5">
          <span className="font-medium text-ink">Hide my personal details from the AI</span>
          <span className="text-muted text-pretty">
            Your name, email, phone, street address and personal links (and any other email address, phone number or
            profile link in what you type) are replaced by placeholders like [NAME] before anything goes to the AI, and put
            back in its answers. Your resume still shows them: TailorbirdCV prints them itself.
          </span>
        </span>
      </label>
      <div role="note" className="rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-warn text-pretty">
        <span className="font-semibold">Experimental: use with care.</span> It matches your details as written and common
        formats of emails, phone numbers and links; an unusual spelling can slip through. Your career history (employers,
        titles, dates, achievements) is still sent and can identify you, and other people’s names aren’t detected. Check
        “See what the AI receives” below.
      </div>
      <label className="flex max-w-[520px] flex-col gap-1 text-[13px] font-medium text-ink">
        <span>Street address to hide <span className="font-normal text-muted">(optional; TailorbirdCV never prints it on your resume)</span></span>
        <span className="flex gap-2">
          <input className="field" value={address} onChange={(e) => setAddress(e.target.value)} autoComplete="street-address" disabled={busy} />
          <button className="btn shrink-0" disabled={busy || address === (settings.private_address ?? '')} onClick={() => save({ private_address: address.trim() })}>Save</button>
        </span>
      </label>
      <div className="flex flex-col gap-3 border-t border-line pt-4">
        <div><button className="btn" onClick={show} disabled={busy}>{busy && <Spinner />}See what the AI receives</button></div>
        {preview && (
          <div className="animate-rise flex flex-col gap-3">
            <p className="text-[13px] text-muted text-pretty">
              {preview.on
                ? hidden.length
                  ? <>Your profile as every AI request carries it. Hidden here: {hidden.map(([t, v]) => <span key={t} className="mr-2 whitespace-nowrap"><span className="font-mono text-xs text-accent">{t}</span> = {v}</span>)}</>
                  : 'Your profile as every AI request carries it. Your contact details are never in it (they’re always left out); placeholders appear when they show up elsewhere, such as in your answers.'
                : 'Privacy mode is off: this is what the AI receives, with only the contact block left out.'}
            </p>
            <pre className="max-h-[360px] overflow-auto whitespace-pre-wrap rounded-xl border border-rule bg-wash px-4 py-3 font-mono text-xs leading-[1.6] text-body">{preview.text}</pre>
          </div>
        )}
      </div>
    </section>
  )
}
