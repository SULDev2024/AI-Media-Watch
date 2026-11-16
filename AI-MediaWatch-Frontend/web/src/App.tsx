import { useState, useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Nav } from './components/Nav'

import { LoginPage } from './routes/LoginPage'

import { OverviewPage } from './routes/OverviewPage'
import { TopBar } from './components/TopBar'
import { queryClient } from './lib/queryClient'

const QueuePage = lazy(() => import('./routes/QueuePage').then(module => ({ default: module.QueuePage })))
const AnalyzePage = lazy(() => import('./routes/AnalyzePage').then(module => ({ default: module.AnalyzePage })))
const ReportPage = lazy(() => import('./routes/ReportPage').then(module => ({ default: module.ReportPage })))
const GraphPage = lazy(() => import('./routes/GraphPage').then(module => ({ default: module.GraphPage })))
const MetricsPage = lazy(() => import('./routes/MetricsPage').then(module => ({ default: module.MetricsPage })))
const FeedbackLogPage = lazy(() => import('./routes/FeedbackLogPage').then(module => ({ default: module.FeedbackLogPage })))
const ValidationPage = lazy(() => import('./routes/ValidationPage').then(module => ({ default: module.ValidationPage })))
const AnalyticsPage = lazy(() => import('./routes/AnalyticsPage').then(module => ({ default: module.AnalyticsPage })))
const CasePage = lazy(() => import('./routes/CasePage').then(module => ({ default: module.CasePage })))
const InvestigatePage = lazy(() => import('./routes/InvestigatePage').then(module => ({ default: module.InvestigatePage })))
const BiometricsPage = lazy(() => import('./routes/BiometricsPage').then(module => ({ default: module.BiometricsPage })))
const AgentsPage = lazy(() => import('./routes/AgentsPage').then(module => ({ default: module.AgentsPage })))

function getStoredAuth() {
  const token = localStorage.getItem('aimw_token')
  const email = localStorage.getItem('aimw_email')
  const role = localStorage.getItem('aimw_role')
  return token ? { token, email: email || '', role: role || 'analyst' } : null
}

export default function App() {
  const [auth, setAuth] = useState(getStoredAuth)
  const [dark, setDark] = useState(() => localStorage.getItem('aimw_dark') === '1')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('aimw_dark', dark ? '1' : '0')
  }, [dark])

  const handleLogin = (token: string, email: string, role: string) => {
    localStorage.setItem('aimw_token', token)
    localStorage.setItem('aimw_email', email)
    localStorage.setItem('aimw_role', role)
    setAuth({ token, email, role })
  }

  const handleLogout = () => {
    queryClient.clear()
    localStorage.removeItem('aimw_token')
    localStorage.removeItem('aimw_email')
    localStorage.removeItem('aimw_role')
    setAuth(null)
  }

  if (!auth) {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div className={`flex h-screen overflow-hidden ${dark ? 'bg-gray-950' : 'bg-gray-50'}`}>
        <Nav dark={dark} onToggleDark={() => setDark(!dark)} email={auth.email} onLogout={handleLogout} />
        <main className="app-main flex-1 overflow-auto">
          <TopBar />
          <Suspense fallback={<div className="workspace-loading" role="status">Loading workspace...</div>}>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/queue" element={<QueuePage />} />
            <Route path="/analyze" element={<AnalyzePage />} />
            <Route path="/report/:id" element={<ReportPage />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/feedback-log" element={<FeedbackLogPage />} />
            <Route path="/validation" element={<ValidationPage />} />
            <Route path="/cases/:id" element={<CasePage />} />
            <Route path="/investigate" element={<InvestigatePage />} />
            <Route path="/biometrics" element={<BiometricsPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  )
}
