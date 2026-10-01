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

function Masthead() {
  const guard = (e: { preventDefault(): void }) => { if (!confirmLeave()) e.preventDefault() }
  const link = ({ isActive }: { isActive: boolean }) =>
    cx('relative shrink-0 py-1 text-sm transition-colors', isActive ? 'text-ink after:absolute after:inset-x-0 after:-bottom-[13px] after:h-0.5 after:bg-rust' : 'text-muted hover:text-ink')
  return (
    <header className="sticky top-0 z-30 border-b border-rule bg-paper/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:gap-8 sm:px-6">
        <NavLink to="/" onClick={guard} className="flex items-baseline gap-2">
          <span className="font-serif text-2xl italic text-ink">AutoCV</span>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.2em] text-faint lg:inline">fact-locked tailoring</span>
        </NavLink>
        <nav className="flex gap-4 whitespace-nowrap sm:gap-6">
          <NavLink to="/" end onClick={guard} className={link}><span className="sm:hidden">Apps</span><span className="hidden sm:inline">Applications</span></NavLink>
          <NavLink to="/new" onClick={guard} className={link}>New<span className="hidden sm:inline"> tailoring</span></NavLink>
          <NavLink to="/profile" onClick={guard} className={link}><span className="hidden sm:inline">Master </span>Profile</NavLink>
        </nav>
        <div className="ml-auto"><EngineBadge /></div>
      </div>
    </header>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Masthead />
      <main className="mx-auto max-w-6xl px-4 pb-24 pt-10 sm:px-6">
        <Routes>
          <Route path="/" element={<Applications />} />
          <Route path="/new" element={<NewApplication />} />
          <Route path="/a/:id" element={<Workspace />} />
          <Route path="/profile" element={<Profile />} />
        </Routes>
      </main>
    </BrowserRouter>
  </StrictMode>,
)
