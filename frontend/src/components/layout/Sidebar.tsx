import { NavLink } from 'react-router-dom'
import { useState } from 'react'
import { cn } from '../../lib/cn'
import {
  LayoutDashboard, FlaskConical, BarChart2, CandlestickChart,
  Calendar, ScrollText, Settings, LogOut,
} from 'lucide-react'

interface NavItem {
  to: string
  icon: React.ElementType
  label: string
  exact?: boolean
}

const primary: NavItem[] = [
  { to: '/dashboard',     icon: LayoutDashboard, label: 'Home',       exact: true },
  { to: '/research',      icon: FlaskConical,    label: 'Research' },
  { to: '/strategies',    icon: BarChart2,       label: 'Strategies' },
  { to: '/paper-trading', icon: CandlestickChart,label: 'Trade' },
]

const system: NavItem[] = [
  { to: '/scheduler', icon: Calendar,    label: 'Scheduler' },
  { to: '/logs',      icon: ScrollText,  label: 'Logs' },
  { to: '/settings',  icon: Settings,    label: 'Settings' },
]

function Tip({ label }: { label: string }) {
  return (
    <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 z-[60] pointer-events-none animate-fade-in">
      <div className="bg-s3 border border-border2 text-text text-xs font-medium px-2.5 py-1.5 rounded-md whitespace-nowrap shadow-xl">
        {label}
      </div>
    </div>
  )
}

function RailItem({ item }: { item: NavItem }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      className="relative"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <NavLink
        to={item.to}
        end={item.exact}
        aria-label={item.label}
        className={({ isActive }) => cn(
          'flex items-center justify-center w-full h-[52px] transition-colors relative',
          isActive
            ? 'text-accent bg-accent-bg'
            : 'text-muted hover:text-text hover:bg-s2',
        )}
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 bg-accent rounded-r-full" />
            )}
            <item.icon
              size={19}
              strokeWidth={isActive ? 2.5 : 1.8}
              className="shrink-0"
            />
          </>
        )}
      </NavLink>
      {hover && <Tip label={item.label} />}
    </div>
  )
}

export function Sidebar() {
  const [signOutHover, setSignOutHover] = useState(false)

  return (
    <aside className="flex flex-col w-[52px] min-w-[52px] bg-surface border-r border-border h-full select-none">
      {/* Wordmark */}
      <div className="flex items-center justify-center h-[52px] border-b border-border shrink-0">
        <span className="text-accent font-bold text-xl font-mono leading-none">E</span>
      </div>

      {/* Primary nav */}
      <nav className="flex flex-col flex-1 pt-1" aria-label="Main navigation">
        {primary.map(item => <RailItem key={item.to} item={item} />)}
      </nav>

      {/* System nav + sign out */}
      <div className="border-t border-border py-1 shrink-0" aria-label="System navigation">
        {system.map(item => <RailItem key={item.to} item={item} />)}

        <div
          className="relative"
          onMouseEnter={() => setSignOutHover(true)}
          onMouseLeave={() => setSignOutHover(false)}
        >
          <button
            onClick={async () => {
              await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
              location.href = '/login'
            }}
            aria-label="Sign out"
            className="flex items-center justify-center w-full h-[52px] text-muted hover:text-red hover:bg-red/5 transition-colors"
          >
            <LogOut size={19} strokeWidth={1.8} />
          </button>
          {signOutHover && <Tip label="Sign Out" />}
        </div>
      </div>
    </aside>
  )
}
