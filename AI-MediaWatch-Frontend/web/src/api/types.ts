// Mirrored from Phase 12 API schemas — keep names identical to backend.

export interface VideoSummary {
  video_id: string
  platform: string
  url: string
  collected_at: string
  score: number | null
  level: string | null
  confidence: number | null
  action: string | null
  priority_score: number | null
  content_type: string  // "video" | "photo" | "text"
  title: string | null
  evidence_count: number
}

export interface VideosList {
  items: VideoSummary[]
  total: number
  limit: number
  request_id: string
}

export interface VideoDetail {
  status?: 'pending' | 'complete' | 'failed'
  error?: string | null
  video_id: string
  platform: string
  url: string
  collected_at: string
  language_hint: string | null
  raw_path: string | null
  package_ids: string[]
  transcript_segments: string | null
  ocr_text?: string | null
  request_id: string
}

export interface TranscriptSegment {
  text: string
  start: number
  end: number
}

export interface CollectorState {
  status: string // "running" | "stopped"
  queries: string[]
  platforms: string[]
  content_types: string[]
  region_focus: string
  per_query: number
  last_run: string | null
  last_enqueued: number
  enqueued_total: number
  supported_platforms: string[]
}

export interface CollectorStartRequest {
  queries: string[]
  platforms?: string[]
  content_types?: string[]
  region_focus?: string
  per_query?: number
}

export interface KeywordSuggestion {
  keyword: string
  source: string // "pattern" | "trigram" | "bigram" | "llm"
  confidence: number
  reason?: string
  count?: number
}

export interface EvidencePiece {
  source: string
  polarity: string // "incriminating" | "mitigating"
  timestamp: number | null
  content: string
  raw_value: string
  indicator_type: string
  strength: string // "weak" | "medium" | "strong"
  recovery_method: string | null
  corroborated_by: string[]
  regulation_ref: string | null
}

export interface NetworkConnection {
  kind: string
  shared_entity_kind: string
  shared_entity_value: string
  co_occurring_report_ids: string[]
  campaign_strength: string
  detected_at: string
}

export interface ExtractedEntities {
  telegram_handles: string[]
  telegram_links: string[]
  crypto_wallets: string[]
  phone_numbers: string[]
  websites: string[]
  referral_codes: string[]
  profit_claims: string[]
  payment_phones: string[]
}

export interface EvidencePackage {
  report_id: string
  video_id: string
  platform: string
  url: string
  collected_at: string
  processed_at: string
  evidence: EvidencePiece[]
  entities: ExtractedEntities
  network_connections: NetworkConnection[]
  // Computed by scoring registry after register() is called
  score: number
  risk_level: string
  // Set by confidence engine; may be absent if pipeline did not run confidence
  confidence?: number | null
  action?: string | null
}

export interface ReportResponse {
  package: EvidencePackage
  markdown: string
  request_id: string
  // Verdict projection — LLM judge result when available, else rule-based
  score: number | null
  risk_level: string | null
  confidence: number | null
  action: string | null
  judge: string | null  // "llm" | "rules" — null if unknown
}

export interface FeedbackIn {
  report_id: string
  projection?: {
    score: number | null
    risk_level: string | null
    confidence: number | null
    action: string | null
  } | null
  verdict: string
  notes?: string
}

export interface FeedbackOut {
  feedback_id: number
  report_id: string
  verdict: string
  regression_case_id: number | null
  request_id: string
}

export interface FeedbackLogEntry extends FeedbackOut {
  saved_at: string
  notes?: string
}

export interface FeedbackListResponse {
  items: FeedbackLogEntry[]
  request_id: string
}

export interface CytoscapeElementData {
  id: string
  source?: string
  target?: string
  [key: string]: unknown
}

export interface CytoscapeElement {
  data: CytoscapeElementData
}

export interface CytoscapeGraph {
  nodes: CytoscapeElement[]
  edges: CytoscapeElement[]
  request_id: string
}

export interface CampaignOut {
  campaign_id: string
  shared_entities: string[]
  strength: string
  n_videos: number
  videos: string[]
}

export interface CampaignsResponse {
  items: CampaignOut[]
  request_id: string
}

export interface PrecisionRecallCase {
  case_id: string
  expected_level: string
  predicted_level: string
  expected_action: string
  predicted_action: string
  is_correct_level: boolean
  is_correct_action: boolean
  is_false_positive: boolean
  is_false_negative: boolean
}

export interface PrecisionRecallResponse {
  n_cases: number
  precision: number
  recall: number
  f1: number
  cases: PrecisionRecallCase[]
  cached_at: string
  request_id: string
}

