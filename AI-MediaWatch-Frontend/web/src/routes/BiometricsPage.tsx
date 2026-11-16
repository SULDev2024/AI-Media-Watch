import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Scan, CheckCircle, XCircle, RefreshCw, Eye, Mic, ImageIcon } from 'lucide-react'
import { clsx } from 'clsx'

function CapabilityCard({
  title,
  icon: Icon,
  available,
  description,
  threshold,
  embeddingDim,
  extra,
}: {
  title: string
  icon: typeof Eye
  available: boolean
  description: string
  threshold: number
  embeddingDim: number | null
  extra?: React.ReactNode
}) {
  return (
    <div className={clsx(
      'border rounded-lg p-5 space-y-3',
      available ? 'border-green-700/50 bg-green-900/10' : 'border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/30',
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={clsx(
            'p-2 rounded-lg',
            available ? 'bg-green-900/30 text-green-700 dark:text-green-400' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500',
          )}>
            <Icon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">{title}</h3>
            <p className="text-xs text-gray-600 dark:text-gray-500">{description}</p>
          </div>
        </div>
        {available ? (
          <span className="flex items-center gap-1 text-xs text-green-700 dark:text-green-400">
            <CheckCircle className="h-3.5 w-3.5" /> Module installed
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-gray-600 dark:text-gray-500">
            <XCircle className="h-3.5 w-3.5" /> Unavailable
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="bg-gray-100 dark:bg-gray-800/50 rounded px-3 py-2">
          <span className="text-gray-600 dark:text-gray-500">Match threshold</span>
          <p className="text-gray-700 dark:text-gray-300 font-mono mt-0.5">{(threshold * 100).toFixed(0)}%</p>
        </div>
        {embeddingDim && (
          <div className="bg-gray-100 dark:bg-gray-800/50 rounded px-3 py-2">
            <span className="text-gray-600 dark:text-gray-500">Embedding dim</span>
            <p className="text-gray-700 dark:text-gray-300 font-mono mt-0.5">{embeddingDim}</p>
          </div>
        )}
      </div>
      {extra}
    </div>
  )
}

export function BiometricsPage() {
  const qc = useQueryClient()
  const caps = useQuery({ queryKey: ['biometrics-caps'], queryFn: () => api.biometrics.capabilities() })
  const logos = useQuery({ queryKey: ['logo-refs'], queryFn: () => api.biometrics.logoReferences() })

  const reloadMutation = useMutation({
    mutationFn: () => api.biometrics.reloadLogos(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['biometrics-caps'] })
      qc.invalidateQueries({ queryKey: ['logo-refs'] })
    },
  })

  const data = caps.data

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Scan className="h-6 w-6 text-cyan-700 dark:text-cyan-400" />
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Biometric Analysis</h1>
        <span className="text-xs bg-cyan-500/20 text-cyan-700 dark:text-cyan-300 px-2 py-0.5 rounded-full border border-cyan-500/30">
          3 Modules
        </span>
      </div>

      <p className="text-sm text-gray-600 dark:text-gray-400">
        Optional experimental matching tools. Installed dependencies do not mean these checks ran on a video.
        Scam risk is assessed on the Analyze page; biometric similarity alone is not evidence of fraud.
      </p>

      {caps.isLoading && <p className="text-sm text-gray-600 dark:text-gray-500">Loading capabilities...</p>}
      {caps.isError && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-3 text-sm text-red-700 dark:text-red-300">
          {(caps.error as Error).message}
        </div>
      )}

      {data && (
        <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3">
          {/* Face Recognition */}
          <CapabilityCard
            title="Face Recognition"
            icon={Eye}
            available={data.face_recognition.available}
            description={data.face_recognition.description}
            threshold={data.face_recognition.match_threshold}
            embeddingDim={data.face_recognition.embedding_dim}
            extra={
              <div className="text-xs text-gray-600 dark:text-gray-500 bg-gray-100 dark:bg-gray-800/30 rounded px-3 py-2 space-y-1">
                <p>Haar cascade detection + spatial-histogram embeddings</p>
                <p>8x8 grid, 16-bin LBP histograms per cell</p>
                <p>Survives re-encoding, angle changes, lighting shifts</p>
              </div>
            }
          />

          {/* Speaker Diarization */}
          <CapabilityCard
            title="Speaker Diarization"
            icon={Mic}
            available={data.speaker_diarization.available}
            description={data.speaker_diarization.description}
            threshold={data.speaker_diarization.match_threshold}
            embeddingDim={data.speaker_diarization.embedding_dim}
            extra={
              <div className="text-xs text-gray-600 dark:text-gray-500 bg-gray-100 dark:bg-gray-800/30 rounded px-3 py-2 space-y-1">
                <p>Mel-filterbank spectral features via scipy FFT</p>
                <p>Energy-based segmentation + speaker clustering</p>
                <p>Links same voice across different accounts</p>
              </div>
            }
          />

          {/* Logo Detection */}
          <CapabilityCard
            title="Logo Detection"
            icon={ImageIcon}
            available={data.logo_detection.available && (data.logo_detection.n_reference_logos ?? 0) > 0}
            description={data.logo_detection.description}
            threshold={data.logo_detection.min_good_matches ? data.logo_detection.min_good_matches / 45 : 0.33}
            embeddingDim={null}
            extra={
              <div className="space-y-2">
                <div className="text-xs text-gray-600 dark:text-gray-500 bg-gray-100 dark:bg-gray-800/30 rounded px-3 py-2 space-y-1">
                  <p>ORB feature matching against reference library</p>
                  <p>Min {data.logo_detection.min_good_matches} inlier matches required</p>
                  <p>Place logos in <code className="text-gray-600 dark:text-gray-400">config/logos/</code></p>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-600 dark:text-gray-500">
                    {data.logo_detection.n_reference_logos ?? 0} reference logos loaded
                  </span>
                  <button
                    onClick={() => reloadMutation.mutate()}
                    disabled={reloadMutation.isPending}
                    className="flex items-center gap-1 text-xs text-cyan-700 dark:text-cyan-400 hover:text-cyan-300 transition-colors"
                  >
                    <RefreshCw className={clsx('h-3 w-3', reloadMutation.isPending && 'animate-spin')} />
                    Reload
                  </button>
                </div>
              </div>
            }
          />
        </div>
      )}

      {/* Reference logos table */}
      {logos.data && logos.data.references.length > 0 && (
        <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Reference Logo Library</h2>
          <div className="space-y-1">
            {logos.data.references.map(ref => (
              <div key={ref.brand} className="flex items-center justify-between py-2 px-3 rounded bg-gray-100 dark:bg-gray-800/30">
                <div className="flex items-center gap-3">
                  <ImageIcon className="h-4 w-4 text-cyan-700 dark:text-cyan-400" />
                  <span className="text-sm text-gray-800 dark:text-gray-200">{ref.brand}</span>
                </div>
                <span className="text-xs text-gray-600 dark:text-gray-500">{ref.n_keypoints} keypoints</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* How it works */}
      <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-lg p-5 space-y-4">
        <h2 className="text-sm font-medium text-gray-700 dark:text-gray-300">How Cross-Platform Tracking Works</h2>
        <div className="grid gap-4 md:grid-cols-3 text-xs text-gray-600 dark:text-gray-400">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300 font-medium">
              <Eye className="h-4 w-4 text-green-700 dark:text-green-400" /> Face Re-identification
            </div>
            <p>
              When a video is processed, faces are detected in sampled frames using Haar cascades.
              Each face is normalized to 128x128 and a 1024-dim embedding is computed. The system
              then compares this embedding against all known faces in the database — if the same
              person appears in a different video on a different platform, they are linked as a
              repeat offender.
            </p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300 font-medium">
              <Mic className="h-4 w-4 text-purple-700 dark:text-purple-400" /> Voice Linking
            </div>
            <p>
              Audio is analyzed with mel-filterbank spectral features. Each speaker segment gets
              an 80-dim voice embedding. The system identifies which voice segments belong to the
              same speaker (diarization) and matches voices across videos — catching the same
              scam narrator even when they use a different account.
            </p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300 font-medium">
              <ImageIcon className="h-4 w-4 text-cyan-700 dark:text-cyan-400" /> Logo Detection
            </div>
            <p>
              Reference logos (government seals, bank logos) are loaded from the library. ORB
              feature descriptors are matched against each video frame — when a scam video
              fraudulently displays an official logo to build false authority, it is
              automatically flagged with the specific brand identified.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
