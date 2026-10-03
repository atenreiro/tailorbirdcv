// Tracks unsaved work across the app and guards navigation away from it.
import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'

/** Edits that are lost when the page unmounts: guarded for in-app navigation and tab close. */
const dirty = new Set<string>()
/** Saves still in flight or debounced: they finish on unmount, so only closing the tab is guarded. */
const pending = new Set<string>()

export function setUnsaved(key: string, on: boolean) {
  if (on) dirty.add(key)
  else dirty.delete(key)
}

export function setPendingSave(key: string, on: boolean) {
  if (on) pending.add(key)
  else pending.delete(key)
}

export function hasUnsaved() {
  return dirty.size > 0
}

/** Ask before discarding unsaved work. Returns true when it's OK to go ahead. */
export function confirmLeave(): boolean {
  if (!hasUnsaved()) return true
  const ok = window.confirm('You have unsaved edits. Leave and discard them?')
  if (ok) dirty.clear()
  return ok
}

/** Navigation state that skips the guard (e.g. the app renaming its own URL). */
export const NO_GUARD = { noGuard: true }

/** Mount once (in App): asks before any in-app navigation or Back/Forward to another page
 *  while there are unsaved edits. Query-string changes on the same page aren't guarded. */
export function useUnsavedGuard() {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    hasUnsaved() && currentLocation.pathname !== nextLocation.pathname
    && !(nextLocation.state as { noGuard?: boolean } | null)?.noGuard)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (confirmLeave()) blocker.proceed()
    else blocker.reset()
  }, [blocker])
}

window.addEventListener('beforeunload', (e) => {
  if (hasUnsaved() || pending.size > 0) {
    e.preventDefault()
    e.returnValue = ''
  }
})
