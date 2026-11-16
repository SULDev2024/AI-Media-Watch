import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Loader2, Link2, FileText, Image, Film, Check, AlertCircle } from 'lucide-react'
import { api } from '../api/client'

type Mode = 'text' | 'link' | 'image' | 'video'

const MODES: { id: Mode; label: string; icon: typeof FileText }[] = [
  { id: 'text', label: 'Text', icon: FileText },
  { id: 'link', label: 'Link', icon: Link2 },
  { id: 'image', label: 'Image', icon: Image },
  { id: 'video', label: 'Video', icon: Film },
]

/**
 * Manual "Analyze anything" panel — paste text, paste a link, or upload an
 * image / video and run it through the same scoring pipeline the crawler uses.
 *
 * ``onSubmitted`` fires with the new video_id so a parent page can show the
 * result inline (the Analyze page does this).
 */
export function ManualAnalyze({ onSubmitted }: { onSubmitted?: (videoId: string) => void }) {
  const qc = useQueryClient()
  const [searchParams] = useSearchParams()
  const requestedMode = searchParams.get('mode')
  const platform = searchParams.get('platform') || ''
  const platformNames: Record<string, string> = { youtube: 'YouTube', instagram: 'Instagram', tiktok: 'TikTok' }
  const platformExamples: Record<string, string> = { youtube: 'https://www.youtube.com/watch?v=...', instagram: 'https://www.instagram.com/reel/.../', tiktok: 'https://www.tiktok.com/@account/video/...' }
  const [mode, setMode] = useState<Mode>(requestedMode === 'link' ? 'link' : 'text')
  useEffect(() => { if (requestedMode === 'link') setMode('link') }, [requestedMode, platform])
  const [text, setText] = useState('')
  const [link, setLink] = useState('')
  const [fileName, setFileName] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const submit = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      if (mode === 'text') form.append('text', text)
      else if (mode === 'link') form.append('url', link)
      else {
        const f = fileRef.current?.files?.[0]
        if (!f) throw new Error('Choose a file first')
        form.append('file', f)
      }
      return api.ingest.manual(form)
    },
    onSuccess: (data) => {
      setText('')
      setLink('')
      setFileName('')
      if (fileRef.current) fileRef.current.value = ''
      void qc.invalidateQueries({ queryKey: ['videos'] })
      onSubmitted?.(data.video_id)
    },
  })

  const canSubmit =
    (mode === 'text' && text.trim().length > 0) ||
    (mode === 'link' && link.trim().length > 0) ||
    ((mode === 'image' || mode === 'video') && fileName.length > 0)

  const accept = mode === 'image' ? 'image/*' : 'video/*'

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
      <h2 className="text-sm font-semibold text-gray-800 mb-3">Analyze anything</h2>

      <div className="flex gap-1 mb-3">
        {MODES.map((m) => {
          const Icon = m.icon
          return (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={clsx(
                'flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors',
                mode === m.id
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'text-gray-500 border border-transparent hover:bg-gray-50',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {m.label}
            </button>
          )
        })}
      </div>

      {mode === 'text' && (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder="Paste a message, caption, or transcript to check for fraud signals…"
          className="w-full rounded border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder:text-gray-300 focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-200 resize-y"
        />
      )}

      {mode === 'link' && <div className="mb-3 space-y-2">
        <div className="flex flex-wrap gap-2" aria-label="Video link platforms">{Object.entries(platformNames).map(([id, name]) => <Link key={id} to={`/analyze?mode=link&platform=${id}`} className={clsx('rounded-full border px-3 py-1 text-xs', platform === id ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-500')}>{name}</Link>)}</div>
        <p className="text-xs leading-relaxed text-gray-500">{platformNames[platform] ? `Paste a public ${platformNames[platform]} video link below.` : 'Paste a supported platform video link below.'} This checks one video, rather than searching the platform by keyword. Private or login-restricted videos may require source authentication; you can also upload a local file.</p>
      </div>}

      {mode === 'link' && (
        <input
          type="text"
          aria-label={`${platformNames[platform] || 'Media'} video URL`}
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder={platformExamples[platform] || 'Paste a YouTube, Instagram, or TikTok video URL'}
          className="w-full rounded border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder:text-gray-300 focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-200"
        />
      )}

      {(mode === 'image' || mode === 'video') && (
        <label className="flex items-center justify-center gap-2 rounded border border-dashed border-gray-300 px-3 py-6 text-sm text-gray-500 cursor-pointer hover:border-blue-300 hover:bg-blue-50/40 transition-colors">
          <input
            ref={fileRef}
            type="file"
            accept={accept}
            className="hidden"
            onChange={(e) => setFileName(e.target.files?.[0]?.name ?? '')}
          />
          {mode === 'image' ? <Image className="h-4 w-4" /> : <Film className="h-4 w-4" />}
          {fileName || `Choose ${mode === 'image' ? 'an image' : 'a video'} to upload`}
        </label>
      )}

      <div className="flex items-center gap-3 mt-3">
        <button
          onClick={() => submit.mutate()}
          disabled={!canSubmit || submit.isPending}
          className="flex items-center gap-1.5 rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
        >
          {submit.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Analyze
        </button>

        {submit.isSuccess && (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <Check className="h-3.5 w-3.5" /> Queued — appears below as it scores.
          </span>
        )}
        {submit.isError && (
          <span className="flex items-center gap-1 text-xs text-red-600">
            <AlertCircle className="h-3.5 w-3.5" />
            {(submit.error as Error)?.message ?? 'Failed'}
          </span>
        )}
      </div>

      {(mode === 'image' || mode === 'video') && (
        <p className="text-xs text-gray-400 mt-2">
          {mode === 'image'
            ? 'The image is run through OCR (reads on-screen text, logos, captions) then scored.'
            : 'The video is transcribed and OCR-scanned, then scored — this takes a few minutes.'}
        </p>
      )}
    </div>
  )
}
