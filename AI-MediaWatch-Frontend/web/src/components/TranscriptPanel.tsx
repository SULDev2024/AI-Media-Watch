import { useMemo, useState } from 'react'
import { clsx } from 'clsx'
import { ChevronDown, ChevronUp, FileText } from 'lucide-react'
import type { EvidencePiece, TranscriptSegment } from '../api/types'

interface Props {
  segmentsJson: string | null
  evidence: EvidencePiece[]
  languageHint: string | null
  onSeek: (t: number) => void
  currentTime: number
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

interface HighlightedWord {
  text: string
  piece: EvidencePiece | null
}

function highlightSegment(text: string, evidence: EvidencePiece[]): HighlightedWord[] {
  if (!evidence.length) return [{ text, piece: null }]

  // Build sorted list of (start, end, piece) match positions within segment text
  type Match = { start: number; end: number; piece: EvidencePiece }
  const matches: Match[] = []

  for (const piece of evidence) {
    const needle = piece.raw_value.toLowerCase()
    if (!needle) continue
    let pos = 0
    const haystack = text.toLowerCase()
    while (pos < haystack.length) {
      const idx = haystack.indexOf(needle, pos)
      if (idx === -1) break
      matches.push({ start: idx, end: idx + needle.length, piece })
      pos = idx + needle.length
    }
  }

  if (!matches.length) return [{ text, piece: null }]

  // Sort by start, deduplicate overlaps (keep longer match)
  matches.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start))
  const deduped: Match[] = []
  let covered = 0
  for (const m of matches) {
    if (m.start >= covered) {
      deduped.push(m)
      covered = m.end
    }
  }

  // Split text into (plain | highlighted) spans
  const result: HighlightedWord[] = []
  let cursor = 0
  for (const m of deduped) {
    if (m.start > cursor) result.push({ text: text.slice(cursor, m.start), piece: null })
    result.push({ text: text.slice(m.start, m.end), piece: m.piece })
    cursor = m.end
  }
  if (cursor < text.length) result.push({ text: text.slice(cursor), piece: null })
  return result
}

export function TranscriptPanel({ segmentsJson, evidence, languageHint, onSeek, currentTime }: Props) {
  const [open, setOpen] = useState(true)

  const segments = useMemo<TranscriptSegment[]>(() => {
    if (!segmentsJson) return []
    try { return JSON.parse(segmentsJson) as TranscriptSegment[] } catch { return [] }
  }, [segmentsJson])

  // Only use evidence pieces that come from audio (transcript) for highlighting
  const audioEvidence = useMemo(
    () => evidence.filter(e => e.source === 'speech' || e.source === 'audio' || e.source === 'transcript'),
    [evidence]
  )

  // Active segment index based on video playhead
  const activeIdx = useMemo(() => {
    for (let i = segments.length - 1; i >= 0; i--) {
      if (currentTime >= segments[i].start) return i
    }
    return -1
  }, [segments, currentTime])

  if (!segmentsJson) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2 text-gray-400 text-sm">
          <FileText className="h-4 w-4 shrink-0" />
          <span>Transcript not available — re-ingest this video to generate it.</span>
        </div>
      </div>
    )
  }

  if (!segments.length) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2 text-gray-400 text-sm">
          <FileText className="h-4 w-4 shrink-0" />
          <span>Transcript is empty.</span>
        </div>
      </div>
    )
  }

  const wordCount = segments.reduce((n, s) => n + s.text.trim().split(/\s+/).length, 0)

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-gray-400" />
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Transcript
          </span>
          {languageHint && (
            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600 font-mono">
              {languageHint}
            </span>
          )}
          <span className="text-xs text-gray-400">{wordCount.toLocaleString()} words · {segments.length} segments</span>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>

      {open && (
        <>
          {/* Legend */}
          <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 flex items-center gap-4 text-xs text-gray-500">
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded bg-red-100 border border-red-300" />
              incriminating signal
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded bg-green-100 border border-green-300" />
              mitigating signal
            </span>
            <span className="text-gray-400">· click any segment to seek video</span>
          </div>

          {/* Transcript body */}
          <div className="px-4 py-3 max-h-96 overflow-y-auto space-y-1 text-sm leading-relaxed">
            {segments.map((seg, i) => {
              const highlighted = highlightSegment(seg.text, audioEvidence)
              const isActive = i === activeIdx

              return (
                <div
                  key={i}
                  onClick={() => onSeek(seg.start)}
                  className={clsx(
                    'group flex gap-2 rounded px-2 py-1 cursor-pointer transition-colors',
                    isActive ? 'bg-blue-50' : 'hover:bg-gray-50'
                  )}
                >
                  {/* Timestamp gutter */}
                  <span className={clsx(
                    'shrink-0 font-mono text-xs pt-0.5 w-10 text-right transition-colors',
                    isActive ? 'text-blue-600' : 'text-gray-300 group-hover:text-gray-500'
                  )}>
                    {fmtTime(seg.start)}
                  </span>

                  {/* Text with inline highlights */}
                  <span className="flex-1 text-gray-700">
                    {highlighted.map((span, j) => {
                      if (!span.piece) return <span key={j}>{span.text}</span>
                      const isIncrim = span.piece.polarity === 'incriminating'
                      return (
                        <span
                          key={j}
                          title={`${span.piece.indicator_type} (${span.piece.strength})`}
                          className={clsx(
                            'rounded px-0.5 font-medium cursor-default',
                            isIncrim
                              ? 'bg-red-100 text-red-800 border border-red-200'
                              : 'bg-green-100 text-green-800 border border-green-200'
                          )}
                        >
                          {span.text}
                        </span>
                      )
                    })}
                  </span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
