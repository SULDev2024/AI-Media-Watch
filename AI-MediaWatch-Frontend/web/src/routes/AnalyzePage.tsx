import { useState } from 'react'
import { ScanSearch } from 'lucide-react'
import { ManualAnalyze } from '../components/ManualAnalyze'
import { AnalyzeResult } from '../components/AnalyzeResult'

/**
 * Dedicated Analyze workspace — paste text, drop a photo, upload a video, or
 * paste a link, and see the fraud verdict + reasoning right here. Separate
 * from the crawler Queue so manual checks have their own home.
 */
export function AnalyzePage() {
  const [results, setResults] = useState<string[]>([])

  const handleSubmitted = (videoId: string) => {
    // Newest first; de-dupe so re-submitting identical input doesn't stack.
    setResults((prev) => [videoId, ...prev.filter((v) => v !== videoId)])
  }

  const dismiss = (videoId: string) =>
    setResults((prev) => prev.filter((v) => v !== videoId))

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="page-heading"><div>
        <p className="eyebrow">MULTIMODAL INTELLIGENCE</p>
        <h1>Every detail tells a story.</h1>
        <p>Submit content. Uncover fraud signals. Follow the evidence.</p>
      </div><span className="analysis-heading-icon"><ScanSearch size={26} /></span></div>
      <div className="analysis-workflow" aria-label="Analysis process">
        <span><b>01</b> Submit your content</span><span><b>02</b> Extract signals & context</span><span><b>03</b> Review the evidence</span>
      </div>

      <ManualAnalyze onSubmitted={handleSubmitted} />

      {results.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 py-16 text-center">
          <ScanSearch className="h-8 w-8 text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-500">
            Your findings will appear here. Start with a message, link, image, or video.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {results.map((videoId) => (
            <AnalyzeResult
              key={videoId}
              videoId={videoId}
              onDismiss={() => dismiss(videoId)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
