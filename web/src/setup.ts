import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from './api'

// First run: until there's a master profile, every page except Welcome and Settings sends you to Welcome.
let hasProfile: boolean | null = null
const OPEN = ['/welcome', '/settings']

export const markHasProfile = () => { hasProfile = true }

export function useFirstRun() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  useEffect(() => {
    if (hasProfile || OPEN.includes(pathname)) return
    let live = true
    api.setup().then((s) => {
      hasProfile = s.has_profile
      if (live && !s.has_profile) nav('/welcome', { replace: true })
    }).catch(() => {})
    return () => { live = false }
  }, [pathname, nav])
}

/** On the Welcome page: someone who already has a profile goes to it instead. */
export function useLeaveWelcomeIfSetUp() {
  const nav = useNavigate()
  useEffect(() => {
    let live = true
    api.setup().then((s) => {
      hasProfile = s.has_profile
      if (live && s.has_profile) nav('/profile', { replace: true })
    }).catch(() => {})
    return () => { live = false }
  }, [nav])
}
