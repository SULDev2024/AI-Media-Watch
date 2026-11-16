import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { LayoutDashboard, LayoutList, GitFork, BarChart2, MessageSquare, Shield, FlaskConical, ScanSearch, PieChart, LogOut, Moon, Sun, Menu, X, Users, Scan, Bot, ArrowUpRight } from 'lucide-react'
import { clsx } from 'clsx'

const groups = [
  { label: 'WORKSPACE', links: [
    { to: '/', label: 'Overview', Icon: LayoutDashboard },
    { to: '/queue', label: 'Detection queue', Icon: LayoutList },
    { to: '/analyze', label: 'Analyze content', Icon: ScanSearch },
    { to: '/investigate', label: 'Investigations', Icon: Users },
  ] },
  { label: 'INTELLIGENCE', links: [
    { to: '/agents', label: 'Agent workspace', Icon: Bot },
    { to: '/graph', label: 'Network graph', Icon: GitFork },
    { to: '/biometrics', label: 'Biometrics', Icon: Scan },
    { to: '/analytics', label: 'Analytics', Icon: PieChart },
  ] },
  { label: 'QUALITY & AUDIT', links: [
    { to: '/metrics', label: 'Model performance', Icon: BarChart2 },
    { to: '/validation', label: 'Validation', Icon: FlaskConical },
    { to: '/feedback-log', label: 'Feedback log', Icon: MessageSquare },
  ] },
]

interface NavProps { dark: boolean; onToggleDark: () => void; email: string; onLogout: () => void }

export function Nav({ dark, onToggleDark, email, onLogout }: NavProps) {
  const [open, setOpen] = useState(false)
  return <>
    <button className="mobile-menu" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <X size={20} /> : <Menu size={20} />}</button>
    {open && <div className="nav-overlay" onClick={() => setOpen(false)} />}
    <aside className={clsx('app-sidebar', open && 'is-open')}>
      <NavLink to="/" className="brand" onClick={() => setOpen(false)}><span className="brand-mark"><Shield size={23} strokeWidth={1.7} /></span><span>MediaWatch<span className="brand-sub">INTELLIGENCE PLATFORM</span></span><span className="brand-ai">AI</span></NavLink>
      <div className="workspace-label"><span className="workspace-avatar">M</span><span>Intelligence workspace<small>Analyst console</small></span></div>
      <nav className="sidebar-navigation" aria-label="Main navigation">{groups.map(group => <div className="nav-group" key={group.label}><p>{group.label}</p>{group.links.map(({ to, label, Icon }) => <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)} className={({ isActive }) => clsx('nav-item', isActive && 'active')}><Icon size={18} strokeWidth={1.65} /><span>{label}</span></NavLink>)}</div>)}</nav>
      <div className="sidebar-bottom"><NavLink to="/analyze" className="sidebar-callout" onClick={() => setOpen(false)}><Shield size={20} /><strong>Evidence over assumptions.</strong><span>Start your next analysis <ArrowUpRight size={14} /></span></NavLink>
        <button className="theme-toggle" onClick={onToggleDark}>{dark ? <Sun size={16} /> : <Moon size={16} />}{dark ? 'Light appearance' : 'Dark appearance'}</button>
        <div className="account"><span className="account-avatar">{email.charAt(0).toUpperCase()}</span><span className="account-details"><strong>{email.split('@')[0]}</strong><small title={email}>{email}</small></span><button onClick={onLogout} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button></div>
      </div>
    </aside>
  </>
}
