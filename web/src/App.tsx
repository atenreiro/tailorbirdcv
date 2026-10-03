import { NavLink, Route, Routes } from 'react-router-dom'
import Applications from './pages/Applications'
import Funnel from './pages/Funnel'
import NewApplication from './pages/NewApplication'
import Profile from './pages/Profile'
import Workspace from './pages/Workspace'
import { cx } from './lib'
import { EngineBadge } from './ui'
import { useUnsavedGuard } from './unsaved'

// The v3 design uses a 1480px frame on every page.
const FRAME = 'max-w-[1480px] px-4 sm:px-7'

/** The wordmark: "auto" condensed bold + "[cv]" in mono. */
function Logo() {
  return (
    <span aria-hidden="true" className="flex items-baseline text-[22px] leading-none text-white">
      <span className="font-bold [font-stretch:75%]">auto</span>
      <span className="font-mono text-[20px] font-medium tracking-[-0.04em] text-[#7d93ff]">[cv]</span>
    </span>
  )
}

function Masthead() {
  const link = ({ isActive }: { isActive: boolean }) =>
    cx('flex shrink-0 items-center px-1.5 transition-colors sm:px-3', isActive ? 'text-white shadow-[inset_0_-3px_0_#4d6bff]' : 'text-[#9aa3b5] hover:text-white')
  return (
    <header className="sticky top-0 z-30 bg-ink text-white">
      <div className={cx('mx-auto flex h-14 items-center gap-3 sm:gap-9', FRAME)}>
        <NavLink to="/" aria-label="AutoCV" className="flex items-center"><Logo /></NavLink>
        <nav className="flex h-full gap-0 overflow-x-auto sm:gap-1 whitespace-nowrap [scrollbar-width:none]">
          <NavLink to="/" end className={link}><span className="sm:hidden">Apps</span><span className="hidden sm:inline">Applications</span></NavLink>
          <NavLink to="/funnel" className={link}>Funnel</NavLink>
          <NavLink to="/new" className={link}>New<span className="hidden sm:inline">&nbsp;tailoring</span></NavLink>
          <NavLink to="/profile" className={link}><span className="hidden sm:inline">Master&nbsp;</span>Profile</NavLink>
        </nav>
        <div className="ml-auto"><EngineBadge /></div>
      </div>
    </header>
  )
}

export default function App() {
  useUnsavedGuard()
  return (
    <>
      <Masthead />
      <main className={cx('mx-auto pb-24 pt-10', FRAME)}>
        <Routes>
          <Route path="/" element={<Applications />} />
          <Route path="/funnel" element={<Funnel />} />
          <Route path="/new" element={<NewApplication />} />
          <Route path="/a/:id" element={<Workspace />} />
          <Route path="/profile" element={<Profile />} />
        </Routes>
      </main>
    </>
  )
}
