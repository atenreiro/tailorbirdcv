import { useEffect, useRef, useState } from 'react'
import { api, type SetupState } from '../../api'
import { cx, toBase64 } from '../../lib'
import { ErrorNote, Stitching } from '../../ui'

const MAX_BYTES = 10 * 1024 * 1024
const MAX_PASTE = 200_000
const STAGES: [number, string][] = [[0, 'Extracting the text from your file'], [4, 'Reading your experience, role by role'],
  [20, 'Checking every line against your file'], [45, 'Almost there — long CVs take a little longer']]

/** Step 2: upload (or paste) the CV; the AI transcribes it into a draft the next step reviews. */
export default function UploadCv({ onImported, onBlank }: {
  onImported: (draft: NonNullable<SetupState['draft']>) => void; onBlank: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<'file' | 'paste'>('file')
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [started, setStarted] = useState<number | null>(null)
  const [now, setNow] = useState(0)

  useEffect(() => {
    if (started === null) return
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [started])

  const choose = (f: File | null | undefined) => {
    setError(null)
    if (!f) return
    if (f.size > MAX_BYTES) { setError(`${f.name} is ${(f.size / 1048576).toFixed(1)} MB; the limit is 10 MB. Save a smaller copy, or paste the text.`); return }
    if (!/\.(docx|pdf|txt|md)$/i.test(f.name)) { setError(f.name.toLowerCase().endsWith('.doc') ? 'Old .doc files can’t be read. Save it as .docx or PDF first.' : 'Use a .docx, .pdf or .txt file, or paste the text.'); return }
    setFile(f)
  }
  const read = async () => {
    setError(null)
    setStarted(Date.now())
    setNow(Date.now())
    try {
      const body = mode === 'paste' ? { text } : { filename: file!.name, data: await toBase64(file!) }
      const r = await api.importProfile(body)
      onImported({ profile: r.profile, unverified: r.unverified })
    } catch (e) {
      setError((e as Error).message)
      setStarted(null)
    }
  }
  const ready = mode === 'paste' ? text.trim().length >= 80 : !!file
  const elapsed = started ? Math.max(0, Math.round((now - started) / 1000)) : 0
  const stage = STAGES.filter(([t]) => elapsed >= t).at(-1)![1]

  if (started !== null) {
    return (
      <div role="status" className="flex flex-col items-center gap-4 rounded-[14px] border border-rule bg-sheet px-6 py-14 text-center">
        <Stitching mode="ai" />
        <p className="font-display text-2xl text-ink">{stage}…</p>
        <ol className="flex flex-col gap-1 text-[13px] text-muted">
          {STAGES.slice(0, 3).map(([t, s]) => <li key={s} className={cx(elapsed >= t ? 'text-ink' : 'text-faint')}>{elapsed >= t ? '●' : '○'} {s}</li>)}
        </ol>
        <p className="font-mono text-xs text-faint">{elapsed}s · usually 30–60 seconds</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div role="group" aria-label="Import from" className="inline-flex h-9 w-fit gap-0.5 rounded-lg bg-lane p-[3px]">
        {(['file', 'paste'] as const).map((m) => (
          <button key={m} aria-pressed={mode === m} onClick={() => { setMode(m); setError(null) }}
            className={cx('h-[30px] cursor-pointer rounded-md px-3 text-[13px] font-medium transition-colors',
              mode === m ? 'bg-sheet text-ink shadow-[0_1px_2px_rgb(15_61_46/0.12)]' : 'text-muted hover:text-ink')}>
            {m === 'file' ? 'Upload a file' : 'Paste text'}
          </button>
        ))}
      </div>
      {mode === 'file' ? (
        <>
          <input ref={input} type="file" className="sr-only" tabIndex={-1} aria-hidden
            accept=".docx,.pdf,.txt,.md,.rtf,.doc,.odt,.pages,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => { choose(e.target.files?.[0]); e.target.value = '' }} />
          <button type="button" onClick={() => input.current?.click()}
            onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files[0]) }}
            className="flex min-h-[180px] cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-rule bg-wash px-6 text-center hover:border-accent">
            <span className="font-display text-xl text-ink">{file ? file.name : 'Drop your CV here, or click to choose'}</span>
            <span className="text-[13px] text-muted">{file ? `${Math.max(1, Math.round(file.size / 1024))} KB · click to change` : 'Word (.docx), PDF or plain text · up to 10 MB'}</span>
          </button>
        </>
      ) : (
        <textarea className="field min-h-[240px] resize-y leading-[1.5]" value={text} maxLength={MAX_PASTE}
          onChange={(e) => setText(e.target.value)} placeholder="Paste the full text of your CV…" aria-label="CV text" />
      )}
      <ErrorNote error={error} onDismiss={() => setError(null)} />
      {error && mode === 'file' && <button className="w-fit text-[13px] text-accent hover:text-accent-strong" onClick={() => { setMode('paste'); setError(null) }}>Paste the text instead →</button>}
      <p className="max-w-[680px] text-[13px] leading-[1.5] text-muted text-pretty">
        The AI copies your CV into structured sections word-for-word; it doesn’t rewrite anything. You check the result
        in the next step before anything is saved.
      </p>
      <div className="flex flex-wrap items-center gap-4">
        <button className="btn btn-primary" onClick={read} disabled={!ready}>Read my CV</button>
        <button className="text-[13px] text-muted hover:text-ink" onClick={onBlank}>No CV handy? Start with a blank profile</button>
      </div>
    </div>
  )
}
