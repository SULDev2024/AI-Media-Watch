import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { riskBadge, fmtDate } from '../lib/format'
import { clsx } from 'clsx'
import {
  AlertTriangle,
  Bot,
  Brain,
  ChevronRight,
  FileText,
  GitBranch,
  Image,
  Loader2,
  Radio,
  RefreshCw,
  Scale,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Siren,
  ScanSearch,
  Video,
  XCircle,
  Zap,
  Cpu,
  Microscope,
  Camera,
  Clock,
} from 'lucide-react'

// ── types ─────────────────────────────────────────────────────────────────
interface AgentStatus {
  collector: { status: string; enqueued_total: number; last_enqueued: number; queries: string[]; platforms: string[] }
  analyst:   { total: number; analyzed: number; pending: number; avg_score: number; total_evidence: number }
  judge:     { verdicts: number; by_level: Record<string, number>; by_action: Record<string, number> }
  reporter:  { alerts_sent: number; dashboard_items: number }
  banned_sources: { value: string; type: string; banned_at: string }[]
  gpu_pipeline: string | null
  recent_activity: {
    video_id: string; platform: string; title: string | null
    level: string | null; score: number | null; action: string | null
    collected_at: string; content_type: string
  }[]
}

interface AIDetectResult {
  status: string
  url: string
  is_ai_generated: boolean | null
  confidence: number | null
  suspected_tool: string | null
  source_org: string | null
  evidence: string[]
  full_reasoning: string
}

interface FrameScanResult {
  status: string
  video_id: string
  title: string
  frames_scanned: number
  frames: {
    frame: string; status: string; reasoning: string
    risk_score: number; flags: string[]; logos_detected: string[]
    timestamp_sec: number; screenshot_url: string | null
  }[]
  all_logos_detected: string[]
  screenshots_saved: string[]
}

interface ScannableVideo {
  video_id: string; title: string; platform: string
  n_frames: number; level: string | null; score: number | null
}

// ── helpers ───────────────────────────────────────────────────────────────
function platformLabel(p: string) {
  const m: Record<string, string> = { youtube: 'YouTube', tiktok: 'TikTok', instagram: 'Instagram', telegram: 'Telegram', manual: 'Manual' }
  return m[p] ?? p
}

function ContentTypeIcon({ type }: { type: string }) {
  if (type === 'photo') return <Image className="h-3.5 w-3.5" />
  if (type === 'text')  return <FileText className="h-3.5 w-3.5" />
  return <Video className="h-3.5 w-3.5" />
}

// ── sub-components ────────────────────────────────────────────────────────

/** Formal section header — thick left rule + uppercase monospace label */
function SectionHeading({ children, icon: Icon }: { children: React.ReactNode; icon?: React.ElementType }) {
  return (
    <div className="flex items-center gap-2 border-l-4 border-gray-900 pl-3 dark:border-gray-100">
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-gray-500 dark:text-gray-400" />}
      <span className="text-[11px] font-mono font-bold uppercase tracking-widest text-gray-700 dark:text-gray-300">
        {children}
      </span>
    </div>
  )
}

/** Panel wrapper — thin border, no rounding excess */
function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={clsx('border border-gray-300 bg-white dark:border-gray-700 dark:bg-gray-900', className)}>
      {children}
    </div>
  )
}

/** Panel sub-header bar */
function PanelHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 dark:border-gray-700 dark:bg-gray-800/60">
      {children}
    </div>
  )
}

/** Agent pipeline status row */
function AgentRow({
  id, icon: Icon, name, role, status, primary, secondary, caps,
}: {
  id: string; icon: React.ElementType; name: string; role: string
  status: 'OPERATIONAL' | 'STANDBY' | 'OFFLINE'
  primary: { label: string; value: string | number }
  secondary: { label: string; value: string | number }
  caps: string[]
}) {
  const statusCls = {
    OPERATIONAL: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300',
    STANDBY:     'border-amber-300   bg-amber-50   text-amber-800   dark:border-amber-700   dark:bg-amber-950/50   dark:text-amber-300',
    OFFLINE:     'border-gray-300    bg-gray-100   text-gray-500    dark:border-gray-600    dark:bg-gray-800       dark:text-gray-500',
  }[status]

  const dotCls = {
    OPERATIONAL: 'bg-emerald-500',
    STANDBY:     'bg-amber-400',
    OFFLINE:     'bg-gray-400',
  }[status]

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/40">
      <td className="px-4 py-3 font-mono text-[10px] text-gray-400 whitespace-nowrap">{id}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center border border-gray-200 bg-gray-50 text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
            <Icon className="h-3.5 w-3.5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">{name}</div>
            <div className="text-[10px] text-gray-400">{role}</div>
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <span className={clsx('inline-flex items-center gap-1.5 border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider', statusCls)}>
          <span className={clsx('h-1.5 w-1.5 rounded-full', dotCls)} />
          {status}
        </span>
      </td>
      <td className="px-4 py-3 text-right">
        <div className="font-mono text-sm font-bold text-gray-900 dark:text-gray-100">{primary.value}</div>
        <div className="text-[10px] uppercase tracking-wide text-gray-400">{primary.label}</div>
      </td>
      <td className="px-4 py-3 text-right">
        <div className="font-mono text-sm font-bold text-gray-900 dark:text-gray-100">{secondary.value}</div>
        <div className="text-[10px] uppercase tracking-wide text-gray-400">{secondary.label}</div>
      </td>
      <td className="hidden px-4 py-3 xl:table-cell">
        <div className="flex flex-wrap gap-1">
          {caps.map(c => (
            <span key={c} className="border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-[9px] text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
              {c}
            </span>
          ))}
        </div>
      </td>
    </tr>
  )
}

