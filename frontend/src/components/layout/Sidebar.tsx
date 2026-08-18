import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/cn'
import {
  LayoutDashboard, FlaskConical, FileText, BarChart2, CandlestickChart,
  Calendar, ScrollText, Settings, LogOut,
} from 'lucide-react'

interface NavItem {
  to: string
  icon: React.ElementType
  label: string
  exact?: boolean
}

const primary: NavItem[] = [
  { to: '/dashboard',     icon: LayoutDashboard,  label: 'Home',       exact: true },
  { to: '/research',      icon: FlaskConical,     label: 'Research' },
  { to: '/jobs',          icon: FileText,         label: 'Jobs' },
  { to: '/strategies',    icon: BarChart2,        label: 'Strategies' },
  { to: '/paper-trading', icon: CandlestickChart, label: 'Trade' },
]

const system: NavItem[] = [
  { to: '/scheduler', icon: Calendar,   label: 'Scheduler' },
  { to: '/logs',      icon: ScrollText, label: 'Logs' },
  { to: '/settings',  icon: Settings,   label: 'Settings' },
]

function SideNavItem({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.exact}
      className={({ isActive }) => cn(
        'relative flex items-center gap-3 px-3 py-2.5 mx-2 rounded-lg text-sm font-medium transition-colors',
        isActive
          ? 'text-accent bg-accent-bg'
          : 'text-muted hover:text-text hover:bg-s2',
      )}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-accent rounded-r-full" />
          )}
          <item.icon
            size={17}
            strokeWidth={isActive ? 2.5 : 1.8}
            className="shrink-0"
          />
          <span>{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

export function Sidebar() {
  return (
    <aside className="flex flex-col w-[220px] min-w-[220px] bg-surface border-r border-border h-full select-none">
      {/* Wordmark */}
      <div className="flex items-center h-[52px] px-5 border-b border-border shrink-0">
        <span className="font-bold text-xl font-mono leading-none tracking-tight">
          <span className="text-accent">E</span>
          <span className="text-text">dgelab</span>
        </span>
      </div>

      {/* Primary nav */}
      <nav className="flex flex-col flex-1 pt-2 gap-0.5 overflow-y-auto scrollbar-thin" aria-label="Main navigation">
        {primary.map(item => <SideNavItem key={item.to} item={item} />)}
      </nav>

      {/* System nav + sign out */}
      <div className="border-t border-border pb-2 shrink-0" aria-label="System navigation">
        <div className="text-[10px] font-semibold tracking-widest text-muted2 px-5 mb-1 mt-3">
          SYSTEM
        </div>
        <div className="flex flex-col gap-0.5">
          {system.map(item => <SideNavItem key={item.to} item={item} />)}
        </div>

        <button
          onClick={async () => {
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
            location.href = '/login'
          }}
          className="flex items-center gap-3 px-3 py-2.5 mx-2 w-[calc(100%-16px)] rounded-lg text-sm font-medium text-muted hover:text-red hover:bg-red/5 transition-colors mt-0.5"
        >
          <LogOut size={17} strokeWidth={1.8} className="shrink-0" />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  )
}
