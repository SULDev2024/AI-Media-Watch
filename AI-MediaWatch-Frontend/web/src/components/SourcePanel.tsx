import { FileText, Image as ImageIcon } from 'lucide-react'
import { VideoPlayer } from './VideoPlayer'
import type { TranscriptSegment } from '../api/types'

interface Props {
  platform: string
  videoId: string
  rawPath: string | null
  segmentsJson: string | null
  onTimeUpdate: (t: number) => void
  onDurationChange?: (d: number) => void
  seekTo?: number | null
}

/**
 * Shows the right source view for the analyzed item:
 *  - manual text  → the pasted text itself (no video player)
 *  - manual image → the uploaded image
 *  - everything else → the video player
 *
 * This is why pasted text no longer "looks like a broken video".
 */
export function SourcePanel({
  platform,
  videoId,
  rawPath,
  segmentsJson,
  onTimeUpdate,
  onDurationChange,
  seekTo,
}: Props) {
  if (platform === 'manual') {
    let text = ''
    try {
      const segs = JSON.parse(segmentsJson ?? '[]') as TranscriptSegment[]
      text = segs.map((s) => s.text).join('\n')
    } catch {
      text = ''
    }
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          <FileText className="h-3.5 w-3.5" /> Submitted text
        </p>
        <pre className="whitespace-pre-wrap break-words text-sm text-gray-800 font-sans max-h-80 overflow-y-auto">
          {text || '(no text captured)'}
        </pre>
      </div>
    )
  }

  if (platform === 'manual-image') {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          <ImageIcon className="h-3.5 w-3.5" /> Submitted image
        </p>
        <img
          src={`/media/${encodeURIComponent(videoId)}`}
          alt="submitted"
          className="w-full max-h-80 object-contain rounded"
        />
        <p className="text-xs text-gray-400 mt-2">
          OCR reads on-screen text from this image; results feed the score below.
        </p>
      </div>
    )
  }

  return (
    <VideoPlayer
      videoId={videoId}
      rawPath={rawPath}
      onTimeUpdate={onTimeUpdate}
      onDurationChange={onDurationChange}
      seekTo={seekTo}
    />
  )
}