/** AI Detection result panel */
function DetectResult({ result }: { result: AIDetectResult }) {
  if (result.status === 'gpu_required' || result.status === 'gpu_offline') {
    return (
      <div className="border border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30">
        <div className="border-b border-amber-200 bg-amber-100 px-4 py-2 dark:border-amber-800 dark:bg-amber-950/60">
          <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-amber-800 dark:text-amber-300">
            {result.status === 'gpu_offline' ? '⚠ GPU PIPELINE OFFLINE' : '⚠ GPU PIPELINE NOT CONFIGURED'}
          </span>
        </div>
        <div className="p-4 space-y-2">
          <p className="text-sm text-amber-800 dark:text-amber-300">{result.full_reasoning}</p>
          {result.status === 'gpu_offline' && (
            <div className="border border-amber-200 bg-white p-3 dark:border-amber-800 dark:bg-gray-900">
              <p className="font-mono text-[11px] font-bold uppercase tracking-wider text-gray-700 dark:text-gray-300 mb-1">To fix:</p>
              <ol className="space-y-1 text-xs text-gray-600 dark:text-gray-400">
                <li>1. Start the GPU server on your local machine</li>
                <li>2. Run <code className="font-mono bg-gray-100 dark:bg-gray-800 px-1">cloudflared tunnel run</code> to bring the tunnel back online</li>
                <li>3. Update <code className="font-mono bg-gray-100 dark:bg-gray-800 px-1">AIMW_GPU_PIPELINE_URL</code> in .env if the URL changed</li>
              </ol>
            </div>
          )}
        </div>
      </div>
    )
  }
  if (result.status === 'error') {
    return (
      <div className="flex items-start gap-3 border border-red-300 bg-red-50 p-4 dark:border-red-700 dark:bg-red-950/30">
        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
        <div>
          <p className="text-sm font-semibold text-red-800 dark:text-red-300">Detection Error</p>
          <p className="mt-0.5 text-xs text-red-700 dark:text-red-400">{result.full_reasoning}</p>
        </div>
      </div>
    )
  }

  const pct = result.confidence != null ? Math.round(result.confidence * 100) : null
  const verdict = result.is_ai_generated === true ? 'AI-GENERATED' : result.is_ai_generated === false ? 'AUTHENTIC' : 'INCONCLUSIVE'
  const verdictCls = result.is_ai_generated === true
    ? 'border-red-400 bg-red-50 text-red-800 dark:border-red-600 dark:bg-red-950/40 dark:text-red-300'
    : result.is_ai_generated === false
    ? 'border-emerald-400 bg-emerald-50 text-emerald-800 dark:border-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-300'
    : 'border-amber-400 bg-amber-50 text-amber-800 dark:border-amber-600 dark:bg-amber-950/40 dark:text-amber-300'
  const barCls = result.is_ai_generated === true ? 'bg-red-500' : result.is_ai_generated === false ? 'bg-emerald-500' : 'bg-amber-400'

  return (
    <div className="border border-gray-300 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
      {/* Report header */}
      <div className="border-b border-gray-300 bg-gray-900 px-4 py-2 dark:border-gray-700">
        <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-gray-300">
          AI Content Analysis Report
        </span>
      </div>
      <div className="p-4">
        {/* URL + verdict */}
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="truncate font-mono text-xs text-gray-500 dark:text-gray-400" title={result.url}>{result.url}</p>
          <span className={clsx('shrink-0 border px-3 py-1 font-mono text-xs font-bold uppercase tracking-widest', verdictCls)}>
            {verdict}
          </span>
        </div>

        {/* Confidence bar */}
        {pct != null && (
          <div className="mb-4">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">Confidence</span>
              <span className="font-mono text-sm font-bold text-gray-900 dark:text-gray-100">{pct}%</span>
            </div>
            <div className="h-2 w-full border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
              <div className={clsx('h-full transition-all duration-700', barCls)} style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        {/* Fields grid */}
        <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: 'Suspected Tool', value: result.suspected_tool ?? '—' },
            { label: 'Source Org',     value: result.source_org ?? '—' },
          ].map(f => (
            <div key={f.label} className="border border-gray-200 bg-white p-2 dark:border-gray-700 dark:bg-gray-900">
              <div className="font-mono text-[9px] uppercase tracking-widest text-gray-400">{f.label}</div>
              <div className="mt-1 text-xs font-semibold text-gray-800 dark:text-gray-200">{f.value}</div>
            </div>
          ))}
        </div>

        {/* Evidence */}
        {result.evidence.length > 0 && (
          <div className="mb-3">
            <div className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-gray-500">Evidence Observed</div>
            <ul className="space-y-1">
              {result.evidence.map((e, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-gray-700 dark:text-gray-300">
                  <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-red-500" />
                  {e}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Reasoning */}
        {result.full_reasoning && (
          <details className="text-xs">
            <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-widest text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              Full AI Reasoning ▾
            </summary>
            <p className="mt-2 whitespace-pre-wrap border border-gray-200 bg-white p-3 font-mono text-[10px] leading-relaxed text-gray-600 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
              {result.full_reasoning}
            </p>
          </details>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────
export function AgentsPage() {
  const [banInput, setBanInput] = useState('')
  const [banType, setBanType] = useState('channel')
  const [feedView, setFeedView] = useState<'threats' | 'all'>('threats')
  const [detectUrl, setDetectUrl] = useState('')
  const [detectResult, setDetectResult] = useState<AIDetectResult | null>(null)
  const [scanResult, setScanResult] = useState<FrameScanResult | null>(null)
  const [showScanner, setShowScanner] = useState(false)

  const { data, isLoading, isFetching, refetch } = useQuery<AgentStatus>({
    queryKey: ['agents-status'],
    queryFn: () => api.agents.status() as unknown as Promise<AgentStatus>,
    refetchInterval: 10_000,
    staleTime: 0,
  })

  const detectMut = useMutation({
    mutationFn: (url: string) => api.agents.aiDetect(url),
    onSuccess: (r) => setDetectResult(r),
  })

  const scannableQuery = useQuery<{ items: ScannableVideo[] }>({
    queryKey: ['scannable-videos'],
    queryFn: () => api.agents.scannable(),
    enabled: showScanner,
  })

  const scanMut = useMutation({
    mutationFn: (videoId: string) => api.agents.scanFrames(videoId),
    onSuccess: (r) => setScanResult(r),
  })

  const addBanMut = useMutation({
    mutationFn: ({ value, type }: { value: string; type: string }) => api.agents.addBan(value, type),
    onSuccess: () => refetch(),
  })
  const removeBanMut = useMutation({
    mutationFn: (idx: number) => api.agents.removeBan(idx),
    onSuccess: () => refetch(),
  })

  const col      = data?.collector
  const analyst  = data?.analyst
  const judge    = data?.judge
  const reporter = data?.reporter
  const banned   = data?.banned_sources ?? []
  const activity = data?.recent_activity ?? []

  const byLevel     = judge?.by_level ?? { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
  const collectorOn = col?.status === 'running'
  const alertCount  = (byLevel.CRITICAL ?? 0) + (byLevel.HIGH ?? 0)
  const highActivity = activity.filter(v => v.level === 'HIGH' || v.level === 'CRITICAL')
  const feedItems    = feedView === 'threats' ? highActivity : activity
  const maxLevel     = Math.max(...Object.values(byLevel), 1)

  if (isLoading) return (
    <div className="flex h-full items-center justify-center gap-2 text-gray-400">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span className="font-mono text-sm">LOADING SYSTEM STATUS…</span>
    </div>
  )

  return (
    <div className="min-h-full bg-gray-50 dark:bg-gray-950">

      {/* ── Classification banner ── */}
      <div className="bg-gray-900 px-6 py-1.5">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between">
          <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-yellow-400">
            ⚠ INTERNAL — FOR OFFICIAL USE ONLY
          </span>
          <span className="font-mono text-[10px] text-gray-500">
            SYSTEM: AIMW-2.1 &nbsp;·&nbsp; {new Date().toUTCString()}
          </span>
        </div>
      </div>

      {/* ── Agency header ── */}
      <div className="border-b border-gray-300 bg-white px-6 py-4 dark:border-gray-700 dark:bg-gray-900">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center border-2 border-gray-900 bg-gray-900 dark:border-gray-300">
              <Shield className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold uppercase tracking-widest text-gray-900 dark:text-gray-100">
                Agent Command Center
              </h1>
              <p className="font-mono text-[11px] text-gray-500 dark:text-gray-400">
                Financial Intelligence Unit · AI Media Watch System · Republic of Kazakhstan
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className={clsx(
              'flex items-center gap-2 border px-3 py-1.5 font-mono text-[11px] font-bold uppercase tracking-wide',
              collectorOn
                ? 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
                : 'border-gray-300 bg-gray-100 text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400',
            )}>
              <span className={clsx('h-2 w-2 rounded-full', collectorOn ? 'animate-pulse bg-emerald-500' : 'bg-gray-400')} />
              {collectorOn ? 'SYSTEM ACTIVE' : 'SYSTEM STANDBY'}
            </div>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 border border-gray-300 bg-white px-3 py-1.5 font-mono text-[11px] text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              <RefreshCw className={clsx('h-3.5 w-3.5', isFetching && 'animate-spin')} />
              REFRESH
            </button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-screen-2xl space-y-6 p-6">

        {/* ── Statistics grid ── */}
        <div className="grid grid-cols-2 divide-x divide-y divide-gray-300 border border-gray-300 bg-white dark:divide-gray-700 dark:border-gray-700 dark:bg-gray-900 sm:grid-cols-4 sm:divide-y-0">
          {[
            { label: 'Total Collected', value: col?.enqueued_total ?? analyst?.total ?? 0, sub: 'all platforms' },
            { label: 'Analyzed',        value: analyst?.analyzed ?? 0,                      sub: `${analyst?.pending ?? 0} pending`, ok: true },
            { label: 'Active Alerts',   value: alertCount,                                  sub: `${byLevel.CRITICAL ?? 0} critical`, hot: alertCount > 0 },
            { label: 'Banned Sources',  value: banned.length,                               sub: 'channels / domains' },
          ].map(s => (
            <div key={s.label} className="px-6 py-5">
              <div className="font-mono text-[10px] uppercase tracking-widest text-gray-400 dark:text-gray-500">{s.label}</div>
              <div className={clsx(
                'my-1 font-mono text-4xl font-bold tabular-nums',
                s.hot ? 'text-red-700 dark:text-red-400' : s.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-gray-900 dark:text-gray-100',
              )}>
                {s.value}
              </div>
              <div className="font-mono text-[10px] text-gray-400 dark:text-gray-500">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* ── Pipeline status table ── */}
        <div>
          <div className="mb-3">
            <SectionHeading icon={Bot}>Pipeline Agent Status</SectionHeading>
          </div>
          <Panel>
            <PanelHeader>
              <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500 dark:text-gray-400">
                4 autonomous agents — sequential processing pipeline
              </span>
            </PanelHeader>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/60">
                    {['Agent ID', 'Name / Role', 'Status', 'Primary', 'Secondary', 'Capabilities'].map((h, i) => (
                      <th key={h} className={clsx(
                        'px-4 py-2 text-left font-mono text-[10px] uppercase tracking-widest text-gray-500 dark:text-gray-400',
                        i === 5 && 'hidden xl:table-cell',
                      )}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <AgentRow
                    id="CLLCTR-01"
                    icon={Radio}
                    name="Collector"
                    role="Intelligence Gathering"
                    status={collectorOn ? 'OPERATIONAL' : 'STANDBY'}
                    primary={{ label: 'Collected', value: col?.enqueued_total ?? analyst?.total ?? 0 }}
                    secondary={{ label: 'Last batch', value: col?.last_enqueued ?? 0 }}
                    caps={['Web Crawlers', 'Scrapers', 'Spiders', 'Extension', 'Telegram']}
                  />
                  <AgentRow
                    id="ANLST-01"
                    icon={Brain}
                    name="Analyst"
                    role="Multi-Modal Extraction"
                    status={(analyst?.analyzed ?? 0) > 0 ? 'OPERATIONAL' : 'STANDBY'}
                    primary={{ label: 'Analyzed', value: analyst?.analyzed ?? 0 }}
                    secondary={{ label: 'Evidence', value: analyst?.total_evidence ?? 0 }}
                    caps={['Speech-to-Text', 'Vision AI', 'OCR', 'Frame Sampling']}
                  />
                  <AgentRow
                    id="JUDGE-01"
                    icon={Scale}
                    name="Judge"
                    role="Adversarial Verdict Engine"
                    status={(judge?.verdicts ?? 0) > 0 ? 'OPERATIONAL' : 'STANDBY'}
                    primary={{ label: 'Verdicts', value: judge?.verdicts ?? 0 }}
                    secondary={{ label: 'Avg score', value: analyst?.avg_score?.toFixed(2) ?? '—' }}
                    caps={['Prosecutor AI', 'Defense AI', 'Signals', 'KZ/RU/EN/HI']}
                  />
                  <AgentRow
                    id="RPRT-01"
                    icon={Siren}
                    name="Reporter"
                    role="Alert Dispatch & Triage"
                    status={alertCount > 0 ? 'OPERATIONAL' : 'STANDBY'}
                    primary={{ label: 'Alerts sent', value: alertCount }}
                    secondary={{ label: 'Dashboard', value: reporter?.dashboard_items ?? 0 }}
                    caps={['Priority Queue', 'Telegram', 'Android App', 'Extension']}
                  />
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        {/* ── AI-Generated Content Detection ── */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <SectionHeading icon={Microscope}>AI-Generated Content Detection</SectionHeading>
            <span className="border border-blue-300 bg-blue-50 px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-blue-700 dark:border-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
              NEW CAPABILITY
            </span>
          </div>
          <Panel>
            <PanelHeader>
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500 dark:text-gray-400">
                  Submit a URL to detect AI-generated video, deepfakes, and synthetic media — identifies source tool &amp; organization
                </span>
                <div className="ml-4 flex items-center gap-1.5 shrink-0">
                  <Cpu className="h-3 w-3 text-gray-400" />
                  <span className={clsx('font-mono text-[10px]', data?.gpu_pipeline ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400')}>
                    GPU {data?.gpu_pipeline ? 'ONLINE' : 'OFFLINE'}
                  </span>
                </div>
              </div>
            </PanelHeader>
            <div className="p-4 space-y-4">
              {/* Input form */}
              <div className="flex gap-2">
                <input
                  value={detectUrl}
                  onChange={e => setDetectUrl(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && detectUrl.trim() && detectMut.mutate(detectUrl.trim())}
                  placeholder="https://youtube.com/watch?v=...  or  https://www.instagram.com/p/..."
                  className="flex-1 border border-gray-300 bg-white px-3 py-2 font-mono text-xs text-gray-800 placeholder-gray-400 outline-none transition-colors focus:border-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:placeholder-gray-600 dark:focus:border-gray-400"
                />
                <button
                  onClick={() => detectUrl.trim() && detectMut.mutate(detectUrl.trim())}
                  disabled={!detectUrl.trim() || detectMut.isPending}
                  className="flex items-center gap-2 border border-gray-900 bg-gray-900 px-4 py-2 font-mono text-[11px] font-bold uppercase tracking-wider text-white hover:bg-gray-800 disabled:opacity-50 dark:border-gray-400 dark:bg-gray-800 dark:hover:bg-gray-700"
                >
                  {detectMut.isPending
                    ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Analyzing…</>
                    : <><ScanSearch className="h-3.5 w-3.5" /> Detect</>}
                </button>
              </div>

              {/* Supported platforms note */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="font-mono text-[10px] uppercase tracking-widest text-gray-400">Supported:</span>
                {['YouTube', 'Instagram', 'TikTok', 'Telegram', 'Direct Image URLs'].map(p => (
                  <span key={p} className="font-mono text-[10px] text-gray-500 dark:text-gray-400">▸ {p}</span>
                ))}
              </div>

              {/* Result */}
              {detectResult && <DetectResult result={detectResult} />}

              {/* What it detects */}
              {!detectResult && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[
                    { label: 'Deepfakes',       desc: 'Face-swap and GAN-generated faces' },
                    { label: 'AI Video Tools',  desc: 'Sora, Runway, HeyGen, Kling, Pika' },
                    { label: 'Source Tracing',  desc: 'Identifies generating organization' },
                    { label: 'Voice Cloning',   desc: 'Audio-visual sync anomaly detection' },
                  ].map(f => (
                    <div key={f.label} className="border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
                      <div className="font-mono text-[10px] font-bold uppercase tracking-wide text-gray-700 dark:text-gray-300">{f.label}</div>
                      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">{f.desc}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        </div>

        {/* ── Frame Scanner / Logo Detection ── */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <SectionHeading icon={Camera}>Forensic Frame Scanner</SectionHeading>
            <button
              onClick={() => setShowScanner(!showScanner)}
              className={clsx(
                'border px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-wider transition-colors',
                showScanner
                  ? 'border-gray-900 bg-gray-900 text-white dark:border-gray-400 dark:bg-gray-200 dark:text-gray-900'
                  : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300',
              )}
            >
              {showScanner ? 'COLLAPSE' : 'EXPAND'}
            </button>
          </div>

          {showScanner && (
            <Panel>
              <PanelHeader>
                <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500 dark:text-gray-400">
                  Select a video to scan its frames for logos, brand marks, fake UI, QR codes, and suspicious overlays via GPU vision
                </span>
              </PanelHeader>
              <div className="p-4 space-y-4">

                {/* Video selection table */}
                {scannableQuery.isLoading ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-gray-400">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="font-mono text-xs">Loading scannable videos…</span>
                  </div>
                ) : (scannableQuery.data?.items ?? []).length === 0 ? (
                  <p className="py-6 text-center font-mono text-xs text-gray-400">No videos with extracted frames available</p>
                ) : (
                  <div className="max-h-64 overflow-y-auto border border-gray-200 dark:border-gray-700">
                    <table className="w-full">
                      <thead className="sticky top-0">
                        <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/60">
                          {['Video', 'Platform', 'Level', 'Frames', ''].map(h => (
                            <th key={h} className="px-3 py-1.5 text-left font-mono text-[9px] uppercase tracking-widest text-gray-500 dark:text-gray-400">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(scannableQuery.data?.items ?? []).map(v => (
                          <tr key={v.video_id} className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/40">
                            <td className="max-w-xs px-3 py-2">
                              <span className="block truncate text-xs text-gray-800 dark:text-gray-200">{v.title}</span>
                            </td>
                            <td className="px-3 py-2 font-mono text-[10px] text-gray-500">{platformLabel(v.platform)}</td>
                            <td className="px-3 py-2">
                              {v.level && (
                                <span className={clsx('border px-1.5 py-0.5 font-mono text-[9px] font-bold', riskBadge(v.level))}>
                                  {v.level}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 font-mono text-[10px] text-gray-500">{v.n_frames}</td>
                            <td className="px-3 py-2">
                              <button
                                onClick={() => scanMut.mutate(v.video_id)}
                                disabled={scanMut.isPending}
                                className="border border-gray-900 bg-gray-900 px-2.5 py-1 font-mono text-[9px] font-bold uppercase text-white hover:bg-gray-800 disabled:opacity-50 dark:border-gray-400 dark:bg-gray-700 dark:hover:bg-gray-600"
                              >
                                {scanMut.isPending && scanMut.variables === v.video_id
                                  ? <><Loader2 className="mr-1 inline h-3 w-3 animate-spin" />SCANNING…</>
                                  : 'SCAN'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Scan results */}
                {scanResult && (
                  <div className="border border-gray-300 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                    <div className="border-b border-gray-300 bg-gray-900 px-4 py-2 dark:border-gray-700">
                      <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-gray-300">
                        Frame Analysis Report — {scanResult.title}
                      </span>
                    </div>
                    <div className="p-4 space-y-4">

                      {/* Summary */}
                      <div className="grid grid-cols-3 gap-2">
                        <div className="border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-900">
                          <div className="font-mono text-[9px] uppercase tracking-widest text-gray-400">Frames Scanned</div>
                          <div className="mt-1 font-mono text-2xl font-bold text-gray-900 dark:text-gray-100">{scanResult.frames_scanned}</div>
                        </div>
                        <div className="border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-900">
                          <div className="font-mono text-[9px] uppercase tracking-widest text-gray-400">Logos Detected</div>
                          <div className="mt-1 font-mono text-2xl font-bold text-red-700 dark:text-red-400">{scanResult.all_logos_detected.length}</div>
                        </div>
                        <div className="border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-900">
                          <div className="font-mono text-[9px] uppercase tracking-widest text-gray-400">Screenshots Saved</div>
                          <div className="mt-1 font-mono text-2xl font-bold text-blue-700 dark:text-blue-400">{scanResult.screenshots_saved.length}</div>
                        </div>
                      </div>

                      {/* Detected logos */}
                      {scanResult.all_logos_detected.length > 0 && (
                        <div>
                          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-gray-500">Brands / Logos Identified</div>
                          <div className="flex flex-wrap gap-1.5">
                            {scanResult.all_logos_detected.map(logo => (
                              <span key={logo} className="border border-red-300 bg-red-50 px-2 py-1 font-mono text-xs font-bold text-red-800 dark:border-red-700 dark:bg-red-950/40 dark:text-red-300">
                                {logo}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Per-frame results */}
                      <div className="space-y-2">
                        {scanResult.frames.map((f, i) => (
                          <div key={i} className="border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
                            <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2 dark:border-gray-800">
                              <div className="flex items-center gap-3">
                                <span className="font-mono text-[10px] text-gray-400">#{i + 1}</span>
                                <span className="font-mono text-[10px] text-gray-500">{f.frame}</span>
                                <div className="flex items-center gap-1 text-gray-400">
                                  <Clock className="h-3 w-3" />
                                  <span className="font-mono text-[10px]">{f.timestamp_sec}s</span>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                {f.risk_score > 0 && (
                                  <span className="border border-red-300 bg-red-50 px-1.5 py-0.5 font-mono text-[9px] font-bold text-red-700 dark:border-red-700 dark:bg-red-950/40 dark:text-red-300">
                                    RISK {f.risk_score}
                                  </span>
                                )}
                                {f.flags.map(fl => (
                                  <span key={fl} className="border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-mono text-[9px] text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                                    {fl}
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="flex gap-3 p-3">
                              {/* Screenshot thumbnail */}
                              {f.screenshot_url && (
                                <a href={f.screenshot_url} target="_blank" rel="noopener" className="block shrink-0">
                                  <img
                                    src={f.screenshot_url}
                                    alt={f.frame}
                                    className="h-24 w-40 border border-gray-200 object-cover dark:border-gray-700"
                                  />
                                </a>
                              )}
                              <div className="min-w-0 flex-1">
                                {f.logos_detected.length > 0 && (
                                  <div className="mb-1.5 flex flex-wrap gap-1">
                                    {f.logos_detected.map(l => (
                                      <span key={l} className="border border-red-200 bg-red-50 px-1.5 py-0.5 font-mono text-[9px] font-bold text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
                                        {l}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                <p className="text-xs text-gray-600 dark:text-gray-400">{f.reasoning}</p>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          )}
        </div>

        {/* ── Main content: threat log + command panel ── */}
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">

          {/* ── Threat Intelligence Log ── */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <SectionHeading icon={ShieldAlert}>Threat Intelligence Log</SectionHeading>
              <div className="flex items-center gap-2">
                <div className="flex border border-gray-300 dark:border-gray-700">
                  {(['threats', 'all'] as const).map(v => (
                    <button
                      key={v}
                      onClick={() => setFeedView(v)}
                      className={clsx(
                        'px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-wider transition-colors',
                        feedView === v
                          ? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
                          : 'bg-white text-gray-500 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700',
                      )}
                    >
                      {v === 'threats' ? `Threats (${highActivity.length})` : `All (${activity.length})`}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <Panel>
              {feedItems.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <ShieldCheck className="mb-3 h-8 w-8 text-emerald-400" />
                  <p className="font-mono text-xs uppercase tracking-widest text-gray-400">
                    {feedView === 'threats' ? 'No active threats' : 'No records'}
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/60">
                        {['#', 'Type', 'Platform', 'Title / Identifier', 'Level', 'Score', 'Date'].map(h => (
                          <th key={h} className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-widest text-gray-500 dark:text-gray-400">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {feedItems.map((v, i) => {
                        const level = v.level ?? 'LOW'
                        return (
                          <tr
                            key={v.video_id}
                            className="group border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/40"
                          >
                            <td className="px-4 py-2.5 font-mono text-[10px] text-gray-400">{i + 1}</td>
                            <td className="px-4 py-2.5 text-gray-400">
                              <ContentTypeIcon type={v.content_type} />
                            </td>
                            <td className="px-4 py-2.5 font-mono text-[11px] text-gray-600 dark:text-gray-400 whitespace-nowrap">
                              {platformLabel(v.platform)}
                            </td>
                            <td className="max-w-xs px-4 py-2.5">
                              <Link
                                to={`/report/${v.video_id}`}
                                className="block truncate text-xs font-medium text-gray-800 hover:text-blue-700 dark:text-gray-200 dark:hover:text-blue-400"
                              >
                                {v.title ?? v.video_id}
                              </Link>
                            </td>
                            <td className="px-4 py-2.5">
                              <span className={clsx('border px-2 py-0.5 font-mono text-[10px] font-bold', riskBadge(level))}>
                                {level}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 font-mono text-xs tabular-nums text-gray-600 dark:text-gray-400">
                              {v.score != null ? `${Math.round(v.score * 100)}` : '—'}
                            </td>
                            <td className="px-4 py-2.5 font-mono text-[10px] text-gray-400 whitespace-nowrap">
                              {fmtDate(v.collected_at)}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>

          {/* ── Command Panel ── */}
          <aside className="space-y-6">

            {/* Threat distribution */}
            <div>
              <div className="mb-3">
                <SectionHeading icon={AlertTriangle}>Threat Distribution</SectionHeading>
              </div>
              <Panel>
                <PanelHeader>
                  <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500 dark:text-gray-400">
                    {analyst?.analyzed ?? 0} verdicts total
                  </span>
                </PanelHeader>
                <div className="space-y-3 p-4">
                  {([
                    { key: 'CRITICAL', barCls: 'bg-red-600',     numCls: 'text-red-700 dark:text-red-400' },
                    { key: 'HIGH',     barCls: 'bg-orange-500',  numCls: 'text-orange-600 dark:text-orange-400' },
                    { key: 'MEDIUM',   barCls: 'bg-yellow-500',  numCls: 'text-yellow-600 dark:text-yellow-400' },
                    { key: 'LOW',      barCls: 'bg-emerald-500', numCls: 'text-emerald-600 dark:text-emerald-400' },
                  ] as const).map(r => {
                    const count = byLevel[r.key] ?? 0
                    const pct = Math.round((count / maxLevel) * 100)
                    return (
                      <div key={r.key}>
                        <div className="mb-1 flex items-center justify-between">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{r.key}</span>
                          <span className={clsx('font-mono text-sm font-bold tabular-nums', r.numCls)}>{count}</span>
                        </div>
                        <div className="h-1.5 w-full border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800">
                          <div className={clsx('h-full transition-all duration-700', r.barCls)} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Panel>
            </div>

            {/* Quick actions */}
            <div>
              <div className="mb-3">
                <SectionHeading icon={Zap}>Quick Actions</SectionHeading>
              </div>
              <Panel>
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {([
                    { to: '/',            icon: ShieldAlert, label: 'Review Threat Queue'  },
                    { to: '/analyze',     icon: Zap,         label: 'Submit for Analysis'  },
                    { to: '/investigate', icon: Search,      label: 'Deep Investigation'   },
                    { to: '/graph',       icon: GitBranch,   label: 'Network Map'          },
                    { to: '/metrics',     icon: FileText,    label: 'System Metrics'        },
                  ] as const).map(a => (
                    <Link
                      key={a.to}
                      to={a.to}
                      className="group flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/50"
                    >
                      <div className="flex items-center gap-2.5">
                        <a.icon className="h-3.5 w-3.5 text-gray-400 group-hover:text-gray-700 dark:group-hover:text-gray-200" />
                        <span className="text-sm text-gray-700 group-hover:text-gray-900 dark:text-gray-300 dark:group-hover:text-gray-100">
                          {a.label}
                        </span>
                      </div>
                      <ChevronRight className="h-3.5 w-3.5 text-gray-300 group-hover:text-gray-600 dark:text-gray-600 dark:group-hover:text-gray-300" />
                    </Link>
                  ))}
                </div>
              </Panel>
            </div>

            {/* Banned sources */}
            <div>
              <div className="mb-3 flex items-center justify-between">
                <SectionHeading icon={XCircle}>Banned Sources</SectionHeading>
                <span className="border border-red-300 bg-red-50 px-2 py-0.5 font-mono text-[10px] font-bold text-red-700 dark:border-red-700 dark:bg-red-950/40 dark:text-red-300">
                  {banned.length} ACTIVE
                </span>
              </div>
              <Panel>
                <div className="p-3">
                  <div className="mb-2 flex gap-1.5">
                    <select
                      value={banType}
                      onChange={e => setBanType(e.target.value)}
                      className="border border-gray-300 bg-white px-2 py-1.5 font-mono text-[11px] text-gray-700 outline-none focus:border-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:focus:border-gray-400"
                    >
                      <option value="channel">Channel</option>
                      <option value="domain">Domain</option>
                      <option value="account">Account</option>
                    </select>
                    <input
                      value={banInput}
                      onChange={e => setBanInput(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && banInput.trim() && (addBanMut.mutate({ value: banInput.trim(), type: banType }), setBanInput(''))}
                      placeholder="@channel or domain.com"
                      className="min-w-0 flex-1 border border-gray-300 bg-white px-2 py-1.5 font-mono text-[11px] text-gray-700 placeholder-gray-400 outline-none focus:border-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:placeholder-gray-600 dark:focus:border-gray-400"
                    />
                    <button
                      onClick={() => { if (banInput.trim()) { addBanMut.mutate({ value: banInput.trim(), type: banType }); setBanInput('') } }}
                      disabled={!banInput.trim() || addBanMut.isPending}
                      className="border border-red-700 bg-red-700 px-3 py-1.5 font-mono text-[11px] font-bold uppercase text-white hover:bg-red-800 disabled:opacity-50"
                    >
                      {addBanMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : 'BAN'}
                    </button>
                  </div>
                  <div className="max-h-40 divide-y divide-gray-100 overflow-y-auto dark:divide-gray-800">
                    {banned.length === 0 ? (
                      <p className="py-3 text-center font-mono text-[10px] uppercase tracking-widest text-gray-400">No entries</p>
                    ) : banned.map((b, i) => (
                      <div key={i} className="flex items-center gap-2 py-1.5">
                        <span className="border border-red-200 bg-red-50 px-1.5 py-0.5 font-mono text-[9px] uppercase font-bold text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
                          {b.type}
                        </span>
                        <span className="flex-1 truncate font-mono text-[11px] text-gray-700 dark:text-gray-300">{b.value}</span>
                        <button onClick={() => removeBanMut.mutate(i)} className="text-gray-400 hover:text-red-600 dark:hover:text-red-400">
                          <XCircle className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>
            </div>

            {/* Infrastructure */}
            <div>
              <div className="mb-3">
                <SectionHeading icon={ShieldCheck}>Infrastructure</SectionHeading>
              </div>
              <Panel>
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {[
                    { label: 'Data Sovereignty', value: 'ON-PREMISE',                                     ok: true  },
                    { label: 'GPU Pipeline',      value: data?.gpu_pipeline ? 'CONNECTED' : 'OFFLINE',    ok: !!data?.gpu_pipeline },
                    { label: 'Collector Agent',   value: collectorOn ? 'RUNNING' : 'STOPPED',             ok: collectorOn },
                    { label: 'YouTube',           value: 'ACTIVE',                                        ok: true  },
                    { label: 'Telegram',          value: 'ACTIVE',                                        ok: true  },
                    { label: 'Instagram',         value: 'ACTIVE',                                        ok: true  },
                    { label: 'TikTok',            value: 'ACTIVE',                                        ok: true  },
                  ].map(r => (
                    <div key={r.label} className="flex items-center justify-between px-4 py-2">
                      <span className="font-mono text-[11px] text-gray-500 dark:text-gray-400">{r.label}</span>
                      <span className={clsx('font-mono text-[10px] font-bold uppercase tracking-wider', r.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-gray-400')}>
                        {r.value}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
            </div>

          </aside>
        </div>
      </div>
    </div>
  )
}
