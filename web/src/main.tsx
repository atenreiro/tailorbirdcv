import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import './index.css'
import Applications from './pages/Applications'
import NewApplication from './pages/NewApplication'
import Profile from './pages/Profile'
import Workspace from './pages/Workspace'
import { cx, EngineBadge } from './ui'
import { confirmLeave } from './unsaved'

// The v3 design uses a 1480px frame on every page.
const FRAME = 'max-w-[1480px] px-4 sm:px-7'

/** The wordmark: "auto" condensed bold + "[cv]" in mono. */
function Logo() {
  return (
    <span aria-label="AutoCV" className="flex items-baseline text-[22px] leading-none text-white">
      <span className="font-bold [font-stretch:75%]">auto</span>
      <span className="font-mono text-[20px] font-medium tracking-[-0.04em] text-[#7d93ff]">[cv]</span>
    </span>
  )
}

function Masthead() {
  const guard = (e: { preventDefault(): void }) => { if (!confirmLeave()) e.preventDefault() }
  const link = ({ isActive }: { isActive: boolean }) =>
    cx('flex shrink-0 items-center px-2 transition-colors sm:px-3', isActive ? 'text-white shadow-[inset_0_-3px_0_#4d6bff]' : 'text-[#9aa3b5] hover:text-white')
  return (
    <header className="sticky top-0 z-30 bg-ink text-white">
      <div className={cx('mx-auto flex h-14 items-center gap-4 sm:gap-9', FRAME)}>
        <NavLink to="/" onClick={guard} className="flex items-center"><Logo /></NavLink>
        <nav className="flex h-full gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
          <NavLink to="/" end onClick={guard} className={link}><span className="sm:hidden">Apps</span><span className="hidden sm:inline">Applications</span></NavLink>
          <NavLink to="/new" onClick={guard} className={link}>New<span className="hidden sm:inline">&nbsp;tailoring</span></NavLink>
          <NavLink to="/profile" onClick={guard} className={link}><span className="hidden sm:inline">Master&nbsp;</span>Profile</NavLink>
        </nav>
        <div className="ml-auto"><EngineBadge /></div>
      </div>
    </header>
  )
}

function Shell() {
  return (
    <>
      <Masthead />
      <main className={cx('mx-auto pb-24 pt-10', FRAME)}>
        <Routes>
          <Route path="/" element={<Applications />} />
          <Route path="/new" element={<NewApplication />} />
          <Route path="/a/:id" element={<Workspace />} />
          <Route path="/profile" element={<Profile />} />
        </Routes>
      </main>
    </>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </StrictMode>,
)
