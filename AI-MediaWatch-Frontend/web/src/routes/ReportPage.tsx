import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { AnalyzeResult } from '../components/AnalyzeResult'
import { FeedbackBar } from '../components/FeedbackBar'
import { ArrowLeft, ExternalLink, Download, Search } from 'lucide-react'

/**
 * Report page — the detail view reached from the queue. Uses the exact same
 * tabbed verdict view as the Analyze page (0-100 score, Transcript, OCR Text,
 * Speech Analysis, Final Verdict, Entities), plus an analyst feedback bar.
 */
export function ReportPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isReportId = id?.startsWith('rpt-') ?? false

  const directReportQuery = useQuery({
    queryKey: qk.report(id ?? ''),
    queryFn: () => api.reports.get(id!),
    enabled: !!id && isReportId,
  })
  const resolvedVideoId = isReportId ? directReportQuery.data?.package.video_id : id

  const videoQuery = useQuery({
    queryKey: qk.video(resolvedVideoId ?? ''),
    queryFn: () => api.videos.get(resolvedVideoId!),
    enabled: !!resolvedVideoId,
  })
  const packageId = directReportQuery.data?.package.report_id ?? videoQuery.data?.package_ids?.[0]
  const failed = directReportQuery.isError || videoQuery.isError

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3">
        <Link to="/queue" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors">
          <ArrowLeft className="h-4 w-4" />
          Queue
        </Link>
        <span className="text-gray-300">/</span>
        <span className="text-sm text-gray-700 font-medium truncate max-w-md">
          {videoQuery.data?.url ?? directReportQuery.data?.package.url ?? id}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {/* 9-agent investigation shortcut */}
          {resolvedVideoId && (
            <button
              onClick={() => navigate(`/investigate?vid=${resolvedVideoId}`)}
              className="flex items-center gap-1.5 rounded border border-purple-200 bg-purple-50 px-3 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100 transition-colors"
              title="Run 9-agent investigation on this video"
            >
              <Search className="h-3.5 w-3.5" />
              Investigate
            </button>
          )}
          {packageId && (
            <button
              onClick={async () => {
                const blob = await api.reports.exportPdf(packageId)
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `report_${packageId}.md`
                a.click()
                URL.revokeObjectURL(url)
              }}
              className="text-gray-400 hover:text-green-600 transition-colors"
              title="Download report"
            >
              <Download className="h-4 w-4" />
            </button>
          )}
          {(videoQuery.data?.url || directReportQuery.data?.package.url) && (
            <a
              href={videoQuery.data?.url ?? directReportQuery.data!.package.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-400 hover:text-blue-600 transition-colors"
              title="Open original URL"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
        </div>
      </div>

      {failed && (
        <div className="px-6 py-6 max-w-4xl mx-auto">
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Failed to load report. The item may no longer exist.
          </div>
        </div>
      )}

      {resolvedVideoId && !failed && (
        <div className="px-6 py-6 max-w-4xl mx-auto space-y-4">
          <AnalyzeResult videoId={resolvedVideoId} hideReportLink />
          {packageId && <FeedbackBar reportId={packageId} />}
        </div>
      )}
    </div>
  )
}
