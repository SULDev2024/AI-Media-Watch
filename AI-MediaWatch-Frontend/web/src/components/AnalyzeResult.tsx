import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { clsx } from 'clsx'
import { Loader2, AlertCircle, ExternalLink, X, AlertTriangle } from 'lucide-react'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import type { EvidencePiece, ExtractedEntities, TranscriptSegment } from '../api/types'

type Tab = 'transcript' | 'ocr' | 'analysis' | 'verdict' | 'entities'

const TABS: { id: Tab; label: string }[] = [
  { id: 'transcript', label: 'Transcript' },
  { id: 'ocr', label: 'OCR Text' },
  { id: 'analysis', label: 'Speech Analysis' },
  { id: 'verdict', label: 'Final Verdict' },
  { id: 'entities', label: 'Entities' },
]

function headerColor(level: string): string {
  const l = level.toUpperCase()
  if (l === 'CRITICAL' || l === 'HIGH') return 'bg-red-50 text-red-700'
  if (l === 'MEDIUM') return 'bg-amber-50 text-amber-700'
  if (l === 'LOW') return 'bg-yellow-50 text-yellow-700'
  if (l === 'CLEAN') return 'bg-green-50 text-green-700'
  return 'bg-gray-50 text-gray-600'
}

function entityRows(e: ExtractedEntities): { label: string; values: string[] }[] {
  return [
    { label: 'Telegram handles', values: e.telegram_handles },
    { label: 'Telegram links', values: e.telegram_links },
    { label: 'Crypto wallets', values: e.crypto_wallets },
    { label: 'Phone numbers', values: e.phone_numbers },
    { label: 'Websites', values: e.websites },
    { label: 'Referral codes', values: e.referral_codes },
    { label: 'Profit claims', values: e.profit_claims },
  ].filter((r) => r.values.length > 0)
}

/**
 * Tabbed analysis result — 0-100 risk score header + Transcript / OCR Text /
 * Speech Analysis / Final Verdict / Entities tabs. Polls until the pipeline
 * attaches a package, then shows the LLM verdict and reasoning.
 */
