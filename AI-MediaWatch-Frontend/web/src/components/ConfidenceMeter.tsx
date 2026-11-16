import { confidenceLabel, fmtPct, riskBadge } from '../lib/format'
import { AlertTriangle } from 'lucide-react'
import { clsx } from 'clsx'

interface Props {
  riskLevel: string
  score: number
  confidence?: number | null
  action?: string | null
}

export function ConfidenceMeter({ riskLevel, score, confidence, action }: Props) {
  const label = confidenceLabel(confidence)
  const pct = confidence != null ? confidence : null

  // Show "human review recommended" when action is analyst_review
  // OR when risk level is HIGH/CRITICAL and confidence is unknown/low
  const reviewRecommended =
    action === 'analyst_review' ||
    (confidence != null && confidence < 0.60 && ['HIGH', 'CRITICAL'].includes(riskLevel.toUpperCase()))

  const barWidth = pct != null ? Math.round(pct * 100) : 0

  // Gauge color based on confidence
  const barColor =
    pct == null
      ? 'bg-gray-300'
      : pct >= 0.75
        ? 'bg-green-500'
        : pct >= 0.60
          ? 'bg-yellow-500'
          : 'bg-red-400'

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Risk Assessment
        </span>
        <span className={clsx('text-xs font-bold px-2 py-0.5 rounded', riskBadge(riskLevel))}>
          {riskLevel}
        </span>
      </div>

      {/* Score */}
      <div className="flex items-baseline gap-1">
        <span className="text-3xl font-mono font-bold text-gray-800">
          {score >= 0 ? '+' : ''}{score.toFixed(2)}
        </span>
        <span className="text-xs text-gray-400 ml-1">signed score</span>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs text-gray-500">Confidence</span>
          <span className="text-xs font-medium text-gray-700">
            {pct != null ? (
              <>{fmtPct(pct)} — <strong>{label}</strong></>
            ) : (
              <span className="text-gray-400">not computed</span>
            )}
          </span>
        </div>
        <div className="h-2 w-full rounded-full bg-gray-100">
          {pct != null && (
            <div
              className={clsx('h-2 rounded-full transition-all', barColor)}
              style={{ width: `${barWidth}%` }}
            />
          )}
        </div>
      </div>

      {/* Human review pill */}
      {reviewRecommended && (
        <div className="flex items-center gap-1.5 rounded bg-amber-50 border border-amber-200 px-2.5 py-1.5 text-amber-800 text-xs font-medium">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
          Human review recommended
        </div>
      )}
    </div>
  )
}
