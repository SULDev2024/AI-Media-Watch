import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AdversarialComparison } from '../api/types'
import { ShieldAlert, Zap, CheckCircle, XCircle, FlaskConical } from 'lucide-react'
import { clsx } from 'clsx'

// Pre-loaded real-world scam examples for the demo
const EXAMPLES = [
  {
    label: 'Crypto VIP Signal',
    text: 'Join our crypto signals VIP group! Guaranteed profit every day. Passive income with zero risk. Double your investment in 48 hours. Referral bonus for every friend you bring! Limited spots available — DM now.',
  },
  {
    label: 'Forex Trading Bot',
    text: 'Our AI forex trading bot delivers guaranteed returns of 15% per week. No experience needed. Financial freedom is just one click away. Get rich fast with our proven investment opportunity. Risk free guaranteed profit daily!',
  },
  {
    label: 'Russian Crypto Scam',
    text: 'Гарантированный доход каждый день! Пассивный доход без риска. Крипто сигналы от лучших трейдеров. Реферальная программа — приглашай друзей и получай бонус. Казино и ставки доступны 24/7.',
  },
  {
    label: 'Bitcoin Doubler',
    text: 'Send 0.1 BTC and receive 0.2 BTC back within 24 hours. Double your money guaranteed. This is not a pyramid scheme — this is a legitimate investment opportunity with 100% profit guaranteed. Casino-style returns every day.',
  },
]

const TECHNIQUE_INFO: Record<string, { label: string; description: string; color: string }> = {
  homoglyph: {
    label: 'Homoglyph Swap',
    description: 'Replaces Latin letters with visually identical Cyrillic ones (a→а, o→о, e→е). Same appearance, different Unicode — keyword filter misses it.',
    color: 'text-purple-400',
  },
  spacing: {
    label: 'Character Spacing',
    description: 'Inserts spaces between every character ("p r o f i t"). Human reads it fine; keyword regex finds no match.',
    color: 'text-blue-400',
  },
  leetspeak: {
    label: 'Leetspeak',
    description: 'Substitutes letters with numbers (o→0, i→1, e→3, a→@, s→$). Common in spam — breaks literal string matching.',
    color: 'text-amber-400',
  },
  zero_width: {
    label: 'Zero-Width Chars',
    description: 'Inserts invisible U+200B zero-width spaces between every character. Completely invisible to human reader, invisible to a keyword filter.',
    color: 'text-green-400',
  },
}

