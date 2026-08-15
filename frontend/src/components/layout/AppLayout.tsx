import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

export function AppLayout() {
  return (
    <div className="flex h-full bg-bg">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-y-auto scrollbar-thin">
        <Outlet />
      </main>
    </div>
  )
}
