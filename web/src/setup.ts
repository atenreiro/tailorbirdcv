import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from './api'

// First run: until the setup wizard is finished (a profile exists and setup is completed), every page
// except the wizard and Settings sends you to /setup.
let ready: boolean | null = null

export const markSetupDone = () => { ready = true }

if (typeof window !== 'undefined') {
  // The server said there's no profile (e.g. the data folder changed): check again on the next page.
  window.addEventListener('tailorbirdcv:no-profile', () => { ready = null })
}

export function useFirstRun() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  useEffect(() => {
    if (ready || pathname.startsWith('/setup') || pathname === '/settings') return
    let live = true
    api.setup().then((s) => {
      ready = s.has_profile && s.completed
      if (live && !ready) nav('/setup', { replace: true })
    }).catch(() => {})
    return () => { live = false }
  }, [pathname, nav])
}
