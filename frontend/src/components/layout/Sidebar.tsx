import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/cn'
import {
  LayoutDashboard, FlaskConical, CirclePlay,
  FileText, Clock, BarChart2,
  CandlestickChart, Calendar, Settings, ScrollText, LogOut,
} from 'lucide-react'

interface NavItem {
  to: string
  icon: React.ElementType
  label: string
}

const groups: { title: string; items: NavItem[] }[] = [
  {
    title: 'Research',
    items: [
      { to: '/dashboard',  icon: LayoutDashboard, label: 'Dashboard' },
      { to: '/research',   icon: FlaskConical,    label: 'New Run' },
      { to: '/jobs',       icon: CirclePlay,      label: 'Jobs' },
    ],
  },
  {
    title: 'Results',
    items: [
      { to: '/reports',    icon: FileText,   label: 'Reports' },
      { to: '/history',    icon: Clock,      label: 'History' },
      { to: '/strategies', icon: BarChart2,  label: 'Strategies' },
    ],
  },
  {
    title: 'Trading',
    items: [
      { to: '/paper-trading', icon: CandlestickChart, label: 'Paper Trading' },
      { to: '/scheduler',     icon: Calendar,          label: 'Scheduler' },
    ],
  },
]

const bottomItems: NavItem[] = [
  { to: '/settings', icon: Settings,   label: 'Settings' },
  { to: '/logs',     icon: ScrollText, label: 'Logs' },
]

function NavRow({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      className={({ isActive }) => cn(
        'flex items-center gap-2 px-3 py-[5px] text-[11px] font-medium transition-colors border-l-2',
        isActive
          ? 'border-l-accent text-accent bg-accent-bg'
          : 'border-l-transparent text-muted hover:text-text hover:bg-s2',
      )}
    >
      {({ isActive }) => (
        <>
          <item.icon size={12} strokeWidth={isActive ? 2.5 : 1.8} className="shrink-0" />
          <span>{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

export function Sidebar() {
  return (
    <aside className="flex flex-col w-[162px] min-w-[162px] bg-surface border-r border-border h-full">
      {/* Wordmark */}
      <div className="flex items-center gap-2 px-3 h-10 border-b border-border shrink-0">
        <CandlestickChart size={13} className="text-accent shrink-0" strokeWidth={2} />
        <div>
          <div className="text-[12px] font-bold text-text leading-none tracking-tight">EdgeLab</div>
          <div className="text-[8px] text-muted uppercase tracking-widest leading-none mt-0.5">Research Terminal</div>
        </div>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 py-2 overflow-y-auto scrollbar-thin">
        {groups.map((g) => (
          <div key={g.title} className="mb-1">
            <div className="px-3 pt-2 pb-1 text-[8px] font-semibold uppercase tracking-widest text-muted2 select-none">
              {g.title}
            </div>
            {g.items.map((item) => <NavRow key={item.to} item={item} />)}
          </div>
        ))}
      </nav>

      {/* Bottom items */}
      <div className="border-t border-border py-1 shrink-0">
        {bottomItems.map((item) => <NavRow key={item.to} item={item} />)}
        <button
          onClick={async () => {
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
            location.href = '/login'
          }}
          className="w-full flex items-center gap-2 px-3 py-[5px] border-l-2 border-l-transparent text-[11px] font-medium text-muted hover:text-red hover:bg-red/5 transition-colors"
        >
          <LogOut size={12} strokeWidth={1.8} className="shrink-0" />
          Sign Out
        </button>
      </div>
    </aside>
  )
}
