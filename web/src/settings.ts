import { useEffect, useState } from 'react'
import { api, type Platform, type Settings } from './api'

// Settings are read once per page load and shared; the Settings page refreshes the cache.
let cache: Promise<Settings> | null = null

export function loadSettings(force = false): Promise<Settings> {
  if (force || !cache) cache = api.settings().catch((e) => { cache = null; throw e })
  return cache
}

/** Store fresh settings and tell anything showing engine status (header badge, system check) to refresh. */
export const cacheSettings = (s: Settings) => {
  cache = Promise.resolve(s)
  window.dispatchEvent(new Event('autocv:settings'))
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings | null>(null)
  useEffect(() => {
    let live = true
    loadSettings().then((s) => { if (live) setSettings(s) }).catch(() => {})
    return () => { live = false }
  }, [])
  return settings
}

/** The app that will make the PDF ("Microsoft Word", "LibreOffice"), once known. */
export const pdfEngineName = (s: Settings | null) => s?.pdf_engines.find((e) => e.id === s.pdf_effective)?.name

/** Platform wording: "this Mac" vs "this computer", Finder vs File Explorer. */
export const thisComputer = (p?: Platform) => (p === 'macos' ? 'this Mac' : 'this computer')
export const showInFolder = (p?: Platform) =>
  p === 'macos' ? 'Show in Finder' : p === 'windows' ? 'Show in File Explorer' : 'Show in folder'
export const fileManager = (p?: Platform) =>
  p === 'macos' ? 'Finder' : p === 'windows' ? 'File Explorer' : 'your file manager'

/** The page limit from Settings → Your targets (2 until settings load). */
export const pageLimit = (s: Settings | null) => s?.targets?.pages ?? 2
export const pagesText = (n: number) => `${n} page${n === 1 ? '' : 's'}`
