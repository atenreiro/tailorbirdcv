// Tracks unsaved work across the app and guards navigation away from it.
const dirty = new Set<string>()

export function setUnsaved(key: string, on: boolean) {
  if (on) dirty.add(key)
  else dirty.delete(key)
}

export function hasUnsaved() {
  return dirty.size > 0
}

/** Ask before leaving with unsaved work. Returns true when it's OK to leave. */
export function confirmLeave(): boolean {
  if (!hasUnsaved()) return true
  const ok = window.confirm('You have unsaved edits. Leave and discard them?')
  if (ok) dirty.clear()
  return ok
}

window.addEventListener('beforeunload', (e) => {
  if (hasUnsaved()) {
    e.preventDefault()
    e.returnValue = ''
  }
})
