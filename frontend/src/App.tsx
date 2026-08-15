import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { Login } from './pages/Login'
import { Dashboard } from './pages/Dashboard'
import { Research } from './pages/Research'
import { JobQueue } from './pages/JobQueue'
import { JobDetail } from './pages/JobDetail'
import { Reports } from './pages/Reports'
import { History } from './pages/History'
import { Strategies } from './pages/Strategies'
import { Scheduler } from './pages/Scheduler'
import { Logs } from './pages/Logs'
import { Settings } from './pages/Settings'
import { PaperTrading } from './pages/PaperTrading'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard"    element={<Dashboard />} />
          <Route path="/research"     element={<Research />} />
          <Route path="/jobs"         element={<JobQueue />} />
          <Route path="/jobs/:id"     element={<JobDetail />} />
          <Route path="/reports"      element={<Reports />} />
          <Route path="/history"      element={<History />} />
          <Route path="/strategies"   element={<Strategies />} />
          <Route path="/scheduler"    element={<Scheduler />} />
          <Route path="/paper-trading" element={<PaperTrading />} />
          <Route path="/logs"         element={<Logs />} />
          <Route path="/settings"     element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
