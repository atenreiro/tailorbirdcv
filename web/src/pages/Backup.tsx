import { useRef, useState } from 'react'
import { api, type RestoreResult } from '../api'
import { cx } from '../lib'
import { ErrorNote, Spinner } from '../ui'

const label = 'font-mono text-[11px] uppercase tracking-[0.08em]'
const PROVIDER_NAMES: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI', openrouter: 'OpenRouter' }
const names = (ids: string[]) => ids.map((id) => PROVIDER_NAMES[id] ?? id).join(', ')

/** Shown after every backup (the same words as `tailorbirdcv backup`, backup.WARNING). */
function BackupWarning({ name, keys }: { name: string; keys: string[] }) {
  return (
    <div role="alert" className="animate-rise flex flex-col gap-1.5 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-warn">
      <p className="font-semibold">Saved {name}{keys.length > 0 && ` (with your ${names(keys)} API ${keys.length > 1 ? 'keys' : 'key'})`}. Keep it safe.</p>
      <p className="text-pretty">
        This backup isn’t encrypted: anyone who has the file can read your CV, contact details and
        applications{keys.length > 0 && ', and use your API keys'}. Store it somewhere private (for example an encrypted
        drive or your own cloud folder) and don’t share it.
      </p>
    </div>
  )
}

/** Pick a backup, confirm, restore. `replaces`: there's data now (Settings), so say what happens to it. */
export function RestoreBackup({ replaces, onRestored, className }: {
  replaces: boolean; onRestored: (r: RestoreResult) => void; className?: string
}) {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const restore = (f: File) => {
    setBusy(true); setError(null)
    api.restoreBackup(f).then(onRestored).catch((e) => setError((e as Error).message)).finally(() => { setBusy(false); setFile(null) })
  }
  const pick = (f: File | undefined) => {
    if (input.current) input.current.value = ''
    if (!f) return
    if (replaces) setFile(f)
    else restore(f)
  }
  return (
    <div className={cx('flex flex-col gap-3', className)}>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <input ref={input} type="file" accept=".zip,application/zip" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
      {file ? (
        <div className="animate-rise flex flex-col gap-3 rounded-lg border border-rule bg-wash px-4 py-3.5 text-[13px]">
          <p className="text-ink text-pretty">
            Replace your profile, applications and settings with <span className="font-semibold">{file.name}</span>?
            Nothing is deleted: your current data is kept in the <span className="font-mono text-xs">before-restore</span> folder
            inside your data folder.
          </p>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary" onClick={() => restore(file)} disabled={busy}>{busy && <Spinner />}{busy ? 'Restoring…' : 'Restore this backup'}</button>
            <button className="btn btn-ghost" onClick={() => setFile(null)} disabled={busy}>Cancel</button>
          </div>
        </div>
      ) : (
        <div>
          <button className="btn" onClick={() => input.current?.click()} disabled={busy}>
            {busy && <Spinner />}{busy ? 'Restoring…' : 'Restore from a backup…'}
          </button>
        </div>
      )}
    </div>
  )
}

/** Settings → Backup & restore. */
export default function BackupCard() {
  const [keys, setKeys] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<{ name: string; keys: string[] } | null>(null)
  const [restored, setRestored] = useState<RestoreResult | null>(null)
  const download = () => {
    setBusy(true); setError(null); setSaved(null)
    api.downloadBackup(keys).then(setSaved).catch((e) => setError((e as Error).message)).finally(() => setBusy(false))
  }
  return (
    <section aria-labelledby="backup-title" className="animate-rise flex min-w-0 max-w-[980px] flex-col gap-4 rounded-[14px] border border-rule bg-sheet px-5 py-6 sm:px-7">
      <div className="flex flex-col gap-1.5">
        <p className={cx(label, 'text-accent')}>Your data</p>
        <h2 id="backup-title" className="font-display text-[28px] leading-none tracking-[-0.01em] text-ink">Backup &amp; restore</h2>
        <p className="text-sm text-muted text-pretty">
          Everything TailorbirdCV keeps lives only on this computer. A backup saves your profile, memory, applications (with
          what you sent), settings and history as one .zip, to keep safe or to move to another computer.
        </p>
      </div>
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      <div className="flex flex-col gap-3">
        <label className="flex cursor-pointer items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" checked={keys} disabled={busy}
            onChange={(e) => setKeys(e.target.checked)} />
          <span className="flex flex-col gap-0.5">
            <span className="font-medium text-ink">Include my API keys</span>
            <span className="text-muted text-pretty">
              The Anthropic, OpenAI or OpenRouter keys saved here, so another computer is ready to use. Anyone with the file
              could then use them, so leave this off unless you need it.
            </span>
          </span>
        </label>
        <div>
          <button className="btn btn-primary" onClick={download} disabled={busy}>{busy && <Spinner />}{busy ? 'Preparing…' : 'Download backup'}</button>
        </div>
        {saved && <BackupWarning {...saved} />}
      </div>
      <div className="flex flex-col gap-2 border-t border-line pt-4">
        <p className="text-sm text-muted text-pretty">Restoring replaces what’s here with the backup’s data.</p>
        {restored ? (
          <div role="status" className="animate-rise flex flex-col gap-2 rounded-lg border border-ok/30 bg-ok-soft px-4 py-3 text-[13px] text-ok">
            <p className="font-semibold">
              Restored {restored.applications} application{restored.applications === 1 ? '' : 's'} from the backup
              {restored.created && ` of ${new Date(restored.created).toLocaleDateString()}`}.
            </p>
            {restored.kept && <p>Your previous data is kept in <span className="font-mono text-xs">{restored.kept}</span> in your data folder.</p>}
            {restored.keys_restored.length > 0 && <p>API keys restored: {names(restored.keys_restored)}.</p>}
            {restored.keys_failed.length > 0 && <p className="text-warn">These API keys couldn’t be saved (no keychain): {names(restored.keys_failed)}. Add them again in AI engine.</p>}
            <div><button className="btn btn-dark" onClick={() => window.location.reload()}>Reload TailorbirdCV</button></div>
          </div>
        ) : (
          <RestoreBackup replaces onRestored={setRestored} />
        )}
      </div>
    </section>
  )
}
