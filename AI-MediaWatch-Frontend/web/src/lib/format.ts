/** Verbal confidence label per spec §14: ≥0.75 Confident, 0.60–0.75 Likely, <0.60 Uncertain. */
export function confidenceLabel(confidence: number | null | undefined): string {
  if (confidence == null) return 'Unknown'
  if (confidence >= 0.75) return 'Confident'
  if (confidence >= 0.60) return 'Likely'
  return 'Uncertain'
}

/** Format a floating-point score with sign. */
export function fmtScore(score: number): string {
  return (score >= 0 ? '+' : '') + score.toFixed(3)
}

/** Format a percentage from 0–1. */
export function fmtPct(value: number): string {
  return (value * 100).toFixed(1) + '%'
}

/** Tailwind classes for risk level badge. */
export function riskBadge(level: string | null): string {
  switch (level?.toUpperCase()) {
    case 'CRITICAL': return 'bg-red-600 text-white'
    case 'HIGH':     return 'bg-orange-500 text-white'
    case 'MEDIUM':   return 'bg-yellow-500 text-gray-900'
    case 'LOW':      return 'bg-green-500 text-white'
    case 'NONE':     return 'bg-gray-300 text-gray-700'
    case 'FAILED':   return 'bg-gray-800 text-gray-200'
    case 'CANCELLED': return 'bg-gray-200 text-gray-600'
    default:         return 'bg-gray-200 text-gray-600'
  }
}

/** Tailwind border-left color for risk level. */
export function riskBorder(level: string | null): string {
  switch (level?.toUpperCase()) {
    case 'CRITICAL': return 'border-l-red-600'
    case 'HIGH':     return 'border-l-orange-500'
    case 'MEDIUM':   return 'border-l-yellow-500'
    case 'LOW':      return 'border-l-green-500'
    default:         return 'border-l-gray-300'
  }
}

/** ISO datetime → locale string. */
export function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'short',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

/** Seconds → MM:SS */
export function fmtTimestamp(seconds: number | null): string {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** Capitalize first letter. */
export function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1)
}

/** Polarity → color for timeline ticks and badges. */
export function polarityColor(polarity: string): string {
  switch (polarity.toLowerCase()) {
    case 'incriminating': return '#dc2626' // red-600
    case 'mitigating':    return '#16a34a' // green-600
    default:              return '#6b7280' // gray-500
  }
}

/** Strength → numeric weight 1–3. */
export function strengthWeight(strength: string): number {
  switch (strength.toLowerCase()) {
    case 'strong': return 3
    case 'medium': return 2
    default:       return 1
  }
}
