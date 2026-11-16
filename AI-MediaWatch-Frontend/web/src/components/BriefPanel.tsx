import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { EvidencePiece } from '../api/types'
import { polarityColor, fmtTimestamp, capitalize } from '../lib/format'
import { clsx } from 'clsx'

interface Props {
  evidence: EvidencePiece[]
  markdown: string
}

type Tab = 'prosecutor' | 'defense' | 'report'

function PieceRow({ piece }: { piece: EvidencePiece }) {
  const color = polarityColor(piece.polarity)
  const isValidated = piece.regulation_ref != null
  return (
    <div
      className={clsx(
        'rounded border-l-4 bg-white p-3 text-sm space-y-0.5',
        isValidated ? 'border-green-400 bg-green-50' : 'border-gray-200',
      )}
      style={{ borderLeftColor: isValidated ? undefined : color }}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-gray-800 flex-1">{piece.raw_value}</span>
        <div className="flex gap-1 shrink-0">
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            {piece.strength}
          </span>
          {piece.timestamp != null && (
            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">
              {fmtTimestamp(piece.timestamp)}
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-gray-500">
        {capitalize(piece.indicator_type)} · {piece.source}
        {piece.corroborated_by.length > 0 && (
          <> · corroborated by {piece.corroborated_by.join(', ')}</>
        )}
      </p>
      {piece.content && piece.content !== piece.raw_value && (
        <p className="text-xs text-gray-600 italic">{piece.content}</p>
      )}
      {isValidated && (
        <p className="text-xs font-medium text-green-700">
          ✓ Valid discount — {piece.regulation_ref}
        </p>
      )}
    </div>
  )
}

export function BriefPanel({ evidence, markdown }: Props) {
  const [tab, setTab] = useState<Tab>('prosecutor')

  const incriminating = evidence.filter((e) => e.polarity === 'incriminating')
  const mitigating = evidence.filter((e) => e.polarity === 'mitigating')

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'prosecutor', label: 'Prosecutor', count: incriminating.length },
    { id: 'defense',    label: 'Defense',    count: mitigating.length    },
    { id: 'report',     label: 'Full Report'                             },
  ]

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 bg-gray-50">
        {tabs.map(({ id, label, count }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px',
              tab === id
                ? 'border-blue-600 text-blue-700 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-100',
            )}
          >
            {label}
            {count != null && (
              <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-xs leading-none">
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-4 max-h-96 overflow-y-auto scrollbar-thin space-y-2">
        {tab === 'prosecutor' && (
          incriminating.length === 0
            ? <p className="text-sm text-gray-400">No incriminating evidence found.</p>
            : incriminating
                .sort((a, b) => (b.timestamp ?? -1) - (a.timestamp ?? -1))
                .map((e, i) => <PieceRow key={i} piece={e} />)
        )}

        {tab === 'defense' && (
          mitigating.length === 0
            ? <p className="text-sm text-gray-400">No mitigating evidence found.</p>
            : mitigating
                .sort((a, b) => {
                  // Valid discounts (regulation_ref set) float to the top
                  const aV = a.regulation_ref != null ? 1 : 0
                  const bV = b.regulation_ref != null ? 1 : 0
                  return bV - aV
                })
                .map((e, i) => <PieceRow key={i} piece={e} />)
        )}

        {tab === 'report' && (
          <div className="prose prose-sm prose-gray max-w-none">
            <ReactMarkdown>{markdown}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
