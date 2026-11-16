import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { riskBadge, fmtDate, confidenceLabel } from '../lib/format'
import { clsx } from 'clsx'
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowUpDown,
  Clock3,
  Download,
  ExternalLink,
  FileText,
  Filter,
  Image,
  Loader2,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Video,
  XCircle,
} from 'lucide-react'
import type { VideoSummary, VideosList } from '../api/types'
import { CollectorControl } from '../components/CollectorControl'
import type { ReactNode } from 'react'
import { useState } from 'react'

type SortKey = 'priority' | 'date'
type ViewKey = 'threats' | 'all' | 'pending' | 'critical' | 'high' | 'failed'

function isPending(v: VideoSummary) {
  return v.level == null && v.score == null
}

function isThreat(v: VideoSummary) {
  return v.level === 'HIGH' || v.level === 'CRITICAL'
}

function ageMinutes(v: VideoSummary) {
  return (Date.now() - new Date(v.collected_at).getTime()) / 60_000
}

function isFresh(v: VideoSummary) {
  return ageMinutes(v) <= 60
}

function platformIcon(platform: string) {
  return platform.toLowerCase() === 'youtube' ? '\u25B6' : '\u2022'
}

function platformLabel(platform: string) {
  const p = platform.toLowerCase()
  if (p === 'youtube') return 'YouTube'
  if (p === 'tiktok') return 'TikTok'
  if (p === 'instagram') return 'Instagram'
  if (p === 'telegram') return 'Telegram'
  if (p === 'manual') return 'Manual'
  return platform
}

