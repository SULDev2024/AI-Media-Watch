import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { riskBadge, fmtDate } from '../lib/format'
import { clsx } from 'clsx'
import {
  ShieldCheck, Loader2, AlertCircle,
  Hash, FileText, Scale, User, ExternalLink, ChevronDown, ChevronRight,
  CheckCircle2, XCircle,
} from 'lucide-react'
import { useState } from 'react'
import type { CaseFile } from '../api/types'

function StatuteCard({ s }: { s: CaseFile['statute_violations'][number] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left"
      >
        <div>
          <p className="text-sm font-semibold text-red-800 dark:text-red-300">{s.short}</p>
          <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">{s.title}</p>
        </div>
        <div className="shrink-0 mt-0.5">
          {open ? (
            <ChevronDown className="h-4 w-4 text-red-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-red-500" />
          )}
        </div>
      </button>
      {open && s.article && (
        <div className="px-4 pb-3 border-t border-red-200 dark:border-red-900 pt-2">
          <p className="text-xs text-red-700 dark:text-red-400 whitespace-pre-wrap leading-relaxed">
            {s.article}
          </p>
          <p className="text-xs text-red-500 dark:text-red-600 mt-2">
            Jurisdiction: {s.jurisdiction}
          </p>
        </div>
      )}
    </div>
  )
}

function EvidenceRow({ entry, idx }: { entry: CaseFile['evidence_chain'][number]; idx: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2 bg-white dark:bg-gray-800 text-left hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors"
      >
        <span className="text-xs text-gray-400 font-mono w-5 shrink-0">{idx + 1}</span>
        <span className={clsx(
          'text-xs font-bold px-1.5 py-0.5 rounded shrink-0',
          entry.polarity === 'incriminating'
            ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
            : 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
        )}>
          {entry.polarity === 'incriminating' ? '▲' : '▼'}
        </span>
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300 flex-1 truncate">
          {entry.indicator_type}
        </span>
        <span className="text-xs text-gray-400 shrink-0">{entry.strength}</span>
        <span className="font-mono text-[10px] text-gray-300 dark:text-gray-600 shrink-0 hidden sm:block">
          {entry.hash.slice(0, 12)}…
        </span>
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-gray-400 shrink-0" />
        )}
      </button>
      {open && (
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 space-y-1.5">
          <p className="text-xs text-gray-600 dark:text-gray-400">
            <span className="font-medium">Value:</span>{' '}
            <span className="font-mono">{entry.raw_value}</span>
          </p>
          {entry.regulation_cite && (
            <p className="text-xs text-red-600 dark:text-red-400">
              <Scale className="h-3 w-3 inline mr-1" />
              {entry.regulation_cite}
            </p>
          )}
          <p className="text-[10px] font-mono text-gray-400 dark:text-gray-600 break-all">
            SHA-256: {entry.hash}
          </p>
        </div>
      )}
    </div>
  )
}

export function CasePage() {
  const { id } = useParams<{ id: string }>()

  const { data, isLoading, isError } = useQuery<CaseFile>({
    queryKey: ['case', id],
    queryFn: () => api.cases.get(id!),
    enabled: Boolean(id),
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Sealing case file…</span>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="p-6">
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700 text-sm">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to load case file. Is the backend running?
        </div>
      </div>
    )
  }

  const hasViolations = data.statute_violations.length > 0
  const totalEntities = Object.values(data.entities).flat().length

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck className="h-5 w-5 text-blue-500" />
            <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 font-mono">
              {data.case_id}
            </h1>
            <span className={clsx(
              'rounded px-2 py-0.5 text-xs font-bold',
              riskBadge(data.risk_level),
            )}>
              {data.risk_level}
            </span>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Sealed {fmtDate(data.sealed_at)} · {data.platform}
          </p>
        </div>

        <div className={clsx(
          'flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium',
          data.verify_ok
            ? 'bg-green-50 text-green-700 border border-green-200 dark:bg-green-950 dark:text-green-400 dark:border-green-800'
            : 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-950 dark:text-red-400 dark:border-red-800',
        )}>
          {data.verify_ok
            ? <CheckCircle2 className="h-4 w-4" />
            : <XCircle className="h-4 w-4" />}
          {data.verify_ok ? 'Chain verified' : 'Verification failed'}
        </div>
      </div>

      {/* URL */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3 flex items-center justify-between gap-3">
        <p className="text-sm text-gray-700 dark:text-gray-300 font-mono truncate">{data.url}</p>
        <a
          href={data.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-blue-500 hover:text-blue-600"
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>

      {/* Score row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Risk score', value: data.final_score.toFixed(3) },
          { label: 'Confidence', value: data.confidence != null ? (data.confidence * 100).toFixed(0) + '%' : '—' },
          { label: 'Evidence pieces', value: data.n_evidence_pieces },
          { label: 'Entities found', value: totalEntities },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3">
            <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">{value}</p>
          </div>
        ))}
      </div>

      {/* Chain root */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-4 py-3">
        <div className="flex items-center gap-2 mb-1">
          <Hash className="h-3.5 w-3.5 text-gray-400" />
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
            Tamper-evident chain root (SHA-256)
          </p>
        </div>
        <p className="font-mono text-xs text-gray-700 dark:text-gray-300 break-all">
          {data.chain_root}
        </p>
      </div>

      {/* Statute violations */}
      {hasViolations && (
        <section className="space-y-2">
          <div className="flex items-center gap-2">
            <Scale className="h-4 w-4 text-red-500" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Statute violations ({data.statute_violations.length})
            </h2>
          </div>
          {data.statute_violations.map((s) => (
            <StatuteCard key={s.id} s={s} />
          ))}
        </section>
      )}

      {/* Entities */}
      {totalEntities > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-2">
            <User className="h-4 w-4 text-gray-400" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Extracted entities
            </h2>
          </div>
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700">
            {Object.entries(data.entities).map(([kind, values]) =>
              values.length > 0 ? (
                <div key={kind} className="px-4 py-2.5 flex gap-3 items-start">
                  <span className="text-xs text-gray-500 dark:text-gray-400 w-36 shrink-0 pt-0.5">
                    {kind.replace(/_/g, ' ')}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {values.map((v, i) => (
                      <span key={i} className="rounded bg-gray-100 dark:bg-gray-700 px-2 py-0.5 text-xs font-mono text-gray-700 dark:text-gray-300">
                        {v}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null,
            )}
          </div>
        </section>
      )}

      {/* Evidence chain */}
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Evidence chain ({data.evidence_chain.length} pieces)
          </h2>
          <span className="text-xs text-gray-400">— click to expand</span>
        </div>
        <div className="space-y-1">
          {data.evidence_chain.map((entry, i) => (
            <EvidenceRow key={i} entry={entry} idx={i} />
          ))}
        </div>
      </section>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-gray-200 dark:border-gray-700">
        <Link
          to={`/report/${data.report_id}`}
          className="text-sm text-blue-500 hover:text-blue-600 flex items-center gap-1"
        >
          ← View full report
        </Link>
        <p className="text-xs text-gray-400">
          Report: <span className="font-mono">{data.report_id}</span>
        </p>
      </div>
    </div>
  )
}
