import { useRef, useEffect, useCallback } from 'react'
import { Video } from 'lucide-react'

interface Props {
  videoId: string
  rawPath: string | null
  onTimeUpdate: (t: number) => void
  onDurationChange?: (d: number) => void
  seekTo?: number | null
}

export function VideoPlayer({ videoId, rawPath, onTimeUpdate, onDurationChange, seekTo }: Props) {
  const ref = useRef<HTMLVideoElement>(null)

  // Seek when parent requests it
  useEffect(() => {
    if (seekTo != null && ref.current) {
      ref.current.currentTime = seekTo
    }
  }, [seekTo])

  const handleTimeUpdate = useCallback(() => {
    if (ref.current) onTimeUpdate(ref.current.currentTime)
  }, [onTimeUpdate])

  const handleDuration = useCallback(() => {
    if (ref.current && onDurationChange) onDurationChange(ref.current.duration)
  }, [onDurationChange])

  // Build a plausible src URL. In dev, assumes the backend serves /media/{id}
  // or the raw_path is accessible. Falls back to empty (no-video state).
  const src = rawPath
    ? rawPath.startsWith('http')
      ? rawPath
      : `/media/${encodeURIComponent(videoId)}`
    : ''

  if (!src) {
    return (
      <div className="flex flex-col items-center justify-center h-48 bg-gray-100 rounded-lg border border-gray-200 gap-2 text-gray-400">
        <Video className="h-8 w-8" />
        <p className="text-sm">No media source available</p>
        <p className="text-xs">{videoId}</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg overflow-hidden bg-black">
      <video
        ref={ref}
        src={src}
        controls
        className="w-full max-h-64 object-contain"
        onTimeUpdate={handleTimeUpdate}
        onDurationChange={handleDuration}
        onError={() => {
          // Video source unavailable — surface gracefully via the no-src path
        }}
      />
    </div>
  )
}
