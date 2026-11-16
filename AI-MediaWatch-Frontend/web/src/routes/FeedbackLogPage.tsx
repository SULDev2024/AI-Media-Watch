import { useState, useEffect } from 'react'
import { loadFeedbackLog } from '../lib/feedbackStore'
import { api } from '../api/client'
import { fmtDate } from '../lib/format'
import { clsx } from 'clsx'
import { Trash2, MessageSquare, RefreshCw } from 'lucide-react'
import type { FeedbackLogEntry } from '../api/types'

const VERDICT_STYLE: Record<string, string> = {
  confirmed:  'bg-green-50 text-green-700 border-green-200',
  dismissed:  'bg-gray-50 text-gray-600 border-gray-200',
  escalated:  'bg-red-50 text-red-700 border-red-200',
}

function Entry({ entry }: { entry: FeedbackLogEntry }) {
  return (
    <div className={clsx(
      'rounded-lg border px-4 py-3 space-y-1',
      VERDICT_STYLE[entry.verdict] ?? 'bg-gray-50 border-gray-200 text-gray-600',
    )}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold capitalize text-sm">{entry.verdict}</span>
          <span className="text-xs font-mono opacity-60">{entry.feedback_id}</span>
        </div>
        <span className="text-xs opacity-60 shrink-0">{fmtDate(entry.saved_at)}</span>
      </div>
      <p className="text-xs opacity-70">Report: {entry.report_id}</p>
      {entry.notes && (
        <p className="text-xs italic opacity-80 border-t border-current border-opacity-10 pt-1 mt-1">
          {entry.notes}
        </p>
      )}
    </div>
  )
}

function mergeEntries(local: FeedbackLogEntry[], remote: FeedbackLogEntry[]): FeedbackLogEntry[] {
  const seen = new Set<string>()
  const merged: FeedbackLogEntry[] = []
  for (const entry of [...remote, ...local]) {
    const key = `${entry.feedback_id}-${entry.report_id}`
    if (!seen.has(key)) {
      seen.add(key)
      merged.push(entry)
    }
  }
  merged.sort((a, b) => (b.saved_at || '').localeCompare(a.saved_at || ''))
  return merged
}

export function FeedbackLogPage() {
  const [log, setLog] = useState<FeedbackLogEntry[]>(() => loadFeedbackLog())
  const [loading, setLoading] = useState(false)

  async function fetchFromApi() {
    setLoading(true)
    try {
      const resp = await api.feedback.list()
      const local = loadFeedbackLog()
      setLog(mergeEntries(local, resp.items))
    } catch {
      setLog(loadFeedbackLog())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchFromApi() }, [])

  function clearLog() {
    if (confirm('Clear the local feedback log? This cannot be undone.')) {
      localStorage.removeItem('aimw_feedback_log')
      fetchFromApi()
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Feedback Log</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Analyst verdicts — {log.length} entries
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchFromApi}
            disabled={loading}
            className="flex items-center gap-1.5 rounded border border-gray-200 dark:border-gray-600 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
            Refresh
          </button>
          {log.length > 0 && (
            <button
              onClick={clearLog}
              className="flex items-center gap-1.5 rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear local
            </button>
          )}
        </div>
      </div>

      {log.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 py-16 text-center">
          <MessageSquare className="h-8 w-8 text-gray-300 dark:text-gray-500 mx-auto mb-3" />
          <p className="text-sm text-gray-500 dark:text-gray-400">No feedback recorded yet.</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
            Open a report and submit a verdict to see entries here.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {log.map((entry, i) => (
            <Entry key={`${entry.feedback_id}-${i}`} entry={entry} />
          ))}
        </div>
      )}

      <p className="text-xs text-gray-400 dark:text-gray-500 text-center pt-4">
        Showing server + local entries. Local-only verdicts clear with the browser.
      </p>
    </div>
  )
}
