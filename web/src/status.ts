// Changing an application's status. Marking it "applied" freezes the exact files sent;
// if the PDF is missing or out of date, offer "Build & freeze" instead. An application that
// was already frozen as applied (e.g. moved back and forth) is just a status change.
import { api, ApiError, type Application, type Meta, type Outcome, type SentCopy } from './api'

type StatusResult = { meta: Meta } | { app: Application } | null

/** Whether an "applied" copy was already frozen, so re-entering applied must not rebuild. */
export const sentAsApplied = (sent: (SentCopy | null | undefined)[]) => sent.some((c) => c?.reason === 'applied')

export async function changeStatus(id: string, status: string, opts: {
  outcome?: Outcome; alreadySent?: boolean; onBuilding?: (on: boolean) => void
} = {}): Promise<StatusResult> {
  const { outcome, alreadySent, onBuilding } = opts
  try {
    return { meta: await api.patch(id, outcome ? { status, outcome } : { status }) }
  } catch (e) {
    if (!(e instanceof ApiError) || e.code !== 'needs_build' || alreadySent) throw e
    const ok = window.confirm(`${e.message}\n\nBuild a fresh PDF now and freeze the exact copy you're sending?`)
    if (!ok) return null
    onBuilding?.(true)
    try {
      return { app: await api.freeze(id, { build: true, markApplied: true }) }
    } finally {
      onBuilding?.(false)
    }
  }
}
