import { useRef, useCallback, useState } from 'react'
import type { EvidencePiece } from '../api/types'
import { polarityColor, fmtTimestamp } from '../lib/format'

interface Props {
  evidence: EvidencePiece[]
  currentTime: number
  duration: number
  onSeek: (t: number) => void
}

interface Tooltip {
  x: number
  y: number
  piece: EvidencePiece
}

const HEIGHT = 56
const TICK_HEIGHT = 28

export function EvidenceTimeline({ evidence, currentTime, duration, onSeek }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const [width, setWidth] = useState(600)

  const measuredRef = useCallback((node: SVGSVGElement | null) => {
    if (node) {
      const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
      ro.observe(node)
    }
  }, [])

  // Effective duration: at least the max evidence timestamp, or 300s default
  const timed = evidence.filter((e) => e.timestamp != null)
  const maxTs = timed.length > 0
    ? Math.max(...timed.map((e) => e.timestamp as number))
    : 0
  const effectiveDuration = Math.max(duration || 0, maxTs, 60)

  const xFor = (t: number) => (t / effectiveDuration) * width

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current) return
    const rect = svgRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const t = (x / width) * effectiveDuration
    onSeek(Math.max(0, Math.min(t, effectiveDuration)))
  }

  const playheadX = xFor(currentTime)

  return (
    <div className="relative select-none">
      <p className="text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
        Evidence Timeline
      </p>
      <svg
        ref={(node) => {
          ;(svgRef as React.MutableRefObject<SVGSVGElement | null>).current = node
          measuredRef(node)
        }}
        width="100%"
        height={HEIGHT}
        className="cursor-pointer block"
        onClick={handleClick}
        onMouseLeave={() => setTooltip(null)}
      >
        {/* Track */}
        <rect x={0} y={HEIGHT / 2 - 1} width={width} height={2} fill="#e5e7eb" rx={1} />

        {/* Evidence ticks */}
        {timed.map((piece, i) => {
          const x = xFor(piece.timestamp as number)
          const color = polarityColor(piece.polarity)
          const tickW = piece.strength === 'strong' ? 3 : piece.strength === 'medium' ? 2 : 1.5
          return (
            <g key={i}>
              <rect
                x={x - tickW / 2}
                y={HEIGHT / 2 - TICK_HEIGHT / 2}
                width={tickW}
                height={TICK_HEIGHT}
                fill={color}
                opacity={0.85}
                rx={1}
              />
              {/* Invisible wide hit target */}
              <rect
                x={x - 6}
                y={0}
                width={12}
                height={HEIGHT}
                fill="transparent"
                onMouseEnter={(e) => {
                  const rect = (e.currentTarget.closest('svg') as SVGSVGElement).getBoundingClientRect()
                  setTooltip({ x: e.clientX - rect.left, y: 0, piece })
                }}
              />
            </g>
          )
        })}

        {/* Playhead */}
        <line
          x1={playheadX}
          y1={0}
          x2={playheadX}
          y2={HEIGHT}
          stroke="#3b82f6"
          strokeWidth={2}
        />
        <polygon
          points={`${playheadX - 5},0 ${playheadX + 5},0 ${playheadX},8`}
          fill="#3b82f6"
        />
      </svg>

      {/* Time labels */}
      <div className="flex justify-between text-xs text-gray-400 mt-0.5">
        <span>0:00</span>
        <span className="text-blue-500">{fmtTimestamp(currentTime)}</span>
        <span>{fmtTimestamp(effectiveDuration)}</span>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute z-20 bg-gray-900 text-gray-100 text-xs rounded shadow-lg px-2.5 py-2 pointer-events-none max-w-xs"
          style={{ left: Math.min(tooltip.x + 8, width - 200), top: HEIGHT + 18 }}
        >
          <p className="font-semibold capitalize">{tooltip.piece.polarity}</p>
          <p className="text-gray-300">{tooltip.piece.indicator_type}</p>
          <p className="text-gray-400 truncate">{tooltip.piece.raw_value}</p>
          <p className="text-gray-500 mt-0.5">
            {tooltip.piece.source} · {fmtTimestamp(tooltip.piece.timestamp)} · {tooltip.piece.strength}
          </p>
          {tooltip.piece.regulation_ref && (
            <p className="text-green-400 mt-0.5">{tooltip.piece.regulation_ref}</p>
          )}
        </div>
      )}
    </div>
  )
}
