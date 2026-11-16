import type { EvidencePiece } from '../api/types'
import { strengthWeight } from '../lib/format'

interface Props {
  evidence: EvidencePiece[]
}

export function ScoreBreakdown({ evidence }: Props) {
  const incriminating = evidence.filter((e) => e.polarity === 'incriminating')
  const mitigating = evidence.filter((e) => e.polarity === 'mitigating')

  const incScore = incriminating.reduce((s, e) => s + strengthWeight(e.strength), 0)
  const mitScore = mitigating.reduce((s, e) => s + strengthWeight(e.strength), 0)
  const total = incScore + mitScore || 1

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Score Breakdown</p>

      <div className="space-y-2">
        {/* Incriminating bar */}
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-red-600 font-medium">Incriminating ({incriminating.length})</span>
            <span className="text-gray-500">weight {incScore}</span>
          </div>
          <div className="h-2 w-full bg-gray-100 rounded-full">
            <div
              className="h-2 rounded-full bg-red-500"
              style={{ width: `${(incScore / total) * 100}%` }}
            />
          </div>
        </div>

        {/* Mitigating bar */}
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-green-600 font-medium">Mitigating ({mitigating.length})</span>
            <span className="text-gray-500">weight {mitScore}</span>
          </div>
          <div className="h-2 w-full bg-gray-100 rounded-full">
            <div
              className="h-2 rounded-full bg-green-500"
              style={{ width: `${(mitScore / total) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Indicator types summary */}
      <div className="flex flex-wrap gap-1 pt-1">
        {Array.from(new Set(evidence.map((e) => e.indicator_type))).map((t) => (
          <span
            key={t}
            className="inline-block rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600"
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  )
}
