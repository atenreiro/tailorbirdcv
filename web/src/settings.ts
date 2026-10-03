import { useEffect, useState } from 'react'
import { api, type Settings } from './api'

// Settings are read once per page load and shared; the Settings page refreshes the cache.
let cache: Promise<Settings> | null = null

export function loadSettings(force = false): Promise<Settings> {
  if (force || !cache) cache = api.settings().catch((e) => { cache = null; throw e })
  return cache
}

export const cacheSettings = (s: Settings) => { cache = Promise.resolve(s) }

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
