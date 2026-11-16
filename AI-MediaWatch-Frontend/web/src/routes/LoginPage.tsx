import { useState } from 'react'
import { Shield, Loader2, Eye, EyeOff, ArrowRight, Fingerprint, GitFork, FileCheck2, LockKeyhole } from 'lucide-react'

interface LoginPageProps {
  onLogin: (token: string, email: string, role: string) => void
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${BASE}/api/v1/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Sign-in failed. Please check your credentials.')
        return
      }
      const data = await res.json()
      onLogin(data.access_token, data.email, data.role)
    } catch {
      setError('Cannot connect to the API. Start the backend and try again.')
    } finally {
      setLoading(false)
    }
  }

  return <div className="login-shell">
    <section className="login-story">
      <div className="brand"><span className="brand-mark"><Shield size={24} /></span><span>MediaWatch<span className="brand-sub">INTELLIGENCE PLATFORM</span></span></div>
      <div className="login-story-content page-enter"><span className="eyebrow">CLARITY IN A WORLD OF NOISE</span><h1>Behind every signal,<br />a story worth<br />investigating.</h1><p>Turn complex media into clear, actionable intelligence. Detect financial fraud with evidence you can follow.</p>
        <div className="login-feature"><Fingerprint size={20} />Multimodal content analysis</div><div className="login-feature"><GitFork size={20} />Connected campaign intelligence</div><div className="login-feature"><FileCheck2 size={20} />Traceable evidence and audit trails</div>
      </div><span className="login-story-footer">AI MEDIAWATCH / EVIDENCE-FIRST INTELLIGENCE</span>
    </section>
    <section className="login-panel"><div className="login-form page-enter"><span className="eyebrow">YOUR INTELLIGENCE WORKSPACE</span><h2>Welcome back.</h2><p className="login-intro">Sign in to see the bigger picture.</p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="login-email">Work email</label><input id="login-email" name="email" type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required placeholder="you@organization.com" />
        <label htmlFor="login-password">Password</label><div className="password-field"><input id="login-password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="Enter your password" /><button type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>
        {error && <p role="alert" className="mt-4 text-xs text-red-600">{error}</p>}
        <button type="submit" disabled={loading} className="button-primary">{loading ? <><Loader2 size={16} className="animate-spin" />Signing in…</> : <>Sign in to workspace<ArrowRight size={16} /></>}</button>
      </form>
      <p className="login-assurance"><LockKeyhole size={13} />Access restricted to authorized analysts</p><p className="login-help">Need access? Contact your workspace administrator.<br />Use the account configured in your backend environment.</p>
    </div></section>
  </div>
}
