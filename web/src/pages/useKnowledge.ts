import { useEffect, useState } from 'react'
import { api, type Knowledge } from '../api'
import { setUnsaved } from '../unsaved'

/** Answers & style preferences (knowledge.yaml), edited locally and saved by the page's save dock. */
export function useKnowledge() {
  const [saved, setSaved] = useState<Knowledge | null>(null)
  const [k, setK] = useState<Knowledge | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = () => api.knowledge().then((x) => { setSaved(x); setK(structuredClone(x)) }).catch((e) => setError(e.message))
  useEffect(() => { void load() }, [])
  const dirty = !!k && JSON.stringify(k) !== JSON.stringify(saved)
  useEffect(() => { setUnsaved('knowledge', dirty) }, [dirty])
  useEffect(() => () => setUnsaved('knowledge', false), [])
  /** Returns false (with `error` set) when the save failed. */
  const save = async () => {
    setError(null)
    try {
      const x = await api.saveKnowledge(k!); setSaved(x); setK(structuredClone(x))
      return true
    } catch (e) {
      const conflict = (e as { status?: number }).status === 409
      setError(conflict ? 'Your answers/preferences changed elsewhere since this page loaded. Reload to get the latest, then re-apply your edit.' : (e as Error).message)
      // Reloading replaces the local copy (and its version); declining keeps the edits, and every
      // later save is refused the same way, so a stale copy never overwrites the newer file.
      if (conflict && window.confirm('Reload the latest answers/preferences now? Unsaved edits here will be discarded.')) void load().then(() => setError(null))
      return false
    }
  }
  return { k, setK, dirty, save, load, error, setError, discard: () => setK(structuredClone(saved)) }
}
