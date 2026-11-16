import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Activity, ArrowRight, ArrowUpRight, ShieldAlert, ScanLine, Layers3, Clock3, RefreshCw, GitFork, FileSearch, AlertCircle, ShieldCheck } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { fmtDate, riskBadge } from '../lib/format'

export function OverviewPage() {
  const { data, isLoading, isError, isFetching, refetch } = useQuery({ queryKey: qk.videos(200), queryFn: () => api.videos.list(200), refetchInterval: 30_000 })
  const items = data?.items ?? []
  const threats = items.filter(v => v.level === 'HIGH' || v.level === 'CRITICAL')
  const pending = items.filter(v => v.level == null && v.score == null)
  const platforms = [...new Set(items.map(v => v.platform))]
  const daily = new Map<string, { date: string; analyzed: number; threats: number }>()
  for (const v of items) {
    const date = v.collected_at.slice(0, 10)
    const row = daily.get(date) ?? { date, analyzed: 0, threats: 0 }
    row.analyzed++
    if (v.level === 'HIGH' || v.level === 'CRITICAL') row.threats++
    daily.set(date, row)
  }
  const chart = [...daily.values()].sort((a, b) => a.date.localeCompare(b.date)).slice(-14)
  const recent = [...items].sort((a, b) => new Date(b.collected_at).getTime() - new Date(a.collected_at).getTime()).slice(0, 5)
  const stats = [
    { label: 'Content monitored', value: items.length, Icon: Layers3, note: 'In the latest 200 submissions', tone: 'teal' },
    { label: 'Threats detected', value: threats.length, Icon: ShieldAlert, note: 'High and critical risk verdicts', tone: 'coral' },
    { label: 'Awaiting analysis', value: pending.length, Icon: Clock3, note: 'Submitted without a verdict', tone: 'amber' },
    { label: 'Sources represented', value: platforms.length, Icon: Activity, note: 'Across monitored content', tone: 'violet' },
  ]
  return <div className="overview page-enter">
    <div className="page-heading"><div><p className="eyebrow">YOUR INTELLIGENCE AT A GLANCE</p><h1>See the signals. Stop the scams.</h1><p>A clearer view of emerging threats, backed by traceable evidence.</p></div><button className="button-secondary" onClick={() => void refetch()} disabled={isFetching}><RefreshCw size={15} className={isFetching ? 'animate-spin' : ''} />Refresh</button></div>
    {isError && <div role="alert" className="error-banner"><AlertCircle size={18} />Unable to load intelligence. Check that the API is running, then refresh.</div>}
    <section className="overview-stats" aria-label="Monitoring statistics">{stats.map(({ label, value, Icon, note, tone }) => <article className="metric-card" key={label}><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon size={19} /></span></div><strong>{isLoading || isError ? '—' : value.toLocaleString()}</strong><p>{note}</p></article>)}</section>
    <section className="overview-middle"><article className="surface activity-chart"><div className="section-heading"><div><h2>Detection activity</h2><p>Submission volume and flagged threats by day</p></div><span className="subtle-tag">Latest 14 active days</span></div><div className="chart-legend"><span><i />All submissions</span><span><i />High & critical</span></div>{chart.length > 0 ? <ResponsiveContainer width="100%" height={235}><AreaChart data={chart} margin={{ left: -24, right: 12, top: 12, bottom: 0 }}><defs><linearGradient id="activity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0d9488" stopOpacity={0.19} /><stop offset="100%" stopColor="#0d9488" stopOpacity={0} /></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 5" /><XAxis dataKey="date" tickFormatter={v => v.slice(5)} tick={{ fontSize: 11, fill: '#89959e' }} axisLine={false} tickLine={false} dy={9} /><YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#89959e' }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, color: 'var(--text)' }} /><Area name="All submissions" type="monotone" dataKey="analyzed" stroke="#0d9488" strokeWidth={2.5} fill="url(#activity-fill)" /><Area name="High & critical" type="monotone" dataKey="threats" stroke="#ed8d72" strokeWidth={2} fill="transparent" /></AreaChart></ResponsiveContainer> : <div className="chart-empty"><Activity size={30} /><strong>{isLoading ? 'Loading detection activity…' : isError ? 'Activity unavailable' : 'Your intelligence starts here'}</strong><span>{isError ? 'Reconnect to the API to see your data.' : 'Analyze content to build your activity timeline.'}</span></div>}</article>
      <article className="analysis-callout"><span className="callout-icon"><ScanLine size={27} /></span><span className="eyebrow">LOOK BEYOND THE SURFACE</span><h2>One submission.<br />A deeper understanding.</h2><p>Uncover fraud signals in videos, images, links, and text. Follow every verdict back to its evidence.</p><Link to="/analyze" className="button-primary">Analyze content <ArrowUpRight size={17} /></Link><span className="callout-foot"><ShieldCheck size={14} />Evidence-first analysis</span></article></section>
    <section className="surface recent-content"><div className="section-heading"><div><h2>Recent submissions</h2><p>The latest content entering your workspace</p></div><Link to="/queue" className="text-link">View detection queue <ArrowRight size={15} /></Link></div><div className="table-scroll"><table><thead><tr><th>CONTENT</th><th>SOURCE</th><th>RISK LEVEL</th><th>COLLECTED</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{recent.map(v => <tr key={v.video_id}><td><Link to={`/report/${encodeURIComponent(v.video_id)}`} className="content-link"><span className="content-icon"><FileSearch size={18} /></span><span>{v.title || v.url || 'Untitled submission'}<small>{v.content_type || 'video'} · {v.evidence_count} evidence signals</small></span></Link></td><td><span className="source-pill">{v.platform}</span></td><td><span className={`risk-pill ${v.level ? riskBadge(v.level) : 'bg-blue-100 text-blue-700'}`}>{v.level || 'PENDING'}</span></td><td className="date-cell">{fmtDate(v.collected_at)}</td><td><Link aria-label={`Open report for ${v.title || v.video_id}`} to={`/report/${encodeURIComponent(v.video_id)}`}><ArrowUpRight size={17} /></Link></td></tr>)}</tbody></table></div>{!recent.length && <div className="table-empty">{isLoading ? 'Loading submissions…' : isError ? 'Submissions unavailable. Refresh to try again.' : 'No submissions yet. Add your first piece of content to get started.'}</div>}</section>
    <div className="overview-footer"><span><ShieldCheck size={14} />Intelligence with a traceable evidence trail</span><Link to="/graph">Explore connected entities <GitFork size={14} /></Link></div>
  </div>
}
