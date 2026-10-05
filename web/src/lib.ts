// Plain helpers shared across pages (no components here, so React fast refresh stays happy).
import { useEffect } from 'react'
import type { Outcome } from './api'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

/** A file's contents as base64, for JSON uploads. */
export function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(new Error('That file could not be read.'))
    reader.readAsDataURL(file)
  })
}

export function fmtDate(iso?: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
}

const STATUS_STYLE: Record<string, string> = {
  draft: 'bg-[#e6e9ef] text-muted',
  analyzed: 'bg-[#e6e9ef] text-ink',
  composed: 'bg-[#f6ead2] text-warn',
  built: 'bg-[#dfe5fb] text-accent',
  applied: 'bg-ink text-white',
  interview: 'bg-[#dcefe5] text-ok',
  offer: 'bg-ok text-white',
  closed: 'bg-[#e6e9ef] text-faint',
}

/** Closing outcomes, grouped by who ended it. */
export const OUTCOMES: { key: Outcome; label: string; who: 'them' | 'you' | 'success'; style: string }[] = [
  { key: 'rejected', label: 'Rejected', who: 'them', style: 'bg-bad-soft text-bad' },
  { key: 'no_response', label: 'No response', who: 'them', style: 'bg-[#e6e9ef] text-muted' },
  { key: 'role_closed', label: 'Role closed', who: 'them', style: 'bg-[#e6e9ef] text-muted' },
  { key: 'withdrew', label: 'Withdrew', who: 'you', style: 'bg-[#e6e9ef] text-faint' },
  { key: 'declined_offer', label: 'Declined offer', who: 'you', style: 'bg-[#dcefe5] text-ok' },
  { key: 'did_not_apply', label: 'Didn’t apply', who: 'you', style: 'bg-[#e6e9ef] text-faint' },
  { key: 'accepted_offer', label: 'Accepted offer', who: 'success', style: 'bg-ok text-white' },
]
export const OUTCOME_GROUPS: [('them' | 'you' | 'success'), string][] = [['them', 'Ended by them'], ['you', 'Ended by you'], ['success', 'Success']]
const outcome = (o?: string | null) => OUTCOMES.find((x) => x.key === o)

/** Tailwind classes of the status pill, for custom pills (e.g. one with a ▾ for a select). */
export function statusStyle(status: string, closedAs?: string | null) {
  return (status === 'closed' && outcome(closedAs)?.style) || (STATUS_STYLE[status] ?? STATUS_STYLE.draft)
}

/** What a status pill says: the status, or for a closed application how it ended. */
export function statusLabel(status: string, closedAs?: string | null) {
  return status === 'closed' ? outcome(closedAs)?.label ?? 'Closed' : status
}

/** Sets the browser tab title to "<parts> · AutoCV" while the page is mounted. */
export function useTitle(parts: (string | undefined)[]) {
  const title = [...parts.filter((p): p is string => !!p?.trim()), 'AutoCV'].join(' · ')
  useEffect(() => {
    const previous = document.title
    document.title = title
    return () => { document.title = previous }
  }, [title])
}
