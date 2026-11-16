import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, AlertOctagon, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '../api/client'
import { appendFeedback } from '../lib/feedbackStore'
import { qk } from '../lib/queryClient'

interface Props {
  reportId: string
}

type Verdict = 'confirmed' | 'dismissed' | 'escalated'

const VERDICTS: { id: Verdict; label: string; Icon: React.ElementType; color: string }[] = [
  { id: 'confirmed',  label: 'Confirm',  Icon: CheckCircle,   color: 'text-green-700 border-green-300 hover:bg-green-50'  },
  { id: 'dismissed',  label: 'Dismiss',  Icon: XCircle,       color: 'text-gray-600  border-gray-300  hover:bg-gray-50'   },
  { id: 'escalated',  label: 'Escalate', Icon: AlertOctagon,  color: 'text-red-700   border-red-300   hover:bg-red-50'    },
]

export function FeedbackBar({ reportId }: Props) {
  const [notes, setNotes] = useState('')
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null)
  const qc = useQueryClient()

  const mutation = useMutation({
    mutationFn: (verdict: Verdict) =>
      api.feedback.post({ report_id: reportId, verdict, notes: notes || undefined }),
    onSuccess: (data, verdict) => {
      appendFeedback(data, notes || undefined)
      setNotes('')
      setToast({ text: `Verdict "${verdict}" recorded (id ${data.feedback_id})`, ok: true })
      // Invalidate metrics so the regression suite count reflects the new case
      void qc.invalidateQueries({ queryKey: qk.metrics() })
      setTimeout(() => setToast(null), 4000)
    },
    onError: (err) => {
      setToast({ text: String(err), ok: false })
      setTimeout(() => setToast(null), 6000)
    },
  })

  const isPending = mutation.isPending

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Analyst Verdict</p>

      <div className="flex gap-2">
        {VERDICTS.map(({ id, label, Icon, color }) => (
          <button
            key={id}
            disabled={isPending}
            onClick={() => mutation.mutate(id)}
            className={clsx(
              'flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50',
              color,
            )}
          >
            {isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Icon className="h-3.5 w-3.5" />
            )}
            {label}
          </button>
        ))}
      </div>

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Optional notes for the analyst log…"
        rows={2}
        disabled={isPending}
        className="w-full rounded border border-gray-200 px-2.5 py-1.5 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:opacity-50"
      />

      {toast && (
        <div
          className={clsx(
            'rounded px-3 py-2 text-xs',
            toast.ok ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800',
          )}
        >
          {toast.text}
        </div>
      )}
    </div>
  )
}
