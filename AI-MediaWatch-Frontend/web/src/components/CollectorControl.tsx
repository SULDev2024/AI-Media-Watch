import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Link } from 'react-router-dom'
import {
  Loader2,
  Play,
  Square,
  Radar,
  AlertCircle,
  Sparkles,
  Plus,
  RefreshCw,
  MapPin,
} from 'lucide-react'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { fmtDate } from '../lib/format'
import type { KeywordSuggestion } from '../api/types'

const ALL_PLATFORMS = [
  { id: 'youtube', label: 'YouTube', urlOnly: false },
  { id: 'telegram', label: 'Telegram', urlOnly: false },
  { id: 'instagram', label: 'Instagram', urlOnly: true },
  { id: 'tiktok', label: 'TikTok', urlOnly: true },
]

const ALL_CONTENT_TYPES = [
  { id: 'video', label: 'Video' },
  { id: 'photo', label: 'Photo' },
  { id: 'text', label: 'Text' },
]

const REGION_OPTIONS = [
  { id: 'global', label: 'Global' },
  { id: 'kazakhstan', label: 'Kazakhstan / KZ' },
]

function normalizeContentTypes(selectedPlatforms: string[], selectedTypes: string[]) {
  const active = selectedTypes.length ? selectedTypes : ['video']
  const supportsTelegramMedia = selectedPlatforms.includes('telegram')
  const normalized = active.filter((kind) => {
    if (kind === 'video') return true
    return supportsTelegramMedia
  })
  if (selectedPlatforms.includes('youtube') && !normalized.includes('video')) {
    normalized.unshift('video')
  }
  return Array.from(new Set(normalized.length ? normalized : ['video']))
}