export interface UsageToday {
  date: string
  model: string
  tokens_used: number
  daily_cap: number
  remaining: number
  request_id: string
}

export interface IngestRequest {
  url: string
  platform?: string
}

export interface IngestResponse {
  video_id: string
  status: string
  request_id: string
  queue_id: number
}

export interface CheckResponse {
  video_id: string
  status: string
}

export interface CheckResult {
  video_id: string
  risk_level: string | null
  risk_score: number | null
  summary: string | null
  recommended_action: string | null
  status: string
}

// ---------------------------------------------------------------------------
// Case files — tamper-evident chain of custody
// ---------------------------------------------------------------------------

export interface EvidenceHashEntry {
  hash: string
  indicator_type: string
  polarity: string
  strength: string
  source: string
  timestamp: number | null
  raw_value: string
  regulation_ref: string | null
  regulation_cite: string | null
}

export interface StatuteViolation {
  id: string
  short: string
  title: string
  article: string
  jurisdiction: string
}

export interface CaseFile {
  case_id: string
  report_id: string
  video_id: string
  platform: string
  url: string
  collected_at: string
  sealed_at: string
  verdict: string
  risk_level: string
  final_score: number
  confidence: number | null
  chain_root: string
  package_hash: string
  n_evidence_pieces: number
  evidence_chain: EvidenceHashEntry[]
  statute_violations: StatuteViolation[]
  entities: Record<string, string[]>
  verify_ok: boolean
  verify_reason: string
  action: string | null
  request_id: string
}

// ---------------------------------------------------------------------------
// Investigation cell — 9-agent orchestrated investigation
// ---------------------------------------------------------------------------

export interface AgentRosterEntry {
  name: string
  role: string
  tier: number
  uses_llm: boolean
  objective?: string
  inputs?: string[]
  outputs?: string[]
  authority?: string
}

export interface AgentReport {
  agent: string
  role: string
  tier: number
  assessment: string
  findings: string[]
  confidence: number
  signals: Record<string, unknown>
  suggested_next: string | null
  used_llm: boolean
  elapsed_ms: number
  error: string | null
}

export interface JournalEntry {
  ts: string
  agent: string
  event: string
  detail: string
}

export interface InvestigationResult {
  video_id: string
  report_id: string
  verdict: string
  risk_level: string
  final_score: number
  confidence: number | null
  chain_root: string | null
  escalated_to_human: boolean
  iterations: number
  reports: Record<string, AgentReport>
  journal: JournalEntry[]
  llm_used: boolean
  request_id: string
  platform?: string
  url?: string
  started_at?: string
  finished_at?: string | null
  case_file?: unknown
}

export interface RosterResponse {
  roster: AgentRosterEntry[]
  request_id: string
}

// ---------------------------------------------------------------------------
// System info — sovereignty posture
// ---------------------------------------------------------------------------

export interface SystemInfo {
  llm_model: string
  llm_provider: string
  inference_host: string
  on_prem: boolean
  sovereign_capable: boolean
  mode: string
  note: string
  request_id: string
}

// ---------------------------------------------------------------------------
// Adversarial robustness comparison
// ---------------------------------------------------------------------------

export interface AdversarialVariant {
  technique: string
  sample: string
  keyword_flagged: boolean
  n_hits: number
  defeated_baseline: boolean
}

export interface AdversarialComparison {
  original: {
    keyword_flagged: boolean
    n_hits: number
    matched_keywords: string[]
  }
  variants: AdversarialVariant[]
  evasions_tested: number
  evasions_defeating_baseline: number
  verdict: string
  request_id: string
}

// ---------------------------------------------------------------------------
// Biometrics — face, voice, logo
// ---------------------------------------------------------------------------

export interface BiometricCapability {
  available: boolean
  embedding_dim: number | null
  match_threshold: number
  description: string
  n_reference_logos?: number
  reference_logos?: string[]
  min_good_matches?: number
}

export interface BiometricCapabilities {
  face_recognition: BiometricCapability
  speaker_diarization: BiometricCapability
  logo_detection: BiometricCapability
  request_id: string
}

export interface LogoReference {
  brand: string
  path: string
  n_keypoints: number
}

export interface ValidationSummary {
  n_total: number
  n_evaluated: number
  n_pending: number
  n_error: number
  n_skipped: number
  precision: number
  recall: number
  f1: number
  fpr: number
  fnr: number
  tp: number
  fp: number
  fn: number
  tn: number
  per_class: Record<string, Record<string, number>>
  confusion_matrix: Record<string, Record<string, number>>
  holdout?: {
    n: number
    precision: number
    recall: number
    f1: number
    tp: number
    fp: number
    fn: number
    tn: number
  } | null
  request_id: string
}
