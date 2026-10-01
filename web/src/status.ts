// Changing an application's status. Marking it "applied" freezes the exact files sent;
// if the PDF is missing or out of date, offer "Build & freeze" instead.
import { api, ApiError, type Application, type Meta } from './api'

export type StatusResult = { meta: Meta } | { app: Application } | null

export async function changeStatus(id: string, status: string, onBuilding?: (on: boolean) => void): Promise<StatusResult> {
  try {
    return { meta: await api.patch(id, { status }) }
  } catch (e) {
    if (!(e instanceof ApiError) || e.code !== 'needs_build') throw e
    const ok = window.confirm(`${e.message}\n\nBuild a fresh PDF now and freeze the exact copy you're sending? (Word will open briefly.)`)
    if (!ok) return null
    onBuilding?.(true)
    try {
      return { app: await api.freeze(id, { build: true, markApplied: true }) }
    } finally {
      onBuilding?.(false)
    }
  }
}
