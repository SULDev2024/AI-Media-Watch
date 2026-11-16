import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AgentReport, AgentRosterEntry, InvestigationResult, JournalEntry } from '../api/types'
import {
  Activity,
  AlertTriangle,
  Brain,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Command,
  FileText,
  Gauge,
  GitBranch,
  HelpCircle,
  Microscope,
  Play,
  Scale,
  Search,
  Shield,
  ShieldAlert,
  Target,
  Users,
  XCircle,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { clsx } from 'clsx'

const TIER_LABELS: Record<number, string> = {
  0: 'Command',
  1: 'Acquisition',
  2: 'Analysis',
  3: 'Challenge',
  4: 'Output',
}

const TIER_COLORS: Record<number, string> = {
  0: 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-200 border-cyan-400/30',
  1: 'bg-blue-500/15 text-blue-700 dark:text-blue-200 border-blue-400/30',
  2: 'bg-amber-500/15 text-amber-700 dark:text-amber-200 border-amber-400/30',
  3: 'bg-rose-500/15 text-rose-700 dark:text-rose-200 border-rose-400/30',
  4: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-200 border-emerald-400/30',
}

const TIER_LINES: Record<number, string> = {
  0: 'Case direction, evidence policy, and escalation gates.',
  1: 'Source capture, transcript recovery, entities, and platform context.',
  2: 'Risk scoring, forensics, network links, and legal mapping.',
  3: 'Adversarial challenge, dissent, and false-positive pressure tests.',
  4: 'Final brief, reviewer action, and sealed chain summary.',
}

const AGENT_ICONS: Record<string, LucideIcon> = {
  handler: Command,
  scout: Search,
  triage: Gauge,
  forensics: Microscope,
  correlator: GitBranch,
  legal: Scale,
  adversary: ShieldAlert,
  skeptic: HelpCircle,
  briefer: FileText,
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${Math.round(value * 100)}%`
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return value.toFixed(2)
}

function formatTime(value: string | null | undefined) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function tierClass(tier: number) {
  return TIER_COLORS[tier] ?? 'bg-gray-500 dark:bg-gray-500/15 text-gray-700 dark:text-gray-300 border-gray-500 dark:border-gray-500/30'
}

function agentIcon(name: string) {
  return AGENT_ICONS[name] ?? Shield
}

function keyValue(value: unknown) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function Metric({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'hot' | 'good' }) {
  return (
    <div className={clsx(
      'rounded border px-3 py-2',
      tone === 'hot'
        ? 'border-rose-500/30 bg-rose-500/10'
        : tone === 'good'
          ? 'border-emerald-500/30 bg-emerald-500/10'
          : 'border-gray-300 dark:border-gray-700/70 bg-gray-50 dark:bg-gray-900/50',
    )}>
      <div className="text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-gray-900 dark:text-gray-100">{value}</div>
    </div>
  )
}

function ChipList({ items }: { items?: string[] }) {
  if (!items?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(item => (
        <span key={item} className="rounded border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950/50 px-2 py-1 text-[11px] text-gray-700 dark:text-gray-300">
          {item}
        </span>
      ))}
    </div>
  )
}

function RosterCard({ agent }: { agent: AgentRosterEntry }) {
  const Icon = agentIcon(agent.name)

  return (
    <div className="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/60 p-4">
      <div className="flex items-start gap-3">
        <div className={clsx('rounded border p-2', tierClass(agent.tier))}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{agent.role}</h3>
            <span className={clsx('rounded border px-2 py-0.5 text-[10px] font-medium', tierClass(agent.tier))}>
              T{agent.tier} {TIER_LABELS[agent.tier]}
            </span>
            {agent.uses_llm && <Brain className="h-3.5 w-3.5 text-violet-300" />}
          </div>
          <p className="mt-2 text-sm leading-5 text-gray-700 dark:text-gray-300">{agent.objective ?? 'Objective pending.'}</p>
        </div>
      </div>
      {agent.authority && (
        <div className="mt-3 rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/50 px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
          <span className="font-medium text-gray-700 dark:text-gray-300">Authority:</span> {agent.authority}
        </div>
      )}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">Inputs</div>
          <ChipList items={agent.inputs} />
        </div>
        <div>
          <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">Outputs</div>
          <ChipList items={agent.outputs} />
        </div>
      </div>
    </div>
  )
}

function SignalGrid({ signals }: { signals: Record<string, unknown> }) {
  const entries = Object.entries(signals)
  if (!entries.length) return null

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/50 px-3 py-2">
          <div className="text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">{key.replace(/_/g, ' ')}</div>
          <div className="mt-1 break-words text-xs text-gray-700 dark:text-gray-300">{keyValue(value)}</div>
        </div>
      ))}
    </div>
  )
}

function AgentReportCard({
  report,
  rosterEntry,
  expanded,
  onToggle,
}: {
  report: AgentReport
  rosterEntry?: AgentRosterEntry
  expanded: boolean
  onToggle: () => void
}) {
  const Icon = agentIcon(report.agent)
  const confidence = Math.max(0, Math.min(1, report.confidence || 0))

  return (
    <div className="overflow-hidden rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/70">
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-800/60"
      >
        {expanded ? <ChevronDown className="h-4 w-4 shrink-0 text-gray-600 dark:text-gray-500" /> : <ChevronRight className="h-4 w-4 shrink-0 text-gray-600 dark:text-gray-500" />}
        <div className={clsx('rounded border p-2', tierClass(report.tier))}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{report.role}</span>
            <span className={clsx('rounded border px-2 py-0.5 text-[10px] font-medium', tierClass(report.tier))}>
              T{report.tier} {TIER_LABELS[report.tier]}
            </span>
            {report.used_llm && <span title="LLM assisted"><Brain className="h-3.5 w-3.5 text-violet-300" /></span>}
            {report.error && <XCircle className="h-4 w-4 text-rose-700 dark:text-rose-300" />}
          </div>
          <p className="mt-1 truncate text-xs text-gray-600 dark:text-gray-400">{report.assessment}</p>
        </div>
        <div className="hidden min-w-[150px] items-center gap-3 sm:flex">
          <span className="w-14 text-right text-xs text-gray-600 dark:text-gray-500">{report.elapsed_ms.toFixed(0)}ms</span>
          <div className="h-1.5 flex-1 rounded-full bg-gray-100 dark:bg-gray-800">
            <div className="h-1.5 rounded-full bg-cyan-400" style={{ width: `${confidence * 100}%` }} />
          </div>
          <span className="w-10 text-right text-xs text-gray-700 dark:text-gray-300">{formatPercent(confidence)}</span>
        </div>
      </button>

      {expanded && (
        <div className="space-y-4 border-t border-gray-200 dark:border-gray-800 px-4 pb-4 pt-4">
          {rosterEntry?.objective && (
            <div className="rounded border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-sm text-cyan-100">
              {rosterEntry.objective}
            </div>
          )}

          {report.findings.length > 0 && (
            <div>
              <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">Findings</div>
              <div className="space-y-2">
                {report.findings.map((finding, index) => (
                  <div key={`${report.agent}-${index}`} className="flex gap-2 rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/40 px-3 py-2 text-sm text-gray-700 dark:text-gray-300">
                    <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-700 dark:text-cyan-300" />
                    <span>{finding}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <SignalGrid signals={report.signals} />

          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">Expected Outputs</div>
              <ChipList items={rosterEntry?.outputs} />
            </div>
            <div>
              <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-500">Next Move</div>
              <div className="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/50 px-3 py-2 text-xs text-gray-700 dark:text-gray-300">
                {report.suggested_next ?? 'No additional move requested.'}
              </div>
            </div>
          </div>

          {report.error && (
            <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-200">
              {report.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PhaseRail({ active }: { active: boolean }) {
  const phases = [
    { tier: 0, label: 'Command' },
    { tier: 1, label: 'Acquire' },
    { tier: 2, label: 'Analyze' },
    { tier: 3, label: 'Challenge' },
    { tier: 4, label: 'Brief' },
  ]

  return (
    <div className="grid gap-2 sm:grid-cols-5">
      {phases.map(phase => (
        <div key={phase.tier} className={clsx(
          'rounded border px-3 py-3',
          active ? tierClass(phase.tier) : 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/60 text-gray-600 dark:text-gray-400',
        )}>
          <div className="flex items-center gap-2">
            <div className={clsx('h-2 w-2 rounded-full', active ? 'bg-current' : 'bg-gray-600 dark:bg-gray-600')} />
            <span className="text-xs font-semibold">{phase.label}</span>
          </div>
          <p className="mt-2 text-xs leading-4 opacity-80">{TIER_LINES[phase.tier]}</p>
        </div>
      ))}
    </div>
  )
}

function Journal({ entries }: { entries: JournalEntry[] }) {
  return (
    <div className="space-y-2">
      {entries.map((entry, index) => (
        <div key={`${entry.agent}-${entry.event}-${index}`} className="grid gap-2 rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/40 px-3 py-2 text-xs md:grid-cols-[88px_110px_92px_1fr]">
          <span className="font-mono text-gray-600 dark:text-gray-500">{formatTime(entry.ts)}</span>
          <span className="truncate font-medium text-cyan-700 dark:text-cyan-200" title={entry.agent}>{entry.agent}</span>
          <span className="text-gray-600 dark:text-gray-500">{entry.event}</span>
          <span className="text-gray-700 dark:text-gray-300">{entry.detail}</span>
        </div>
      ))}
    </div>
  )
}

function ResultBanner({ result }: { result: InvestigationResult }) {
  const risky = result.risk_level === 'HIGH' || result.risk_level === 'CRITICAL'
  const medium = result.risk_level === 'MEDIUM'

  return (
    <div className={clsx(
      'rounded border p-5',
      risky
        ? 'border-rose-500/40 bg-rose-500/10'
        : medium
          ? 'border-amber-500/40 bg-amber-500/10'
          : 'border-emerald-500/40 bg-emerald-500/10',
    )}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          {result.escalated_to_human ? (
            <AlertTriangle className="mt-1 h-6 w-6 text-amber-700 dark:text-amber-300" />
          ) : (
            <CheckCircle className="mt-1 h-6 w-6 text-emerald-700 dark:text-emerald-300" />
          )}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xl font-bold text-gray-900 dark:text-gray-100">{result.verdict || result.risk_level}</span>
              <span className="rounded border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950/40 px-2 py-1 text-xs text-gray-700 dark:text-gray-300">
                {result.risk_level}
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-sm text-gray-700 dark:text-gray-300">
              {result.escalated_to_human
                ? 'Human review is requested because the cell found dissent, uncertainty, or high operational risk.'
                : 'The cell completed without mandatory escalation.'}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[430px]">
          <Metric label="Score" value={formatScore(result.final_score)} tone={risky ? 'hot' : 'default'} />
          <Metric label="Confidence" value={formatPercent(result.confidence)} />
          <Metric label="Agents" value={String(Object.keys(result.reports).length)} tone="good" />
          <Metric label="Mode" value={result.llm_used ? 'LLM' : 'Rules'} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-gray-600 dark:text-gray-400">
        <span><Clock className="mr-1 inline h-3.5 w-3.5" />{result.iterations} iterations</span>
        {result.platform && <span>{result.platform}</span>}
        {result.chain_root && (
          <span className="font-mono text-gray-600 dark:text-gray-500" title={result.chain_root}>
            chain {result.chain_root.slice(0, 16)}
          </span>
        )}
      </div>
    </div>
  )
}

export function InvestigatePage() {
  const [searchParams] = useSearchParams()
  const [videoId, setVideoId] = useState(() => searchParams.get('vid') ?? '')
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<InvestigationResult | null>(null)

  const roster = useQuery({ queryKey: ['roster'], queryFn: () => api.investigate.roster() })
  const videos = useQuery({ queryKey: ['investigation-videos'], queryFn: () => api.videos.list(200) })

  const mutation = useMutation({
    mutationFn: (vid: string) => api.investigate.run(vid),
    onSuccess: (data) => {
      setResult(data)
      setExpandedAgents(new Set(Object.keys(data.reports)))
    },
  })

  useEffect(() => {
    const vid = searchParams.get('vid')
    if (vid?.trim()) {
      setVideoId(vid.trim())
      mutation.mutate(vid.trim())
    }
    // Only on mount so a copied case URL launches once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const rosterByName = useMemo(() => {
    return new Map((roster.data?.roster ?? []).map(agent => [agent.name, agent]))
  }, [roster.data])

  const rosterByTier = useMemo(() => {
    const groups = new Map<number, AgentRosterEntry[]>()
    for (const agent of roster.data?.roster ?? []) {
      const tier = groups.get(agent.tier) ?? []
      tier.push(agent)
      groups.set(agent.tier, tier)
    }
    return [...groups.entries()].sort(([a], [b]) => a - b)
  }, [roster.data])

  const sortedReports = result
    ? Object.values(result.reports).sort((a, b) => a.tier - b.tier || a.agent.localeCompare(b.agent))
    : []

  const toggleAgent = (name: string) => {
    setExpandedAgents(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded border border-cyan-400/30 bg-cyan-400/10 p-2">
              <Shield className="h-6 w-6 text-cyan-700 dark:text-cyan-200" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Investigation Cell</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                <span className="rounded-full border border-violet-400/30 bg-violet-400/10 px-2 py-0.5 text-violet-200">9-Agent</span>
                <span className="rounded-full border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-2 py-0.5">chain of custody</span>
                <span className="rounded-full border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-2 py-0.5">challenge layer</span>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 sm:min-w-[360px]">
          <Metric label="Roster" value={String(roster.data?.roster.length ?? 0)} />
          <Metric label="Reports" value={String(sortedReports.length)} />
          <Metric label="Escalate" value={result?.escalated_to_human ? 'Yes' : 'No'} tone={result?.escalated_to_human ? 'hot' : 'default'} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/70 p-4">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-cyan-700 dark:text-cyan-300" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Launch Case</h2>
          </div>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <select
              aria-label="Select saved content to investigate"
              value={videoId}
              onChange={event => { setVideoId(event.target.value); mutation.reset() }}
              disabled={mutation.isPending || videos.isLoading}
              className="min-h-11 min-w-0 flex-1 rounded border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 px-4 text-sm text-gray-800 dark:text-gray-200"
            >
              <option value="">{videos.isLoading ? 'Loading saved content...' : 'Choose analyzed content to investigate'}</option>
              {videoId && !videos.data?.items.some(v => v.video_id === videoId) && <option value={videoId}>Content ID: {videoId}</option>}
              {videos.data?.items.filter(v => v.level && v.level !== 'FAILED').map(v => (
                <option key={v.video_id} value={v.video_id}>{v.title || v.url} - {v.level}</option>
              ))}
            </select>
            <button
              onClick={() => videoId.trim() && mutation.mutate(videoId.trim())}
              disabled={mutation.isPending || !videoId.trim()}
              className={clsx(
                'inline-flex min-h-11 items-center justify-center gap-2 rounded px-5 text-sm font-semibold transition-colors',
                mutation.isPending
                  ? 'cursor-wait bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                  : 'bg-cyan-500 text-gray-950 dark:text-gray-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-gray-800 disabled:text-gray-500',
              )}
            >
              {mutation.isPending ? (
                <>
                  <Zap className="h-4 w-4 animate-pulse" />
                  Investigating
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Investigate
                </>
              )}
            </button>
          </div>
          {mutation.isError && (
            <div className="mt-3 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-200">
              {(mutation.error as Error).message}
            </div>
          )}
        </div>

        <div className="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/70 p-4">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-violet-300" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Cell Readiness</h2>
          </div>
          <div className="mt-4 space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Roster loaded</span>
              <span className={roster.data ? 'text-emerald-700 dark:text-emerald-300' : 'text-gray-600 dark:text-gray-500'}>{roster.data ? 'Ready' : 'Loading'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Reasoning path</span>
              <span className="text-gray-800 dark:text-gray-200">{result ? (result.llm_used ? 'LLM assisted' : 'Rules only') : 'Not run yet'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Last chain</span>
              <span className="font-mono text-xs text-gray-600 dark:text-gray-500">{result?.chain_root?.slice(0, 10) ?? 'none'}</span>
            </div>
          </div>
        </div>
      </div>

      <PhaseRail active={Boolean(result) || mutation.isPending} />

      {result && <ResultBanner result={result} />}

      {roster.data && !result && (
        <div className="space-y-4">
          {rosterByTier.map(([tier, agents]) => (
            <section key={tier}>
              <div className="mb-3 flex items-center gap-2">
                <span className={clsx('rounded border px-2 py-1 text-xs font-semibold', tierClass(tier))}>
                  T{tier} {TIER_LABELS[tier]}
                </span>
                <p className="text-sm text-gray-600 dark:text-gray-400">{TIER_LINES[tier]}</p>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {agents.map(agent => <RosterCard key={agent.name} agent={agent} />)}
              </div>
            </section>
          ))}
        </div>
      )}

      {result && (
        <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Agent Reports</h2>
              <span className="text-xs text-gray-600 dark:text-gray-500">{sortedReports.length} reports</span>
            </div>
            <div className="space-y-3">
              {sortedReports.map(report => (
                <AgentReportCard
                  key={report.agent}
                  report={report}
                  rosterEntry={rosterByName.get(report.agent)}
                  expanded={expandedAgents.has(report.agent)}
                  onToggle={() => toggleAgent(report.agent)}
                />
              ))}
            </div>
          </section>

          <aside className="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/70 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Journal</h2>
              <span className="text-xs text-gray-600 dark:text-gray-500">{result.journal.length} entries</span>
            </div>
            <div className="max-h-[760px] overflow-y-auto pr-1">
              <Journal entries={result.journal} />
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
