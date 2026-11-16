import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { Link } from 'react-router-dom'
import { Loader2, AlertCircle, TrendingUp, Info } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import type { PrecisionRecallCase } from '../api/types'

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

function F1Gauge({ f1 }: { f1: number }) {
  const strokeColor = f1 >= 0.8 ? '#22c55e' : f1 >= 0.6 ? '#f59e0b' : '#ef4444'
  const circumference = 2 * Math.PI * 44
  const dash = (f1 * circumference).toFixed(1)
  return (
    <div className="flex flex-col items-center relative" style={{ width: 120, height: 120 }}>
      <svg width={120} height={120} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={60} cy={60} r={44} stroke="#e5e7eb" strokeWidth={10} fill="none" />
        <circle
          cx={60} cy={60} r={44}
          stroke={strokeColor}
          strokeWidth={10}
          fill="none"
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold font-mono" style={{ color: strokeColor }}>
          {Math.round(f1 * 100)}%
        </span>
        <span className="text-xs text-gray-400">F1</span>
      </div>
    </div>
  )
}

const LEVEL_COLOR: Record<string, string> = {
  NONE:     '#94a3b8',
  LOW:      '#22c55e',
  MEDIUM:   '#f59e0b',
  HIGH:     '#f97316',
  CRITICAL: '#ef4444',
  UNKNOWN:  '#cbd5e1',
}

export function MetricsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.metrics(),
    queryFn: () => api.metrics.precisionRecall(),
    staleTime: 60_000,
  })

  // Per-level accuracy for bar chart
  const levelStats = (() => {
    if (!data) return []
    const groups: Record<string, { total: number; correct: number }> = {}
    for (const c of data.cases as PrecisionRecallCase[]) {
      const level = c.expected_level
      if (!groups[level]) groups[level] = { total: 0, correct: 0 }
      groups[level].total++
      if (c.is_correct_level) groups[level].correct++
    }
    return Object.entries(groups).map(([level, { total, correct }]) => ({
      level,
      accuracy: total > 0 ? correct / total : 0,
      total,
    }))
  })()

  // Count exact matches
  const exactLevelMatches = data
    ? (data.cases as PrecisionRecallCase[]).filter((c) => c.is_correct_level).length
    : 0

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Ambiguity Metrics</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Binary scam-vs-not classification on the in-sample regression corpus
        </p>
      </div>

      {/* Honesty banner — these are in-sample, not held-out numbers */}
      <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
        <Info className="h-4 w-4 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p>
            These scores are the <strong>in-sample regression suite</strong> — a small
            set of hand-built adversarial cases used during development as a sanity
            check. The headline is <strong>binary</strong> (≥MEDIUM = scam): a case can
            pass binary yet still miss its exact level, which is why
            per-level accuracy below is lower.
          </p>
          <p>
            For <strong>held-out, real-world performance</strong> on labelled videos
            the model never trained on, see the{' '}
            <Link to="/validation" className="font-semibold underline">Validation</Link> page.
          </p>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20 text-gray-400 gap-2">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading metrics…</span>
        </div>
      )}

      {isError && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700 text-sm">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to load metrics — is the backend running?
        </div>
      )}

      {data && (
        <>
          {/* Top-level P/R/F1 */}
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-6">
              Classification Performance (≥MEDIUM = positive)
            </p>
            <div className="flex items-center gap-8">
              <F1Gauge f1={data.f1} />
              <div className="flex flex-1 gap-4">
                <GaugeStat label="Precision" value={data.precision} color="#3b82f6" />
                <GaugeStat label="Recall"    value={data.recall}    color="#8b5cf6" />
                <GaugeStat label="F1"        value={data.f1}        color="#22c55e" />
              </div>
              <div className="text-right shrink-0">
                <p className="text-3xl font-bold text-gray-800">{data.n_cases}</p>
                <p className="text-xs text-gray-400">total cases</p>
                <p className="text-sm text-gray-600 mt-1">
                  {exactLevelMatches} / {data.n_cases} exact level
                </p>
              </div>
            </div>
          </div>

          {/* Per-level bar */}
          {levelStats.length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-4">
                Per-level accuracy
              </p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={levelStats} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="level" tick={{ fontSize: 12 }} />
                  <YAxis domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => [`${Math.round(v * 100)}%`, 'Accuracy']} />
                  <Bar dataKey="accuracy" radius={[4, 4, 0, 0]}>
                    {levelStats.map(({ level }) => (
                      <Cell key={level} fill={LEVEL_COLOR[level] ?? '#94a3b8'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Case table */}
          <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-gray-400" />
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Case Detail ({data.cases.length})
              </p>
            </div>
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-gray-50">
                  <tr>
                    {['ID', 'Expected', 'Predicted', 'Exp. Action', 'Pred. Action', 'Level ✓', 'Action ✓'].map((h) => (
                      <th key={h} className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(data.cases as PrecisionRecallCase[]).map((c, i) => (
                    <tr key={i} className={c.is_correct_level && c.is_correct_action ? '' : 'bg-red-50'}>
                      <td className="px-4 py-2 font-mono text-xs text-gray-500 whitespace-nowrap">
                        {c.case_id?.slice(0, 8) ?? '—'}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className="rounded px-1.5 py-0.5 text-xs font-bold text-white"
                          style={{ background: LEVEL_COLOR[c.expected_level] ?? '#94a3b8' }}
                        >
                          {c.expected_level}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className="rounded px-1.5 py-0.5 text-xs font-bold text-white"
                          style={{ background: LEVEL_COLOR[c.predicted_level] ?? '#94a3b8' }}
                        >
                          {c.predicted_level}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-600">{c.expected_action}</td>
                      <td className="px-4 py-2 text-xs text-gray-600">{c.predicted_action}</td>
                      <td className="px-4 py-2 text-xs">
                        {c.is_correct_level
                          ? <span className="text-green-600 font-medium">✓</span>
                          : <span className="text-red-600 font-medium">✗</span>}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {c.is_correct_action
                          ? <span className="text-green-600 font-medium">✓</span>
                          : <span className="text-red-600 font-medium">✗</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
