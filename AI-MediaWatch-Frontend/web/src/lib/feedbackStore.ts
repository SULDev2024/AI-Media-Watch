// Local feedback log — persisted in localStorage because Phase 12 has no GET /feedback.
import type { FeedbackLogEntry, FeedbackOut } from '../api/types'

const KEY = 'aimw_feedback_log'
const MAX = 200

export function loadFeedbackLog(): FeedbackLogEntry[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as FeedbackLogEntry[]) : []
  } catch {
    return []
  }
}

export function appendFeedback(
  out: FeedbackOut,
  notes?: string,
): FeedbackLogEntry {
  const entry: FeedbackLogEntry = {
    ...out,
    saved_at: new Date().toISOString(),
    notes,
  }
  const log = loadFeedbackLog()
  log.unshift(entry)
  try {
    localStorage.setItem(KEY, JSON.stringify(log.slice(0, MAX)))
  } catch {
    // storage full — silently drop oldest
  }
  return entry
}
