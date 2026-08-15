import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/cn'
import {
  LayoutDashboard, FlaskConical, CirclePlay,
  FileText, Clock, BarChart2,
  CandlestickChart, Calendar, Settings, ScrollText, LogOut,
  ChevronRight,
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
  { to: '/settings', icon: Settings,    label: 'Settings' },
  { to: '/logs',     icon: ScrollText,  label: 'Logs' },
]

function NavItem({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      className={({ isActive }) => cn(
        'group flex items-center gap-2.5 px-3 py-[6px] mx-1.5 rounded text-[12px] font-medium transition-colors',
        isActive
          ? 'bg-accent-bg text-accent'
          : 'text-muted hover:text-text hover:bg-s2',
      )}
    >
      {({ isActive }) => (
        <>
          <item.icon size={13} strokeWidth={isActive ? 2.5 : 2} />
          <span className="flex-1">{item.label}</span>
          {isActive && <ChevronRight size={10} className="opacity-50" />}
        </>
      )}
    </NavLink>
  )
}

export function Sidebar() {
  return (
    <aside className="flex flex-col w-[186px] min-w-[186px] bg-surface border-r border-border h-full">
      {/* Wordmark */}
      <div className="flex items-center gap-2.5 px-4 h-[48px] border-b border-border shrink-0">
        <div className="w-[26px] h-[26px] rounded bg-accent flex items-center justify-center shrink-0">
          <CandlestickChart size={14} className="text-white" strokeWidth={2.5} />
        </div>
        <div>
          <div className="text-[13px] font-bold text-text tracking-tight leading-none">EdgeLab</div>
          <div className="text-[9px] text-muted uppercase tracking-wider leading-none mt-0.5">Research Terminal</div>
        </div>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 py-2.5 overflow-y-auto scrollbar-thin">
        {groups.map((g) => (
          <div key={g.title} className="mb-1">
            <div className="px-3 py-1 text-[9px] font-semibold uppercase tracking-widest text-muted2 select-none">
              {g.title}
            </div>
            {g.items.map((item) => <NavItem key={item.to} item={item} />)}
          </div>
        ))}
      </nav>

      {/* Bottom items */}
      <div className="border-t border-border py-1.5 shrink-0">
        {bottomItems.map((item) => <NavItem key={item.to} item={item} />)}
        <button
          onClick={async () => {
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
            location.href = '/login'
          }}
          className="w-full flex items-center gap-2.5 px-3 py-[6px] mx-1.5 rounded text-[12px] font-medium text-muted hover:text-red hover:bg-red/5 transition-colors"
          style={{ width: 'calc(100% - 12px)' }}
        >
          <LogOut size={13} strokeWidth={2} />
          Sign Out
        </button>
      </div>
    </aside>
  )
}
