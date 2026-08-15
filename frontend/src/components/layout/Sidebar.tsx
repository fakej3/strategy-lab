import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/cn'
import {
  LayoutDashboard, FlaskConical, Loader, FileText,
  Clock, BarChart2, CandlestickChart, Calendar,
  Settings, ScrollText, LogOut,
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
      { to: '/',          icon: LayoutDashboard,  label: 'Dashboard' },
      { to: '/research',  icon: FlaskConical,      label: 'New Run' },
      { to: '/jobs',      icon: Loader,            label: 'Running Jobs' },
    ],
  },
  {
    title: 'Results',
    items: [
      { to: '/reports',    icon: FileText,    label: 'Reports' },
      { to: '/history',    icon: Clock,       label: 'History' },
      { to: '/strategies', icon: BarChart2,   label: 'Strategies' },
    ],
  },
  {
    title: 'Trading',
    items: [
      { to: '/bot', icon: CandlestickChart, label: 'Paper Trading' },
    ],
  },
  {
    title: 'Automation',
    items: [
      { to: '/scheduler', icon: Calendar, label: 'Scheduler' },
    ],
  },
]

export function Sidebar() {
  return (
    <aside className="flex flex-col w-[190px] min-w-[190px] bg-surface border-r border-border h-full overflow-y-auto scrollbar-thin">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-accent/20 flex items-center justify-center">
            <CandlestickChart size={14} className="text-accent" />
          </div>
          <div>
            <div className="text-[12px] font-bold text-text leading-none">EDGELAB</div>
            <div className="text-[9px] text-muted uppercase tracking-wider leading-none mt-0.5">Research Engine</div>
          </div>
        </div>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 py-2">
        {groups.map((g) => (
          <div key={g.title} className="mb-1">
            <div className="px-3 py-1.5 text-[9px] font-semibold uppercase tracking-widest text-muted2">
              {g.title}
            </div>
            {g.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) => cn(
                  'flex items-center gap-2.5 px-3 py-1.5 mx-1 rounded text-[12px] transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent'
                    : 'text-muted hover:text-text hover:bg-s2',
                )}
              >
                <item.icon size={14} />
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Bottom links */}
      <div className="border-t border-border py-2">
        {[
          { to: '/settings', icon: Settings, label: 'Settings' },
          { to: '/logs',     icon: ScrollText, label: 'Logs' },
        ].map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => cn(
              'flex items-center gap-2.5 px-3 py-1.5 mx-1 rounded text-[12px] transition-colors',
              isActive ? 'bg-accent/10 text-accent' : 'text-muted hover:text-text hover:bg-s2',
            )}
          >
            <item.icon size={14} />
            {item.label}
          </NavLink>
        ))}
        <a
          href="/api/auth/logout"
          onClick={async (e) => {
            e.preventDefault()
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
            location.href = '/login'
          }}
          className="flex items-center gap-2.5 px-3 py-1.5 mx-1 rounded text-[12px] text-muted hover:text-red hover:bg-red/5 transition-colors"
        >
          <LogOut size={14} />
          Sign Out
        </a>
      </div>
    </aside>
  )
}
