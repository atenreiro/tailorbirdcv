import { useRef, useState } from 'react'
import { api } from '../api'
import { toBase64 } from '../lib'
import IdentifyPdf, { type IdentifyState } from './IdentifyPdf'

const MAX_BYTES = 10 * 1024 * 1024

/** Applications → "Identify a PDF": which application a resume PDF came from. The PDF is compared with
 * your sent copies and current builds, and never stored or changed. */
export function useIdentifyPdf() {
  const input = useRef<HTMLInputElement>(null)
  const [state, setState] = useState<IdentifyState | null>(null)

  async function run(file: File) {
    if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
      setState({ name: file.name, busy: false, result: null, error: 'Choose a PDF file.' })
      return
    }
    if (file.size > MAX_BYTES) {
      setState({ name: file.name, busy: false, result: null, error: 'That PDF is larger than 10 MB, so it isn’t one of your resumes.' })
      return
    }
    setState({ name: file.name, busy: true, result: null, error: null })
    try {
      const result = await api.identifyPdf(file.name, await toBase64(file))
      setState({ name: file.name, busy: false, result, error: null })
    } catch (e) {
      setState({ name: file.name, busy: false, result: null, error: (e as Error).message })
    }
  }

  const picker = (
    <input ref={input} type="file" accept="application/pdf,.pdf" hidden
      onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void run(f) }} />
  )
  const pick = () => input.current?.click()
  const panel = state && <IdentifyPdf state={state} onClose={() => setState(null)} onFile={run} onPick={pick} />
  return { pick, picker, panel }
}

