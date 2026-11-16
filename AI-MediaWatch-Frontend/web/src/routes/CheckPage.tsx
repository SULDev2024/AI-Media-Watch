import { useState, useCallback } from 'react'
import { ShieldCheck, Loader2, AlertTriangle, CheckCircle2, XCircle, Link2, Type } from 'lucide-react'
import { api } from '../api/client'
import type { CheckResult } from '../api/types'

const LEVEL_STYLES: Record<string, { bg: string; border: string; text: string; icon: typeof AlertTriangle }> = {
  CRITICAL: { bg: 'bg-red-50', border: 'border-red-300', text: 'text-red-700', icon: XCircle },
  HIGH:     { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-600', icon: AlertTriangle },
  MEDIUM:   { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-700', icon: AlertTriangle },
  LOW:      { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-700', icon: CheckCircle2 },
  NONE:     { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-600', icon: CheckCircle2 },
}

export function CheckPage() {
  const [mode, setMode] = useState<'url' | 'text'>('url')
  const [urlInput, setUrlInput] = useState('')
  const [textInput, setTextInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CheckResult | null>(null)
  const [statusMsg, setStatusMsg] = useState('')

  const reset = () => {
    setResult(null)
    setError(null)
    setStatusMsg('')
  }

  const pollForResult = useCallback(async (videoId: string) => {
    const maxAttempts = 600
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const res = await api.check.result(videoId)
        if (res.status === 'failed') {
          setError(res.summary || 'Analysis failed. Please retry.')
          setLoading(false)
          return
        }
        if (res.status === 'done' && res.risk_level) {
          setResult(res)
          setLoading(false)
          return
        }
        setStatusMsg(res.status === 'processing' ? 'Processing content...' : 'In queue...')
      } catch {
        // retry
      }
    }
    setError('Analysis timed out. Try again later.')
    setLoading(false)
  }, [])

  const handleSubmit = useCallback(async () => {
    reset()
    const body = mode === 'url' ? { url: urlInput.trim() } : { text: textInput.trim() }
    if (!body.url && !body.text) return

    setLoading(true)
    setStatusMsg('Submitting...')
    try {
      const res = await api.check.submit(body)
      setStatusMsg('Analyzing...')
      await pollForResult(res.video_id)
    } catch (e: any) {
      const detail = e?.message || 'Something went wrong'
      const match = detail.match(/:\s*(.+)$/)
      setError(match ? match[1] : detail)
      setLoading(false)
    }
  }, [mode, urlInput, textInput, pollForResult])

  const style = result?.risk_level ? LEVEL_STYLES[result.risk_level] : null
  const Icon = style?.icon ?? AlertTriangle

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="flex items-center gap-2 mb-1">
        <ShieldCheck className="h-5 w-5 text-blue-600" />
        <h1 className="text-xl font-semibold text-gray-900">Scam Check</h1>
      </div>
      <p className="text-sm text-gray-500 mb-6">
        Paste a social media link or suspicious text to check for fraud indicators.
      </p>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => { setMode('url'); reset() }}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            mode === 'url'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <Link2 className="h-4 w-4" /> Link
        </button>
        <button
          onClick={() => { setMode('text'); reset() }}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            mode === 'text'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <Type className="h-4 w-4" /> Text
        </button>
      </div>

      {/* Input */}
      {mode === 'url' ? (
        <input
          type="url"
          placeholder="https://www.instagram.com/p/..."
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          disabled={loading}
          className="w-full px-4 py-3 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50"
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
        />
      ) : (
        <textarea
          placeholder="Paste the suspicious message here..."
          value={textInput}
          onChange={(e) => setTextInput(e.target.value)}
          disabled={loading}
          rows={5}
          className="w-full px-4 py-3 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50 resize-vertical"
        />
      )}

      <div className="flex items-center gap-3 mt-2 mb-4">
        <p className="text-xs text-gray-400">
          {mode === 'url'
            ? 'Supports YouTube, Instagram, TikTok, Telegram'
            : 'Minimum 10 characters'}
        </p>
      </div>

      <button
        onClick={handleSubmit}
        disabled={loading || (mode === 'url' ? !urlInput.trim() : textInput.trim().length < 10)}
        className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium text-sm hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> {statusMsg || 'Checking...'}
          </span>
        ) : (
          'Check for Scam'
        )}
      </button>

      {/* Error */}
      {error && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {/* Result */}
      {result && style && (
        <div className={`mt-6 p-5 rounded-xl border-2 ${style.bg} ${style.border}`}>
          <div className="flex items-center gap-2 mb-3">
            <Icon className={`h-5 w-5 ${style.text}`} />
            <h2 className={`text-lg font-bold ${style.text}`}>
              {result.risk_level}
              {result.risk_score != null && (
                <span className="font-normal text-sm ml-2 opacity-75">
                  {Math.round(result.risk_score * 100)}% risk
                </span>
              )}
            </h2>
          </div>

          {result.summary && (
            <p className="text-sm text-gray-700 leading-relaxed mb-3">
              {result.summary}
            </p>
          )}

          {result.recommended_action && (
            <div className="mt-3 pt-3 border-t border-gray-200">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
                Recommended Action
              </p>
              <p className="text-sm text-gray-700">{result.recommended_action}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
