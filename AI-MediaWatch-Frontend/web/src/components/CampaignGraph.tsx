import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { CytoscapeElement } from '../api/types'
import { GitFork } from 'lucide-react'

interface Props {
  nodes: CytoscapeElement[]
  edges: CytoscapeElement[]
  onNodeClick: (id: string) => void
}

function shortLabel(raw: string): string {
  // Prefer the human label; strip any "video|" / "entity|kind|" id prefix.
  const v = raw.includes('|') ? raw.split('|').pop()! : raw
  if (v.length > 18) return v.slice(0, 16) + '…'
  return v
}

const STYLES: cytoscape.StylesheetStyle[] = [
  // Default node
  {
    selector: 'node',
    style: {
      label: 'data(shortLabel)',
      'background-color': '#6366f1',
      color: '#475569',
      'font-size': 9,
      'text-valign': 'bottom',
      'text-margin-y': 6,
      'text-wrap': 'ellipsis',
      'text-max-width': '80px',
      width: 28,
      height: 28,
    },
  },
  // Entity node (diamond, amber)
  {
    selector: 'node[kind = "entity"]',
    style: {
      'background-color': '#f59e0b',
      shape: 'diamond',
      width: 22,
      height: 22,
      color: '#92400e',
      'font-size': 8,
    },
  },
  // Default edge (entity connection)
  {
    selector: 'edge',
    style: {
      width: 1.5,
      'line-color': '#cbd5e1',
      'target-arrow-color': '#94a3b8',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      opacity: 0.6,
    },
  },
  // Fingerprint edge — entity overlap (orange solid)
  {
    selector: 'edge[link_type = "entity_match"]',
    style: {
      width: 3,
      'line-color': '#f97316',
      'target-arrow-color': '#f97316',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'line-style': 'solid',
      opacity: 0.85,
    },
  },
  // Fingerprint edge — content similarity (orange dashed)
  {
    selector: 'edge[link_type = "content_match"]',
    style: {
      width: 2.5,
      'line-color': '#fb923c',
      'target-arrow-color': '#fb923c',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'line-style': 'dashed',
      'line-dash-pattern': [6, 3],
      opacity: 0.80,
    },
  },
  // Selected
  {
    selector: ':selected',
    style: {
      'background-color': '#1d4ed8',
      'border-color': '#93c5fd',
      'border-width': 3,
    },
  },
  {
    selector: 'node:active',
    style: { 'overlay-opacity': 0.1 },
  },
]

export function CampaignGraph({ nodes, edges, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const enrichedNodes = nodes.map((n) => ({
      ...n,
      data: { ...n.data, shortLabel: shortLabel(String(n.data.label ?? n.data.id)) },
    }))

    const cy = cytoscape({
      container: containerRef.current,
      elements: { nodes: enrichedNodes, edges } as cytoscape.ElementsDefinition,
      style: STYLES,
      layout: {
        name: 'cose',
        animate: false,
        nodeRepulsion: () => 8000,
        idealEdgeLength: () => 120,
        edgeElasticity: () => 100,
        gravity: 0.25,
        numIter: 500,
        padding: 40,
        nodeDimensionsIncludeLabels: true,
      } as cytoscape.LayoutOptions,
      minZoom: 0.15,
      maxZoom: 5,
      wheelSensitivity: 0.25,
    })

    cy.on('tap', 'node', (e: cytoscape.EventObject) => {
      onNodeClick(e.target.id() as string)
    })

    cyRef.current = cy
    return () => {
      cy.destroy()
      cyRef.current = null
    }
  }, [nodes, edges, onNodeClick])

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-2">
        <GitFork className="h-10 w-10" />
        <p className="text-sm">No graph data — run a recompute to build connections.</p>
      </div>
    )
  }

  return (
    <div className="relative h-full">
      <div ref={containerRef} className="h-full w-full" />

      <div className="absolute bottom-4 left-4 bg-white dark:bg-gray-900 bg-opacity-95 border border-gray-200 dark:border-gray-700 rounded-lg p-3 text-xs space-y-1.5 shadow-sm">
        <p className="font-semibold text-gray-600 dark:text-gray-300 mb-1">Legend</p>

        <div className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full bg-indigo-500 shrink-0" />
          <span className="text-gray-600 dark:text-gray-400">Video node — click to open report</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 bg-amber-400 shrink-0" style={{ transform: 'rotate(45deg)' }} />
          <span className="text-gray-600 dark:text-gray-400">Shared entity</span>
        </div>

        <div className="border-t border-gray-100 dark:border-gray-700 pt-1.5 mt-1 space-y-1.5">
          <p className="text-gray-400 dark:text-gray-500 font-medium">Fingerprint links</p>
          <div className="flex items-center gap-2">
            <div className="w-8 h-0.5 bg-orange-500 shrink-0" />
            <span className="text-gray-600 dark:text-gray-400">Shared entity values</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-0.5 shrink-0" style={{
              backgroundImage: 'repeating-linear-gradient(90deg, #fb923c 0, #fb923c 6px, transparent 6px, transparent 9px)',
            }} />
            <span className="text-gray-600 dark:text-gray-400">Same scripted pitch</span>
          </div>
        </div>

        <p className="text-gray-400 dark:text-gray-500 mt-1 pt-1 border-t border-gray-100 dark:border-gray-700">
          Scroll to zoom · drag to pan
        </p>
      </div>
    </div>
  )
}