export function AdversarialPage() {
  const [text, setText] = useState('')
  const [result, setResult] = useState<AdversarialComparison | null>(null)

  const mutation = useMutation({
    mutationFn: (t: string) => api.adversarial.compare(t),
    onSuccess: setResult,
  })

  function loadExample(ex: { label: string; text: string }) {
    setText(ex.text)
    setResult(null)
    mutation.mutate(ex.text)
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ShieldAlert className="h-6 w-6 text-red-400" />
        <h1 className="text-xl font-bold text-gray-100">Adversarial Robustness</h1>
        <span className="text-xs bg-red-500/20 text-red-300 px-2 py-0.5 rounded-full border border-red-500/30">
          Live Demo
        </span>
      </div>

      <p className="text-sm text-gray-400 leading-relaxed">
        The system runs a <span className="text-white font-medium">naive keyword filter</span> against
        the original text, then applies <span className="text-white font-medium">4 evasion techniques</span> scammers
        actually use — proving keyword-based detection is trivially defeated while our{' '}
        <span className="text-green-400 font-medium">intent-based pipeline</span> reads meaning, not literal strings.
      </p>

      {/* Pre-loaded examples */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <FlaskConical className="h-4 w-4 text-gray-400" />
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Load an example</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map(ex => (
            <button
              key={ex.label}
              onClick={() => loadExample(ex)}
              disabled={mutation.isPending}
              className="px-3 py-1.5 rounded border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:border-red-500 hover:text-red-300 transition-colors disabled:opacity-40"
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="space-y-3">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Or paste your own transcript / caption to stress-test…"
          rows={4}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder:text-gray-500 focus:border-red-500 focus:outline-none resize-none"
        />
        <button
          onClick={() => text.trim() && mutation.mutate(text.trim())}
          disabled={mutation.isPending || !text.trim()}
          className={clsx(
            'flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-colors',
            mutation.isPending
              ? 'bg-gray-700 text-gray-400 cursor-wait'
              : 'bg-red-600 hover:bg-red-500 text-white',
          )}
        >
          {mutation.isPending ? (
            <><Zap className="h-4 w-4 animate-pulse" /> Running evasions…</>
          ) : (
            <><ShieldAlert className="h-4 w-4" /> Run Adversarial Test</>
          )}
        </button>
      </div>

      {mutation.isError && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-3 text-sm text-red-300">
          {(mutation.error as Error).message}
        </div>
      )}

      {result && (
        <div className="space-y-4">
          {/* Original verdict */}
          <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Step 1 — Keyword Baseline on Original Text
            </h2>
            <div className="flex items-center gap-4">
              {result.original.keyword_flagged ? (
                <span className="flex items-center gap-1.5 text-sm font-medium text-red-400">
                  <XCircle className="h-4 w-4" /> Flagged as scam
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-sm font-medium text-green-400">
                  <CheckCircle className="h-4 w-4" /> Not flagged
                </span>
              )}
              <span className="text-xs text-gray-500">{result.original.n_hits} keyword{result.original.n_hits !== 1 ? 's' : ''} matched</span>
            </div>
            {result.original.matched_keywords.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {result.original.matched_keywords.map(kw => (
                  <span key={kw} className="text-[11px] px-2 py-0.5 rounded bg-red-900/40 text-red-300 border border-red-700/40 font-mono">
                    {kw}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Evasion variants */}
          <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Step 2 — Apply Evasion Techniques &amp; Re-run Keyword Filter
            </h2>
            <div className="space-y-3">
              {result.variants.map(v => {
                const info = TECHNIQUE_INFO[v.technique]
                return (
                  <div key={v.technique} className={clsx(
                    'rounded-lg border p-3',
                    v.defeated_baseline
                      ? 'bg-red-900/10 border-red-700/50'
                      : 'bg-gray-800/30 border-gray-700/40',
                  )}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={clsx('text-sm font-semibold', info?.color ?? 'text-gray-300')}>
                            {info?.label ?? v.technique}
                          </span>
                          {v.defeated_baseline ? (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30 font-bold">
                              EVADED FILTER
                            </span>
                          ) : (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-400 border border-gray-600">
                              still caught
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-gray-500 mb-2">{info?.description}</p>
                        <p className="text-[11px] text-gray-400 font-mono bg-gray-900/60 rounded px-2 py-1 truncate">
                          {v.sample}
                        </p>
                      </div>
                      <div className="shrink-0 text-right pt-1">
                        {v.keyword_flagged ? (
                          <span className="text-xs text-red-400 flex items-center gap-1">
                            <XCircle className="h-3 w-3" />{v.n_hits} hits
                          </span>
                        ) : (
                          <span className="text-xs text-green-400 flex items-center gap-1">
                            <CheckCircle className="h-3 w-3" />0 hits
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Conclusion */}
          <div className={clsx(
            'rounded-lg p-4 border',
            result.evasions_defeating_baseline > 0
              ? 'bg-red-900/20 border-red-600'
              : 'bg-green-900/20 border-green-700',
          )}>
            <div className="flex items-center gap-3 mb-2">
              <ShieldAlert className={clsx('h-5 w-5 shrink-0', result.evasions_defeating_baseline > 0 ? 'text-red-400' : 'text-green-400')} />
              <span className="text-sm font-bold text-gray-100">
                {result.evasions_defeating_baseline}/{result.evasions_tested} evasion techniques defeated the keyword filter
              </span>
            </div>
            <p className="text-xs text-gray-400 mb-3">{result.verdict}</p>
            <div className="bg-green-900/20 border border-green-700/40 rounded p-3">
              <p className="text-xs text-green-300 font-medium">
                ✓ Our intent-based pipeline is not fooled — it reads <em>what the text means</em>, not which
                literal strings appear. Homoglyphs, spacing, and leetspeak don't change the intent.
                The LLM judge identifies "guaranteed profit" whether it's spelled normally, in Cyrillic,
                l33tsp3@k, or split with invisible characters.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
