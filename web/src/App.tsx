import { useEffect, useState } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import Applications from './pages/Applications'
import Funnel from './pages/Funnel'
import NewApplication from './pages/NewApplication'
import Profile from './pages/Profile'
import Settings from './pages/Settings'
import SetupWizard from './pages/setup/SetupWizard'
import UpdateBanner from './pages/UpdateBanner'
import Workspace from './pages/Workspace'
import { cx } from './lib'
import { EngineBadge } from './ui'
import { useFirstRun } from './setup'
import { useUnsavedGuard } from './unsaved'

// The v3 design uses a 1480px frame on every page.
const FRAME = 'max-w-[1480px] px-4 sm:px-7'

/** The brand mark (docs/brand): a tailorbird on a stitched leaf, drawn for the dark masthead. */
function Mark({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="8 14 100 76" className={className}>
      <path d="M12 76 C28 62 66 62 104 72 C88 98 40 102 12 76 Z" fill="#8CCB7A" />
      <path d="M22 80 C44 78 72 80 96 74" fill="none" stroke="#0F3D2E" strokeWidth="1.8" strokeLinecap="round" strokeDasharray="5 4" />
      <path d="M44 52 L30 20 L38 19 L53 47 Z" fill="#F4F7F5" />
      <path d="M42 54 C42 41 54 34 66 37 C77 40 82 50 78 58 C74 65 56 66 47 61 C44 59 42 57 42 54 Z" fill="#F4F7F5" />
      <circle cx="74" cy="34" r="10" fill="#F4F7F5" />
      <path d="M65 31 C66 22 80 22 84 30 C78 27 70 27 65 31 Z" fill="#E4572E" />
      <circle cx="78" cy="33" r="1.8" fill="#0F3D2E" />
      <path d="M83 35 L94 37.5 L83 40 Z" fill="#F2A93B" />
      <path d="M52 52 C58 58 68 58 74 50" fill="none" stroke="#8CCB7A" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M60 63 L60 67 M68 63 L68 67" stroke="#F4F7F5" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/** The logo: the mark + "Tailorbird" in off-white and "CV" in amber (Outfit 600, the dark variant). */
function Logo() {
  return (
    <span aria-hidden="true" className="flex items-center gap-2">
      <Mark className="h-[26px] w-auto" />
      <span className="hidden font-brand text-[21px] font-semibold leading-none tracking-[-0.03em] text-mist min-[400px]:inline">
        Tailorbird<span className="text-amber">CV</span>
      </span>
    </span>
  )
}

function Masthead() {
  const { pathname } = useLocation()
  if (pathname.startsWith('/setup')) {  // the wizard keeps the focus on itself: no app navigation
    return (
      <header className="sticky top-0 z-30 bg-ink text-white">
        <div className={cx('mx-auto flex h-14 items-center gap-4', FRAME)}>
          <span aria-label="TailorbirdCV" className="flex items-center"><Logo /></span>
          <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-[#a3bcb0]">Setup</span>
        </div>
      </header>
    )
  }
  const link = ({ isActive }: { isActive: boolean }) =>
    cx('flex shrink-0 items-center px-1.5 transition-colors sm:px-3', isActive ? 'text-white shadow-[inset_0_-3px_0_var(--color-amber)]' : 'text-[#a3bcb0] hover:text-white')
  return (
    <header className="sticky top-0 z-30 bg-ink text-white">
      <div className={cx('mx-auto flex h-14 items-center gap-3 sm:gap-9', FRAME)}>
        <NavLink to="/" aria-label="TailorbirdCV" className="flex items-center"><Logo /></NavLink>
        <nav className="flex h-full gap-0 overflow-x-auto sm:gap-1 whitespace-nowrap [scrollbar-width:none]">
          <NavLink to="/" end className={link}><span className="sm:hidden">Apps</span><span className="hidden sm:inline">Applications</span></NavLink>
          <NavLink to="/funnel" className={link}>Funnel</NavLink>
          <NavLink to="/new" className={link}>New<span className="hidden sm:inline">&nbsp;tailoring</span></NavLink>
          <NavLink to="/profile" className={link}><span className="hidden sm:inline">Master&nbsp;</span>Profile</NavLink>
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1">
          <EngineBadge />
          <NavLink to="/settings" aria-label="Settings" title="Settings"
            className={({ isActive }) => cx('grid size-8 shrink-0 place-items-center rounded-md transition-colors sm:size-9', isActive ? 'bg-[#1a4d3b] text-white' : 'text-[#a3bcb0] hover:text-white')}>
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
            </svg>
          </NavLink>
        </div>
      </div>
    </header>
  )
}

/** Shown once after the setup wizard: where to start. */
function FirstTip() {
  const [params, setParams] = useSearchParams()
  if (params.get('welcome') !== '1') return null
  return (
    <div role="status" className="animate-rise mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-[#f0c9b9] bg-accent-soft px-4 py-3 text-[14px] text-ink">
      <span className="flex-1"><strong>You’re all set.</strong> Paste a job description in <Link to="/new" className="text-accent hover:text-accent-strong">New tailoring</Link> to make your first tailored resume.</span>
      <button className="text-[13px] text-muted hover:text-ink" onClick={() => setParams({}, { replace: true })}>Dismiss</button>
    </div>
  )
}

/** This browser hasn't been unlocked: the API only answers the browser opened from `tailorbirdcv serve`'s link. */
function useLocked() {
  const [locked, setLocked] = useState(false)
  useEffect(() => {
    const on = () => setLocked(true)
    window.addEventListener('tailorbirdcv:locked', on)
    return () => window.removeEventListener('tailorbirdcv:locked', on)
  }, [])
  return locked
}

function Locked() {
  return (
    <section className="animate-rise mx-auto flex max-w-[640px] flex-col gap-4 py-16 text-center">
      <h1 className="font-display text-[44px] leading-none tracking-[-0.02em] text-ink">Open TailorbirdCV from its link</h1>
      <p className="text-[15px] leading-[1.6] text-body text-pretty">
        To keep your resume data private from other programs on this computer, TailorbirdCV only answers the browser
        opened from the link it prints when it starts. Look in the terminal where you ran
        <code className="mx-1 rounded bg-wash px-1.5 font-mono text-[13px]">tailorbirdcv serve</code>
        for the line starting with <span className="font-mono text-[13px]">TailorbirdCV →</span> and open that link. You only need to do this once per browser.
      </p>
    </section>
  )
}

export default function App() {
  useUnsavedGuard()
  useFirstRun()
  const locked = useLocked()
  if (locked) return <><Masthead /><main className={cx('mx-auto pb-24 pt-10', FRAME)}><Locked /></main></>
  return (
    <>
      <Masthead />
      <main className={cx('mx-auto pb-24 pt-10', FRAME)}>
        <UpdateBanner />
        <FirstTip />
        <Routes>
          <Route path="/" element={<Applications />} />
          <Route path="/funnel" element={<Funnel />} />
          <Route path="/new" element={<NewApplication />} />
          <Route path="/a/:id" element={<Workspace />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/setup" element={<SetupWizard />} />
          <Route path="/welcome" element={<Navigate to="/setup" replace />} />
        </Routes>
      </main>
    </>
  )
}
