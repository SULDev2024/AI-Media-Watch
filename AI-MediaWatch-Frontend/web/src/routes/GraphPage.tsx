import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useCallback } from 'react'
import { api } from '../api/client'
import { qk } from '../lib/queryClient'
import { CampaignGraph } from '../components/CampaignGraph'
import { Loader2, AlertCircle, GitFork } from 'lucide-react'
import type { CytoscapeElement } from '../api/types'

export function GraphPage() {
  const navigate = useNavigate()

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.graph(),
    queryFn: () => api.graph.get(),
    staleTime: 60_000,
  })

  const { data: campaigns } = useQuery({
    queryKey: qk.campaigns(),
    queryFn: () => api.graph.campaigns(),
    staleTime: 60_000,
  })

  const onNodeClick = useCallback(
    (id: string) => {
      if (data) {
        const node = data.nodes.find((n: CytoscapeElement) => n.data.id === id)
        // Only video nodes open a report; entity nodes are not reports.
        if (node?.data?.kind === 'video') {
          const rid = id.includes('|') ? id.split('|').pop()! : id
          void navigate(`/report/${rid}`)
        }
      }
    },
    [data, navigate],
  )

  const nodes: CytoscapeElement[] = data?.nodes ?? []
  const edges: CytoscapeElement[] = data?.edges ?? []

  const videoNodes = nodes.filter(n => n.data.kind === 'video').length
  const entityNodes = nodes.filter(n => n.data.kind === 'entity').length
  const fingerprintEdges = edges.filter(e => e.data.kind === 'fingerprint').length
  const campaignCount = campaigns?.items?.length ?? 0

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="shrink-0 px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Campaign Graph</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            {videoNodes} videos · {entityNodes} entities · {edges.length} edges
            {fingerprintEdges > 0 && (
              <span className="ml-2 text-orange-500 font-medium">
                · {fingerprintEdges} fingerprint links
              </span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-4">
          {campaignCount > 0 && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 px-3 py-1.5">
              <GitFork className="h-4 w-4 text-red-500" />
              <span className="text-sm font-semibold text-red-700 dark:text-red-400">
                {campaignCount} campaign{campaignCount !== 1 ? 's' : ''} detected
              </span>
            </div>
          )}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading graph…
            </div>
          )}
        </div>
      </div>

      {/* Error */}
      {isError && (
        <div className="m-6 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700 text-sm">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to load graph data — is the backend running?
        </div>
      )}

      {/* Graph canvas */}
      <div className="flex-1 min-h-0">
        {!isLoading && !isError && (
          <CampaignGraph
            nodes={nodes}
            edges={edges}
            onNodeClick={onNodeClick}
          />
        )}
      </div>
    </div>
  )
}