export function CollectorControl() {
  const qc = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.collector(),
    queryFn: () => api.collector.status(),
    refetchInterval: 5_000,
  })

  const { data: suggestionsData } = useQuery({
    queryKey: ['collector', 'suggestions'],
    queryFn: () => api.collector.suggestions(),
    refetchInterval: 60_000,
  })

  const [queryText, setQueryText] = useState('')
  const [platforms, setPlatforms] = useState<string[]>(['youtube'])
  const [contentTypes, setContentTypes] = useState<string[]>(['video', 'photo', 'text'])
  const [regionFocus, setRegionFocus] = useState('global')
  const [showTelegramSetup, setShowTelegramSetup] = useState(false)
  const formInitialized = useRef(false)

  useEffect(() => {
    if (!data || formInitialized.current) return
    formInitialized.current = true
    if (data) {
      setQueryText(data.queries.join(', '))
    }
    if (data && data.platforms?.length) setPlatforms(data.platforms)
    if (data && data.content_types?.length) {
      setContentTypes(normalizeContentTypes(data.platforms ?? ['youtube'], data.content_types))
    }
    if (data?.region_focus) setRegionFocus(data.region_focus)
  }, [data])

  const running = data?.status === 'running'

  const start = useMutation({
    mutationFn: () =>
      api.collector.start({
        queries: queryText
          .split(',')
          .map((q) => q.trim())
          .filter(Boolean),
        platforms,
        content_types: normalizeContentTypes(platforms, contentTypes),
        region_focus: regionFocus,
      }),
    onSuccess: (state) => qc.setQueryData(qk.collector(), state),
  })

  const togglePlatform = (id: string) => {
    formInitialized.current = true
    setPlatforms((prev) => {
      const next = prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
      const normalizedPlatforms = next.length ? next : ['youtube']
      setContentTypes((types) => normalizeContentTypes(normalizedPlatforms, types))
      return normalizedPlatforms
    })
  }

  // Keep at least one content type selected.
  const toggleContentType = (id: string) => {
    formInitialized.current = true
    if (id !== 'video' && !platforms.includes('telegram')) return
    setContentTypes((prev) => {
      const next = prev.includes(id)
        ? (prev.length > 1 ? prev.filter((t) => t !== id) : prev)
        : [...prev, id]
      return normalizeContentTypes(platforms, next)
    })
  }

  const stop = useMutation({
    mutationFn: () => api.collector.stop(),
    onSuccess: (state) => qc.setQueryData(qk.collector(), state),
  })

  const refreshSuggestions = useMutation({
    mutationFn: () => api.collector.refreshSuggestions(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collector', 'suggestions'] }),
  })

  const addSuggestion = (keyword: string) => {
    formInitialized.current = true
    const current = queryText
      .split(',')
      .map((q) => q.trim())
      .filter(Boolean)
    if (!current.includes(keyword)) {
      setQueryText([...current, keyword].join(', '))
    }
  }

  const busy = start.isPending || stop.isPending
  const hasQueries = queryText.split(',').some(q => q.trim().length > 0)
  const queryCount = data?.queries.length ?? 0
  const suggestions: KeywordSuggestion[] = suggestionsData?.suggestions ?? []

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radar className="h-4 w-4 text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-800">Collector</h2>
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
              running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500',
            )}
          >
            <span
              className={clsx(
                'h-1.5 w-1.5 rounded-full',
                running ? 'bg-green-500 animate-pulse' : 'bg-gray-400',
              )}
            />
            {isLoading ? 'loading…' : running ? 'running' : 'stopped'}
          </span>
        </div>
        {data && (queryCount > 0 || data.enqueued_total > 0) && (
          <p className="text-xs text-gray-400">
            {data.enqueued_total} new items queued
            {data.last_run ? ` · last run ${fmtDate(data.last_run)}` : ''}
          </p>
        )}
      </div>

      {data?.last_run && data.last_enqueued === 0 && <div className="mb-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-relaxed text-gray-600">
        The last cycle added no new items. Previously saved posts are skipped. Only selected platforms and content types are searched. Try different keywords, or stop collection and select more content types.
      </div>}

      <p className="text-xs text-gray-500 mb-2">
        Search terms to crawl (comma-separated). The collector searches YouTube
        and Telegram for these keywords, downloads the selected content kinds,
        and runs them through the analysis pipeline.
      </p>

      {running && queryCount === 0 && (
        <div className="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          The collector is on, but there are no search terms configured yet, so it will stay idle until keywords are added.
        </div>
      )}

      {data && queryCount > 0 && (
        <p className="mb-2 text-xs text-gray-400">
          {queryCount} active keyword{queryCount === 1 ? '' : 's'}{data.last_run ? ` · last run ${fmtDate(data.last_run)}` : ''}
        </p>
      )}

      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <span className="text-xs text-gray-400 mr-1">Platforms:</span>
        {ALL_PLATFORMS.map((p) => {
          const supported = (data?.supported_platforms ?? ['youtube']).includes(p.id)
          const on = platforms.includes(p.id)
          const canToggle = supported && !p.urlOnly
          if (p.urlOnly) return (
            <Link key={p.id} to={`/analyze?mode=link&platform=${p.id}`}
              title={`Analyze an individual ${p.label} video by pasting its link`}
              className="rounded-full px-2.5 py-0.5 text-xs font-medium border bg-white text-blue-600 border-gray-200 hover:bg-blue-50">
              {p.label} · paste link
            </Link>
          )
          return (
            <button
              key={p.id}
              type="button"
              disabled={running}
              onClick={() => supported ? togglePlatform(p.id) : setShowTelegramSetup(value => !value)}
              aria-expanded={!supported ? showTelegramSetup : undefined}
              title={
                p.urlOnly
                  ? 'URL analysis only — paste a link on the Analyze page'
                  : !supported
                    ? 'Configure AIMW_TELEGRAM_SESSION to enable'
                    : ''
              }
              className={clsx(
                'rounded-full px-2.5 py-0.5 text-xs font-medium border transition-colors',
                on && canToggle
                  ? 'bg-blue-50 text-blue-700 border-blue-200'
                  : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50',
                running && 'opacity-50 cursor-not-allowed',
              )}
            >
              {p.label}
              {p.urlOnly && ' ·url'}
              {!p.urlOnly && !supported && ' ·setup'}
            </button>
          )
        })}
      </div>

      <p className="mb-3 text-xs leading-relaxed text-gray-500">
        Keyword collection: YouTube and configured Telegram accounts. Instagram and TikTok use individual video links on Analyze content.
      </p>
      {showTelegramSetup && <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-relaxed text-blue-800">
        <p className="font-semibold">Connect Telegram for keyword searches</p>
        <p className="mt-1">Create your Telegram API credentials at my.telegram.org, then run the existing login script from the project folder:</p>
        <code className="my-2 block break-all">.\.venv\Scripts\python.exe scripts\telegram_login.py</code>
        <p>Save your API ID, API hash, and the generated session in the corresponding AIMW_TELEGRAM settings in .env. Restart the backend to enable Telegram, Photo, and Text collection. Keep credentials and the session private.</p>
      </div>}

      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <span className="text-xs text-gray-400 mr-1">Collect:</span>
        {ALL_CONTENT_TYPES.map((t) => {
          const on = contentTypes.includes(t.id)
          const supported = t.id === 'video' || platforms.includes('telegram')
          return (
            <button
              key={t.id}
              type="button"
              disabled={running || !supported}
              onClick={() => toggleContentType(t.id)}
              title={
                supported
                  ? `Collect ${t.label.toLowerCase()} content`
                  : 'Photo/text keyword collection requires Telegram'
              }
              className={clsx(
                'rounded-full px-2.5 py-0.5 text-xs font-medium border transition-colors',
                on
                  ? 'bg-violet-50 text-violet-700 border-violet-200'
                  : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50',
                (running || !supported) && 'opacity-50 cursor-not-allowed',
              )}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      <div className="mb-2 flex items-center gap-2">
        <span className="inline-flex items-center gap-1 text-xs text-gray-400">
          <MapPin className="h-3.5 w-3.5" />
          Region:
        </span>
        <select
          value={regionFocus}
          disabled={running || busy}
          onChange={(e) => { formInitialized.current = true; setRegionFocus(e.target.value) }}
          className="rounded border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
          title="Focus collector search expansion by place/language"
        >
          {REGION_OPTIONS.map((region) => (
            <option key={region.id} value={region.id}>
              {region.label}
            </option>
          ))}
        </select>
      </div>

      <label htmlFor="collector-queries" className="mb-2 block text-xs font-medium text-gray-700">Search keywords (required)</label>
      <div className="flex items-center gap-2">
        <input
          id="collector-queries"
          type="text"
          value={queryText}
          onChange={(e) => { formInitialized.current = true; setQueryText(e.target.value) }}
          aria-describedby="collector-query-help"
          placeholder="crypto investment scam, guaranteed profit, pyramid scheme"
          disabled={busy}
          className="flex-1 rounded border border-gray-200 px-3 py-1.5 text-sm text-gray-800 placeholder:text-gray-300 focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-200 disabled:opacity-50"
        />
        {running ? (
          <button
            onClick={() => stop.mutate()}
            disabled={busy}
            className="flex items-center gap-1.5 rounded bg-red-50 border border-red-200 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
          >
            {stop.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Square className="h-3.5 w-3.5" />
            )}
            Stop
          </button>
        ) : (
          <button
            onClick={() => start.mutate()}
            disabled={busy || !hasQueries}
            title={!hasQueries ? 'Enter at least one search keyword to enable Start' : 'Start collecting content for these keywords'}
            className="flex items-center gap-1.5 rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40 transition-colors"
          >
            {start.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Start
          </button>
        )}
      </div>
      <p id="collector-query-help" className="mt-2 text-xs text-gray-500">
        {!hasQueries
          ? 'Enter at least one keyword above to enable Start. The gray example text is a placeholder, not a saved search.'
          : 'Separate multiple keywords with commas. Click Start to search and collect matching content.'}
      </p>

      {/* Auto-suggested keywords */}
      {suggestions.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              <span className="text-xs font-medium text-gray-600">
                Suggested keywords
              </span>
              <span className="text-xs text-gray-400">
                (from {suggestionsData?.flagged_count ?? 0} flagged items)
              </span>
            </div>
            <button
              type="button"
              onClick={() => refreshSuggestions.mutate()}
              disabled={refreshSuggestions.isPending}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              <RefreshCw
                className={clsx(
                  'h-3 w-3',
                  refreshSuggestions.isPending && 'animate-spin',
                )}
              />
              Refresh
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {suggestions.slice(0, 12).map((s) => (
              <button
                key={s.keyword}
                type="button"
                onClick={() => addSuggestion(s.keyword)}
                title={s.reason || `${s.source} · confidence ${Math.round(s.confidence * 100)}%`}
                className="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2.5 py-0.5 text-xs text-amber-800 hover:bg-amber-100 transition-colors"
              >
                <Plus className="h-3 w-3" />
                {s.keyword}
              </button>
            ))}
          </div>
        </div>
      )}

      {(isError || start.isError || stop.isError) && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-red-600">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          {isError
            ? 'Could not reach the collector — is the backend running?'
            : 'Action failed. Try again.'}
        </div>
      )}
    </div>
  )
}