export function AnalyzeResult({
  videoId,
  onDismiss,
  hideReportLink = false,
}: {
  videoId: string
  onDismiss?: () => void
  hideReportLink?: boolean
}) {
  const [tab, setTab] = useState<Tab>('analysis')
  const [elapsed, setElapsed] = useState(0)

  const videoQuery = useQuery({
    queryKey: qk.video(videoId),
    queryFn: () => api.videos.get(videoId),
    refetchInterval: (q) =>
      q.state.data?.status === 'failed' || (q.state.data?.package_ids?.length ?? 0) > 0 ? false : 2500,
  })
  const packageId = videoQuery.data?.package_ids?.[0]
  const reportQuery = useQuery({
    queryKey: qk.report(packageId ?? ''),
    queryFn: () => api.reports.get(packageId!),
    enabled: !!packageId,
  })

  const pkg = reportQuery.data?.package
  const label = videoQuery.data?.url ?? videoId
  const failed = videoQuery.data?.status === 'failed'
  const processing = !failed && (!packageId || reportQuery.isLoading)

  // Elapsed-time counter while pipeline is running
  useEffect(() => {
    if (!processing) return
    setElapsed(0)
    const id = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [processing])

  // Stage-aware progress message
  const hasRawPath = !!videoQuery.data?.raw_path
  const platform = videoQuery.data?.platform ?? ''
  const isRemoteVideo = ['youtube', 'tiktok', 'instagram'].includes(platform)
  function progressMessage(): string {
    if (elapsed < 3) return 'Submitting…'
    if (isRemoteVideo && !hasRawPath) {
      return `Downloading video (${elapsed}s)…`
    }
    if (!hasRawPath && elapsed < 15) return `Preparing (${elapsed}s)…`
    return `Transcribing / AI analysis (${elapsed}s)…`
  }
  const etaNote = isRemoteVideo && !pkg
    ? 'YouTube analysis takes 30–120 s (download + Whisper + LLM)'
    : null

  const level = reportQuery.data?.risk_level ?? 'UNKNOWN'
  const score100 = Math.round((reportQuery.data?.score ?? 0) * 100)
  const confidence = reportQuery.data?.confidence
  const markdown = reportQuery.data?.markdown ?? ''
  const judgeMode = reportQuery.data?.judge  // "llm" | "rules" | null

  // Derived tab content
  let transcript = ''
  try {
    const segs = JSON.parse(videoQuery.data?.transcript_segments ?? '[]') as TranscriptSegment[]
    transcript = segs.map((s) => s.text).join('\n')
  } catch {
    transcript = ''
  }
  const evidence: EvidencePiece[] = pkg?.evidence ?? []
  const ocrText = videoQuery.data?.ocr_text ?? evidence
    .filter((p) => p.source === 'ocr')
    .map((p) => p.raw_value)
    .join('\n')
  const flags = evidence.filter((p) => p.polarity === 'incriminating')
  const rawJson = pkg
    ? JSON.stringify(
        {
          risk_score: score100,
          risk_level: level,
          confidence,
          action: reportQuery.data?.action,
          signals_fired: flags.map((f) => f.indicator_type),
          entities: pkg.entities,
        },
        null,
        2,
      )
    : ''

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
        <p className="text-sm font-medium text-gray-700 truncate">{label}</p>
        <div className="flex items-center gap-2 shrink-0">
          {packageId && !hideReportLink && (
            <Link to={`/report/${videoId}`} className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800">
              Full report <ExternalLink className="h-3 w-3" />
            </Link>
          )}
          {onDismiss && (
            <button onClick={onDismiss} className="text-gray-300 hover:text-gray-600" aria-label="Dismiss result">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {videoQuery.isError && (
        <div className="flex items-center gap-2 px-4 py-4 text-sm text-red-600">
          <AlertCircle className="h-4 w-4" /> Failed to load — is the backend running?
        </div>
      )}

      {(failed || reportQuery.isError) && (
        <div role="alert" className="space-y-3 px-4 py-4 text-sm">
          <p className="flex items-center gap-2 text-red-600"><AlertCircle className="h-4 w-4 shrink-0" />
          {videoQuery.data?.error || 'Unable to load the analysis report. Please try again.'}
          </p>
          {failed && <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-gray-600">
            <p className="font-medium">Analysis could not be completed.</p>
            <p className="mt-1 text-xs leading-relaxed">
              {/403|forbidden/i.test(videoQuery.data?.error || '')
                ? 'The source rejected the media download. Update the YouTube downloader and its JavaScript solver, then restart the backend. Some sources may still require authentication.'
                : /not available|unavailable|private|removed|deleted/i.test(videoQuery.data?.error || '')
                  ? 'The source reports this video as unavailable. It may be removed, private, or restricted. Open the original link to check access, or choose another source.'
                  : 'Check the error above and the backend logs. No successful risk assessment was produced for this item.'}
            </p>
            <p className="mt-2 text-xs">You can also upload a local video file you have permission to use.</p>
            <Link to="/analyze" className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-blue-600">Upload content or try another link <ExternalLink size={13} /></Link>
          </div>}
        </div>
      )}

      {processing && !videoQuery.isError && (
        <div className="px-4 py-6 space-y-1.5">
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            <span>{progressMessage()}</span>
          </div>
          {etaNote && (
            <p className="text-xs text-gray-400 pl-6">{etaNote}</p>
          )}
        </div>
      )}

      {pkg && (
        <div className="p-4 space-y-4">
          {/* LLM-unavailable notice */}
          {judgeMode === 'rules' && (
            <div className="flex items-center gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              Model assessment unavailable — this result uses rules only.
            </div>
          )}

          {/* 0-100 risk score header */}
          <div className={clsx('rounded-lg px-5 py-4', headerColor(level))}>
            <p className="text-2xl font-semibold">
              Risk Score: {score100}/100 — {level} RISK
            </p>
            {confidence != null && (
              <p className="text-sm mt-1 opacity-80">AI confidence: {Math.round(confidence * 100)}%</p>
            )}
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={clsx(
                  'px-3 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors',
                  tab === t.id
                    ? 'border-red-500 text-red-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700',
                )}
              >
                {t.label}
                {t.id === 'entities' && entityRows(pkg.entities).length > 0 && (
                  <span className="ml-1 rounded-full bg-gray-200 px-1.5 text-xs">
                    {entityRows(pkg.entities).reduce((n, r) => n + r.values.length, 0)}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="text-sm text-gray-700 max-h-[28rem] overflow-y-auto">
            {tab === 'transcript' && (
              <pre className="whitespace-pre-wrap break-words font-sans">
                {transcript || 'No speech transcript (text or image input).'}
              </pre>
            )}

            {tab === 'ocr' && (
              <pre className="whitespace-pre-wrap break-words font-sans">
                {ocrText || (videoQuery.data?.ocr_text != null
                  ? 'No readable text detected in the sampled frames.'
                  : 'OCR text is unavailable for this analysis. Reanalyze to extract text.')}
              </pre>
            )}

            {tab === 'analysis' && (
              <div className="prose prose-sm prose-gray max-w-none">
                <ReactMarkdown>{markdown || 'No analysis available.'}</ReactMarkdown>
              </div>
            )}

            {tab === 'verdict' && (
              <div className="space-y-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Flags</p>
                  {flags.length === 0 ? (
                    <p className="text-gray-400">No incriminating flags.</p>
                  ) : (
                    <div className="space-y-1.5">
                      {flags.map((f, i) => (
                        <div key={i} className="rounded bg-amber-50 border border-amber-100 px-3 py-2">
                          <span className="font-medium text-amber-800">{f.indicator_type}:</span>{' '}
                          <span className="text-amber-700">{f.raw_value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Raw JSON</p>
                  <pre className="rounded bg-gray-900 text-gray-100 text-xs p-3 overflow-x-auto">{rawJson}</pre>
                </div>
              </div>
            )}

            {tab === 'entities' && (
              entityRows(pkg.entities).length === 0 ? (
                <p className="text-gray-400">No entities (wallets, handles, links, phones) detected.</p>
              ) : (
                <div className="space-y-3">
                  {entityRows(pkg.entities).map((r) => (
                    <div key={r.label}>
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{r.label}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {r.values.map((v, i) => (
                          <span key={i} className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700">{v}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>
        </div>
      )}
    </div>
  )
}
