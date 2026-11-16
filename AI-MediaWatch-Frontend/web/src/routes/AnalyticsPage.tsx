import { useQuery } from '@tanstack/react-query'
import { BarChart3, TrendingUp, Shield, AlertTriangle } from 'lucide-react'
import { api } from '../api/client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'

const LEVEL_COLORS: Record<string, string> = {
  CRITICAL: '#dc2626',
  HIGH: '#f97316',
  MEDIUM: '#eab308',
  LOW: '#22c55e',
  NONE: '#6b7280',
}

export function AnalyticsPage() {
  const { data: videos } = useQuery({
    queryKey: ['videos'],
    queryFn: () => api.videos.list(200),
    refetchInterval: 30000,
  })

  const items = videos?.items ?? []
  const total = items.length

  // Risk level distribution
  const levelCounts: Record<string, number> = {}
  const platformCounts: Record<string, number> = {}
  const dailyCounts: Record<string, number> = {}

  for (const v of items) {
    const level = v.level || 'NONE'
    levelCounts[level] = (levelCounts[level] || 0) + 1

    const plat = v.platform || 'unknown'
    platformCounts[plat] = (platformCounts[plat] || 0) + 1

    const day = v.collected_at?.slice(0, 10) || 'unknown'
    dailyCounts[day] = (dailyCounts[day] || 0) + 1
  }

  const highRisk = (levelCounts['HIGH'] || 0) + (levelCounts['CRITICAL'] || 0)
  const scamRate = total > 0 ? ((highRisk / total) * 100).toFixed(1) : '0'

  const pieData = Object.entries(levelCounts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  const dailyData = Object.entries(dailyCounts)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-30)
    .map(([date, count]) => ({ date: date.slice(5), count }))

  const platformData = Object.entries(platformCounts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-2 mb-1">
        <BarChart3 className="h-5 w-5 text-blue-600" />
        <h1 className="text-xl font-semibold text-gray-900">Analytics</h1>
      </div>
      <p className="text-sm text-gray-500 mb-6">Overview of scam detection activity and trends.</p>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<Shield className="h-5 w-5 text-blue-500" />} label="Total Analyzed" value={total} />
        <StatCard icon={<AlertTriangle className="h-5 w-5 text-red-500" />} label="High Risk" value={highRisk} />
        <StatCard icon={<TrendingUp className="h-5 w-5 text-yellow-500" />} label="Scam Rate" value={`${scamRate}%`} />
        <StatCard icon={<BarChart3 className="h-5 w-5 text-green-500" />} label="Platforms" value={Object.keys(platformCounts).length} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Daily activity */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Daily Activity (last 30 days)</h3>
          {dailyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={dailyData}>
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-gray-400 text-center py-10">No data yet</p>
          )}
        </div>

        {/* Risk distribution */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Risk Level Distribution</h3>
          {pieData.length > 0 ? (
            <div className="flex items-center gap-4">
              <ResponsiveContainer width="50%" height={220}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" cx="50%" cy="50%" outerRadius={80} label={false}>
                    {pieData.map((entry) => (
                      <Cell key={entry.name} fill={LEVEL_COLORS[entry.name] || '#6b7280'} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2">
                {pieData.map((entry) => (
                  <div key={entry.name} className="flex items-center gap-2 text-sm">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: LEVEL_COLORS[entry.name] || '#6b7280' }}
                    />
                    <span className="text-gray-600">{entry.name}</span>
                    <span className="font-medium text-gray-900">{entry.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400 text-center py-10">No data yet</p>
          )}
        </div>

        {/* Platform breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">By Platform</h3>
          {platformData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={platformData} layout="vertical">
                <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={80} />
                <Tooltip />
                <Bar dataKey="value" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-gray-400 text-center py-10">No data yet</p>
          )}
        </div>

        {/* Top scam types (from evidence pieces) */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Detection Summary</h3>
          <div className="space-y-3">
            {Object.entries(levelCounts)
              .sort(([, a], [, b]) => b - a)
              .map(([level, count]) => {
                const pct = total > 0 ? (count / total) * 100 : 0
                return (
                  <div key={level}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-600">{level}</span>
                      <span className="font-medium">{count} ({pct.toFixed(0)}%)</span>
                    </div>
                    <div className="w-full bg-gray-100 rounded-full h-2">
                      <div
                        className="h-2 rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: LEVEL_COLORS[level] || '#6b7280',
                        }}
                      />
                    </div>
                  </div>
                )
              })}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center gap-2 mb-2">{icon}<span className="text-xs text-gray-500">{label}</span></div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
    </div>
  )
}