function PriorityBar({ score }: { score: number | null }) {
  if (score == null || score === 0) return null
  const pct = Math.round(score * 100)
  const colour =
    pct >= 80 ? 'bg-red-500' :
    pct >= 50 ? 'bg-orange-400' :
    pct >= 20 ? 'bg-yellow-400' : 'bg-gray-300'
  return (
    <div className="flex items-center gap-1.5 shrink-0" title={`Priority: ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
        <div className={clsx('h-full rounded-full transition-all', colour)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-7 text-[10px] font-mono tabular-nums text-gray-400">{pct}%</span>
    </div>
  )
}

function ContentTypeBadge({ type }: { type: string }) {
  if (type === 'photo') return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
      <Image className="h-3 w-3" />PHOTO
    </span>
  )
  if (type === 'text') return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">
      <FileText className="h-3 w-3" />TEXT
    </span>
  )
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
      <Video className="h-3 w-3" />VIDEO
    </span>
  )
}

function ContentTypeIcon({ type }: { type: string }) {
  if (type === 'photo') return <Image className="h-5 w-5" />
  if (type === 'text') return <FileText className="h-5 w-5" />
  return <Video className="h-5 w-5" />
}

function Stat({ label, value, icon, tone = 'neutral' }: { label: string; value: number; icon: ReactNode; tone?: 'neutral' | 'red' | 'orange' | 'blue' }) {
  const tones = {
    neutral: 'border-gray-200 bg-white text-gray-900 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100',
    red: 'border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100',
    orange: 'border-orange-200 bg-orange-50 text-orange-900 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-100',
    blue: 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-100',
  }
  return (
    <div className={clsx('rounded-lg border px-3 py-2', tones[tone])}>
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide opacity-65">
        {icon}{label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function ViewButton({
  active,
  children,
  onClick,
  count,
}: {
  active: boolean
  children: ReactNode
  onClick: () => void
  count?: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-sm font-medium transition-colors',
        active
          ? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
          : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800',
      )}
    >
      {children}
      {count != null && count > 0 && (
        <span className={clsx(
          'ml-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold',
          active
            ? 'bg-white/20 text-white dark:bg-gray-900/30 dark:text-gray-900'
            : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
        )}>
          {count}
        </span>
      )}
    </button>
  )
}

function riskScoreDisplay(score: number | null): string {
  if (score == null) return '—'
  return `${Math.round(score * 100)}/100`
}

function QueueRow({ v }: { v: VideoSummary }) {
  const qc = useQueryClient()
  const cancel = useMutation({
    mutationFn: () => api.videos.cancel(v.video_id),
    onSuccess: () => {
      qc.setQueriesData<VideosList>({ queryKey: ['videos'] }, old => old ? { ...old, items: old.items.map(item => item.video_id === v.video_id ? { ...item, level: 'CANCELLED', action: 'cancelled', score: null, priority_score: null } : item) } : old)
      void qc.invalidateQueries({ queryKey: ['videos'] })
      void qc.invalidateQueries({ queryKey: qk.video(v.video_id) })
    },
    onError: () => { void qc.invalidateQueries({ queryKey: ['videos'] }) },
  })
  const confLabel = v.confidence != null ? confidenceLabel(v.confidence) : null
  const navigate = useNavigate()
  const ct = v.content_type ?? 'video'
  const pending = isPending(v)
  const fresh = isFresh(v)
  const displayTitle = v.title || v.url

  const borderColor = v.level === 'CRITICAL'
    ? 'border-l-red-600'
    : v.level === 'HIGH'
    ? 'border-l-orange-500'
    : v.level === 'MEDIUM'
    ? 'border-l-yellow-500'
    : pending
    ? 'border-l-blue-400'
    : 'border-l-gray-300'

  return (
    <div
      className={clsx(
        'group relative grid grid-cols-[40px_minmax(0,1fr)] gap-3 rounded-lg border border-l-4 bg-white px-4 py-3 transition-all hover:shadow-md dark:bg-gray-800 sm:grid-cols-[40px_minmax(0,1fr)_auto]',
        borderColor,
        pending ? 'border-t-blue-100 border-r-blue-100 border-b-blue-100 dark:border-t-blue-900 dark:border-r-blue-900 dark:border-b-blue-900' : 'border-t-gray-200 border-r-gray-200 border-b-gray-200 dark:border-t-gray-700 dark:border-r-gray-700 dark:border-b-gray-700',
      )}
    >
      {/* Icon */}
      <div className={clsx(
        'flex h-10 w-10 shrink-0 items-center justify-center rounded transition-colors',
        v.level === 'CRITICAL' ? 'bg-red-100 text-red-600 dark:bg-red-900 dark:text-red-300'
          : v.level === 'HIGH' ? 'bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-300'
          : pending ? 'bg-blue-100 text-blue-500 dark:bg-blue-900 dark:text-blue-300'
          : 'bg-gray-100 text-gray-400 dark:bg-gray-700',
      )}>
        {pending ? <Loader2 className="h-5 w-5 animate-spin" /> : <ContentTypeIcon type={ct} />}
      </div>

      {/* Main content */}
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-sm font-medium text-gray-800 dark:text-gray-200 group-hover:text-blue-600 dark:group-hover:text-blue-400">
            <Link to={`/report/${v.video_id}`} className="after:absolute after:inset-0 after:rounded-lg focus-visible:after:ring-2 focus-visible:after:ring-blue-500">
              {displayTitle}
            </Link>
          </p>
          {fresh && (
            <span className="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200">
              NEW
            </span>
          )}
          {pending && (
            <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700 dark:bg-blue-900 dark:text-blue-200">
              ANALYZING
            </span>
          )}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
            <span>{platformIcon(v.platform)}</span>
            {platformLabel(v.platform)}
          </span>
          <ContentTypeBadge type={ct} />
          <span className="text-xs text-gray-400">{fmtDate(v.collected_at)}</span>
          {v.evidence_count > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-red-600 dark:text-red-400">
              <AlertTriangle className="h-3 w-3" />
              {v.evidence_count} signal{v.evidence_count !== 1 ? 's' : ''}
            </span>
          )}
          {/* Source link */}
          <a
            href={v.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="relative z-10 inline-flex items-center gap-0.5 text-[10px] text-blue-500 hover:text-blue-700 dark:text-blue-400"
            title="Open original source"
          >
            <ExternalLink className="h-3 w-3" />
            source
          </a>
        </div>
      </div>

      {/* Right side: scores + actions */}
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-3 sm:col-span-1 sm:flex-nowrap">
        {pending && <button type="button" disabled={cancel.isPending}
          onClick={event => { event.preventDefault(); event.stopPropagation(); cancel.mutate() }}
          aria-label={`Cancel analysis of ${displayTitle}`}
          className="relative z-10 inline-flex items-center gap-1.5 rounded border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50">
          {cancel.isPending ? <Loader2 size={14} className="animate-spin" /> : <XCircle size={14} />}
          {cancel.isPending ? 'Cancelling...' : 'Cancel'}
        </button>}
        {cancel.isError && <span role="alert" className="relative z-10 max-w-48 text-xs text-red-600">{cancel.error instanceof Error ? cancel.error.message : 'Could not cancel this item. Refresh and try again.'}</span>}
        <PriorityBar score={v.priority_score} />

        {v.level && (
          <span className={clsx('rounded px-2 py-0.5 text-xs font-bold', riskBadge(v.level))}>
            {v.level}
          </span>
        )}
        {v.score != null && (
          <span className="font-mono text-sm font-semibold tabular-nums text-gray-700 dark:text-gray-300">
            {riskScoreDisplay(v.score)}
          </span>
        )}
        {confLabel && (
          <span className="hidden text-xs text-gray-500 dark:text-gray-400 md:block">{confLabel}</span>
        )}

        {v.level && v.level !== 'FAILED' && v.level !== 'CANCELLED' && v.level !== 'CLEAN' && v.level !== 'LOW' && (
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/investigate?vid=${v.video_id}`) }}
            className="relative z-10 shrink-0 text-purple-400 hover:text-purple-600"
            title="Run 9-agent investigation"
          >
            <Search className="h-4 w-4" />
          </button>
        )}

        {v.level && v.level !== 'FAILED' && v.level !== 'CANCELLED' && v.level !== 'CLEAN' && v.level !== 'LOW' && (
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/cases/${v.video_id}`) }}
            className="relative z-10 shrink-0 text-blue-400 hover:text-blue-600"
            title="Open sealed case file"
          >
            <ShieldCheck className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}

export function QueuePage() {
  const [sortKey, setSortKey] = useState<SortKey>('priority')
  const [view, setView] = useState<ViewKey>('all')
  const [search, setSearch] = useState('')
  const [exportError, setExportError] = useState('')

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: qk.videos(200),
    queryFn: () => api.videos.list(200),
    refetchInterval: 10_000,
  })

  const items = data?.items ?? []
  const pendingCount = items.filter(isPending).length
  const failedCount = items.filter(v => v.level === 'FAILED').length
  const threatCount = items.filter(isThreat).length
  const criticalCount = items.filter(v => v.level === 'CRITICAL').length
  const highCount = items.filter(v => v.level === 'HIGH').length

  const filtered = items.filter((v) => {
    if (search.trim() && ![v.title, v.url, v.platform, v.video_id].some(value => value?.toLowerCase().includes(search.trim().toLowerCase()))) return false
    if (view === 'threats') return isThreat(v)
    if (view === 'pending') return isPending(v)
    if (view === 'failed') return v.level === 'FAILED'
    if (view === 'critical') return v.level === 'CRITICAL'
    if (view === 'high') return v.level === 'HIGH'
    return true // 'all'
  })

  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === 'date') {
      return new Date(b.collected_at).getTime() - new Date(a.collected_at).getTime()
    }
    return (b.priority_score ?? 0) - (a.priority_score ?? 0)
  })

  return (
    <div className="mx-auto max-w-7xl p-6">
      {/* Header */}
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-gray-900 dark:text-gray-100">
            <ShieldAlert className="h-6 w-6 text-red-500" />
            Detection Queue
          </h1>
          <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
            All submitted content and analysis outcomes. Use Threats to show HIGH and CRITICAL results.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setSortKey(k => k === 'priority' ? 'date' : 'priority')}
            className="inline-flex items-center gap-1.5 rounded border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            title="Toggle sort"
          >
            <ArrowUpDown className="h-3.5 w-3.5" />
            {sortKey === 'priority' ? 'Priority' : 'Newest'}
          </button>

          <button
            onClick={async () => {
              setExportError('')
              try {
              const blob = await api.reports.exportCsv()
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = 'aimw_reports.csv'
              a.click()
              URL.revokeObjectURL(url)
              } catch { setExportError('Export failed. Check the API connection and try again.') }
            }}
            className="inline-flex items-center gap-1.5 rounded border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            <Download className="h-3.5 w-3.5" />
            Export CSV
          </button>
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 rounded border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </div>

      {exportError && <p role="alert" className="error-banner">{exportError}</p>}
      <label className="queue-search"><Search size={17} /><span className="sr-only">Search submissions</span><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search titles, sources, platforms, or content IDs..." /></label>
      {/* Stats */}
      <div className="mb-5 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Threats" value={threatCount} icon={<ShieldAlert className="h-3.5 w-3.5" />} tone="red" />
        <Stat label="Critical" value={criticalCount} icon={<AlertTriangle className="h-3.5 w-3.5" />} tone="red" />
        <Stat label="High Risk" value={highCount} icon={<Shield className="h-3.5 w-3.5" />} tone="orange" />
        <Stat label="Analyzing" value={pendingCount} icon={<Clock3 className="h-3.5 w-3.5" />} tone="blue" />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <main className="min-w-0">
          {/* View filter bar */}
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex flex-wrap items-center gap-1 rounded-lg border border-gray-200 bg-white p-1 dark:border-gray-700 dark:bg-gray-900">
              <ViewButton active={view === 'threats'} onClick={() => setView('threats')} count={threatCount}>
                <ShieldAlert className="h-3.5 w-3.5" /> Threats
              </ViewButton>
              <ViewButton active={view === 'critical'} onClick={() => setView('critical')} count={criticalCount}>
                Critical
              </ViewButton>
              <ViewButton active={view === 'high'} onClick={() => setView('high')} count={highCount}>
                High
              </ViewButton>
              <ViewButton active={view === 'pending'} onClick={() => setView('pending')} count={pendingCount}>
                <Clock3 className="h-3.5 w-3.5" /> Pending
              </ViewButton>
              <ViewButton active={view === 'all'} onClick={() => setView('all')}>
                <Filter className="h-3.5 w-3.5" /> All
              </ViewButton>
              <ViewButton active={view === 'failed'} onClick={() => setView('failed')} count={failedCount}>
                <AlertCircle className="h-3.5 w-3.5" /> Failed
              </ViewButton>
            </div>
            <div className="inline-flex items-center gap-2 text-xs text-gray-400">
              <Activity className="h-3.5 w-3.5" />
              {sorted.length} shown
            </div>
          </div>

          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-20 text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm">Loading queue...</span>
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              Failed to load queue.
            </div>
          )}

          {data && (
            <div className="space-y-2">
              {sorted.length === 0 ? (
                <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 py-16 text-center dark:border-gray-700 dark:bg-gray-900">
                  <ShieldCheck className="mx-auto mb-3 h-8 w-8 text-green-400" />
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                    {view === 'threats' ? 'No HIGH or CRITICAL results in the submitted items.' : 'No items in this view.'}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    Upload a video on Analyze, or start the collector with search terms. Check All for other results.
                  </p>
                </div>
              ) : (
                sorted.map((v) => <QueueRow key={v.video_id} v={v} />)
              )}
            </div>
          )}
        </main>

        <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start">
          <CollectorControl />
        </aside>
      </div>
    </div>
  )
}
