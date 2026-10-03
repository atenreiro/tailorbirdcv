// Plain helpers shared across pages (no components here, so React fast refresh stays happy).
import { useEffect } from 'react'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
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
  rejected: 'bg-bad-soft text-bad',
  withdrawn: 'bg-[#e6e9ef] text-faint line-through',
}

/** Tailwind classes of the status pill, for custom pills (e.g. one with a ▾ for a select). */
export function statusStyle(status: string) {
  return STATUS_STYLE[status] ?? STATUS_STYLE.draft
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
