import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { Loader2, AlertCircle, FlaskConical } from 'lucide-react'

const LEVEL_COLOR: Record<string, string> = {
  CLEAN:    '#22c55e',
  LOW:      '#84cc16',
  MEDIUM:   '#f59e0b',
  HIGH:     '#f97316',
  CRITICAL: '#ef4444',
  UNKNOWN:  '#94a3b8',
}

const LABEL_COLOR: Record<string, string> = {
  benign:    '#22c55e',
  gambling:  '#f59e0b',
  pyramid:   '#f97316',
  scam:      '#ef4444',
  uncertain: '#94a3b8',
}

function StatBox({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="text-3xl font-bold font-mono tabular-nums text-gray-800">{value}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

function GaugeStat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center gap-1 flex-1">
      <div className="text-3xl font-bold font-mono tabular-nums" style={{ color }}>
        {Math.round(value * 100)}%
      </div>
      <p className="text-xs text-gray-500 text-center">{label}</p>
    </div>
  )
}

function ConfusionMatrix({ matrix }: { matrix: Record<string, Record<string, number>> }) {
  const levels = ['CLEAN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN']
  const labels = Object.keys(matrix).sort()
  if (labels.length === 0) return null

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-4">
        Confusion Matrix (expected → predicted)
      </p>
      <div className="overflow-x-auto">
        <table className="text-xs w-full">
          <thead>
            <tr>
              <th className="py-1 px-2 text-left text-gray-400 font-normal">Expected \</th>
              {levels.map((l) => (
                <th
                  key={l}
                  className="py-1 px-2 text-center font-semibold"
                  style={{ color: LEVEL_COLOR[l] ?? '#94a3b8' }}
                >
                  {l}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {labels.map((label) => (
              <tr key={label}>
                <td
                  className="py-1.5 px-2 font-semibold whitespace-nowrap"
                  style={{ color: LABEL_COLOR[label] ?? '#6b7280' }}
                >
                  {label}
                </td>
                {levels.map((lvl) => {
                  const count = matrix[label]?.[lvl] ?? 0
                  return (
                    <td
                      key={lvl}
                      className="py-1.5 px-2 text-center tabular-nums"
                      style={{ color: count > 0 ? '#374151' : '#d1d5db' }}
                    >
                      {count}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PerClassTable({ perClass }: { perClass: Record<string, Record<string, number>> }) {
  const labels = Object.keys(perClass).sort()
  if (labels.length === 0) return null

  function prec(c: Record<string, number>) {
    return (c.tp + c.fp) > 0 ? c.tp / (c.tp + c.fp) : 0
  }
  function rec(c: Record<string, number>) {
    return (c.tp + c.fn) > 0 ? c.tp / (c.tp + c.fn) : 0
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Per-label breakdown
        </p>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            {['Label', 'TP', 'FP', 'FN', 'TN', 'Precision', 'Recall'].map((h) => (
              <th
                key={h}
                className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {labels.map((label) => {
            const c = perClass[label]
            return (
              <tr key={label}>
                <td className="px-4 py-2">
                  <span
                    className="rounded px-1.5 py-0.5 text-xs font-semibold text-white"
                    style={{ background: LABEL_COLOR[label] ?? '#94a3b8' }}
                  >
                    {label}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-green-600 font-mono">{c.tp}</td>
                <td className="px-4 py-2 text-xs text-orange-600 font-mono">{c.fp}</td>
                <td className="px-4 py-2 text-xs text-red-600 font-mono">{c.fn}</td>
                <td className="px-4 py-2 text-xs text-gray-400 font-mono">{c.tn}</td>
                <td className="px-4 py-2 text-xs font-mono tabular-nums">
                  {Math.round(prec(c) * 100)}%
                </td>
                <td className="px-4 py-2 text-xs font-mono tabular-nums">
                  {Math.round(rec(c) * 100)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
      <FlaskConical className="h-8 w-8 text-gray-300 mx-auto mb-3" />
      <p className="text-sm font-medium text-gray-500">No validation cases yet</p>
      <p className="text-xs text-gray-400 mt-1">
        Run <code className="bg-gray-100 px-1 rounded">aimw validation collect &lt;url&gt; --label &lt;label&gt;</code> to register cases
      </p>
    </div>
  )
}

export function ValidationPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.validation(),
    queryFn: () => api.validation.summary(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Real-World Validation</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Scoring engine on labelled real-world videos — full corpus below, with the
          held-out (never-trained-on) slice called out separately.
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20 text-gray-400 gap-2">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading validation metrics…</span>
        </div>
      )}

      {isError && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700 text-sm">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to load validation data — is the backend running?
        </div>
      )}

      {data && data.n_total === 0 && <EmptyState />}

      {data && data.n_total > 0 && (
        <>
          {/* Case count row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatBox label="Total cases" value={data.n_total} />
            <StatBox label="Evaluated" value={data.n_evaluated} sub="binary metrics" />
            <StatBox label="Pending" value={data.n_pending} sub="not yet processed" />
            <StatBox label="Errors" value={data.n_error} sub="pipeline failures" />
          </div>

          {/* P/R/F1 panel */}
          {data.n_evaluated > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-6">
                Binary Classification  (HIGH/CRITICAL = positive)
              </p>
              <div className="flex items-center gap-8 flex-wrap">
                <div className="flex flex-1 gap-6 min-w-64">
                  <GaugeStat label="Precision" value={data.precision} color="#3b82f6" />
                  <GaugeStat label="Recall"    value={data.recall}    color="#8b5cf6" />
                  <GaugeStat label="F1"        value={data.f1}        color="#22c55e" />
                  <GaugeStat label="FPR"       value={data.fpr}       color="#f97316" />
                  <GaugeStat label="FNR"       value={data.fnr}       color="#ef4444" />
                </div>
                <div className="text-right shrink-0 text-sm text-gray-600 space-y-0.5">
                  <p>TP <span className="font-mono font-bold text-green-600">{data.tp}</span></p>
                  <p>FP <span className="font-mono font-bold text-orange-600">{data.fp}</span></p>
                  <p>FN <span className="font-mono font-bold text-red-600">{data.fn}</span></p>
                  <p>TN <span className="font-mono font-bold text-gray-400">{data.tn}</span></p>
                </div>
              </div>
            </div>
          )}

          {/* Held-out generalization — the honest real-world number */}
          {data.holdout && (
            <div className="rounded-lg border-2 border-violet-200 bg-violet-50 p-6">
              <p className="text-xs font-semibold uppercase tracking-wide text-violet-600 mb-1">
                Held-out generalization · {data.holdout.n} unseen videos
              </p>
              <p className="text-xs text-violet-500 mb-5">
                Cases the model never trained on — the honest measure of real-world performance.
              </p>
              <div className="flex items-center gap-8 flex-wrap">
                <div className="flex flex-1 gap-6 min-w-64">
                  <GaugeStat label="Precision" value={data.holdout.precision} color="#7c3aed" />
                  <GaugeStat label="Recall"    value={data.holdout.recall}    color="#7c3aed" />
                  <GaugeStat label="F1"        value={data.holdout.f1}        color="#7c3aed" />
                </div>
                <div className="text-right shrink-0 text-sm text-gray-600 space-y-0.5">
                  <p>TP <span className="font-mono font-bold text-green-600">{data.holdout.tp}</span></p>
                  <p>FP <span className="font-mono font-bold text-orange-600">{data.holdout.fp}</span></p>
                  <p>FN <span className="font-mono font-bold text-red-600">{data.holdout.fn}</span></p>
                  <p>TN <span className="font-mono font-bold text-gray-400">{data.holdout.tn}</span></p>
                </div>
              </div>
            </div>
          )}

          {/* Confusion matrix */}
          <ConfusionMatrix matrix={data.confusion_matrix} />

          {/* Per-label table */}
          {Object.keys(data.per_class).length > 0 && (
            <PerClassTable perClass={data.per_class} />
          )}
        </>
      )}
    </div>
  )
}
