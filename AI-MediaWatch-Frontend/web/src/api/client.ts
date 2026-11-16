import type {
  AdversarialComparison,
  BiometricCapabilities,
  CampaignsResponse,
  CaseFile,
  CheckResponse,
  CheckResult,
  CollectorStartRequest,
  CollectorState,
  CytoscapeGraph,
  FeedbackIn,
  FeedbackListResponse,
  FeedbackOut,
  IngestRequest,
  IngestResponse,
  InvestigationResult,
  KeywordSuggestion,
  LogoReference,
  PrecisionRecallResponse,
  ReportResponse,
  RosterResponse,
  SystemInfo,
  UsageToday,
  ValidationSummary,
  VideoDetail,
  VideosList,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')
const API_KEY = import.meta.env.VITE_API_KEY ?? 'dev'

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY,
  }
  const token = localStorage.getItem('aimw_token')
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let message = `Request failed (HTTP ${res.status}). Please try again.`
    try {
      const body = JSON.parse(text)
      if (typeof body.detail === 'string') message = body.detail
      else if (typeof body.error === 'string') message = body.error
    } catch { /* Keep the fallback for non-JSON error responses. */ }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const h: Record<string, string> = { 'X-API-Key': API_KEY }
  const token = localStorage.getItem('aimw_token')
  if (token) h['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: h,
    body: form,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`)
  }
  return res.json() as Promise<T>
}

async function getBlob(path: string): Promise<Blob> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.blob()
}

export const api = {
  videos: {
    cancel: (id: string) => post<{ video_id: string; status: string }>(`/api/v1/videos/${encodeURIComponent(id)}/cancel`, {}),
    list: (limit = 100) =>
      get<VideosList>(`/api/v1/videos?limit=${limit}`),
    get: (id: string) =>
      get<VideoDetail>(`/api/v1/videos/${encodeURIComponent(id)}`),
  },

  reports: {
    get: (id: string) =>
      get<ReportResponse>(`/api/v1/reports/${encodeURIComponent(id)}`),
    exportPdf: (id: string) =>
      getBlob(`/api/v1/reports/${encodeURIComponent(id)}/export?format=pdf`),
    exportCsv: () =>
      getBlob('/api/v1/reports/export?format=csv'),
  },

  feedback: {
    post: (body: FeedbackIn) =>
      post<FeedbackOut>('/api/v1/feedback', body),
    list: () =>
      get<FeedbackListResponse>('/api/v1/feedback'),
  },

  graph: {
    get: () => get<CytoscapeGraph>('/api/v1/graph'),
    campaigns: () => get<CampaignsResponse>('/api/v1/campaigns'),
  },

  metrics: {
    precisionRecall: () =>
      get<PrecisionRecallResponse>('/api/v1/metrics/precision-recall'),
  },

  usage: {
    today: () => get<UsageToday>('/api/v1/usage/today'),
  },

  ingest: {
    url: (body: IngestRequest) =>
      post<IngestResponse>('/api/v1/ingest/url', body),
    manual: (form: FormData) => postForm<IngestResponse>('/api/v1/ingest/manual', form),
  },

  collector: {
    status: () => get<CollectorState>('/api/v1/collector/status'),
    start: (body: CollectorStartRequest) =>
      post<CollectorState>('/api/v1/collector/start', body),
    stop: () => post<CollectorState>('/api/v1/collector/stop', {}),
    suggestions: () =>
      get<{ suggestions: KeywordSuggestion[]; generated_at: string | null; flagged_count: number }>(
        '/api/v1/collector/suggestions',
      ),
    refreshSuggestions: () =>
      post<{ status: string }>('/api/v1/collector/suggestions/refresh', {}),
  },

  check: {
    submit: (body: { url?: string; text?: string }) =>
      post<CheckResponse>('/api/v1/check', body),
    submitBatch: (urls: string[]) =>
      post<{ results: CheckResponse[] }>('/api/v1/check/batch', { urls }),
    result: (videoId: string) =>
      get<CheckResult>(`/api/v1/check/${encodeURIComponent(videoId)}`),
  },

  validation: {
    summary: () => get<ValidationSummary>('/api/v1/validation/summary'),
  },

  cases: {
    get: (videoId: string) => get<CaseFile>(`/api/v1/cases/${encodeURIComponent(videoId)}`),
  },

  investigate: {
    roster: () => get<RosterResponse>('/api/v1/investigate/roster'),
    run: (videoId: string) =>
      post<InvestigationResult>(`/api/v1/investigate/${encodeURIComponent(videoId)}`, {}),
  },

  system: {
    info: () => get<SystemInfo>('/api/v1/system/info'),
  },

  adversarial: {
    compare: (text: string) =>
      post<AdversarialComparison>('/api/v1/adversarial/compare', { text }),
  },

  agents: {
    status: () => get<Record<string, unknown>>('/api/v1/agents/status'),
    listBanned: () => get<{ items: { value: string; type: string; banned_at: string }[] }>('/api/v1/agents/banned'),
    addBan: (value: string, type: string) =>
      post<{ items: { value: string; type: string; banned_at: string }[] }>('/api/v1/agents/banned', { value, type }),
    removeBan: (index: number) => {
      const h: Record<string, string> = { 'Content-Type': 'application/json', 'X-API-Key': API_KEY }
      const token = localStorage.getItem('aimw_token')
      if (token) h['Authorization'] = `Bearer ${token}`
      return fetch(`${BASE}/api/v1/agents/banned/${index}`, { method: 'DELETE', headers: h })
        .then(r => r.json()) as Promise<{ items: { value: string; type: string; banned_at: string }[] }>
    },
    aiDetect: (url: string) =>
      post<{
        status: string; url: string
        is_ai_generated: boolean | null; confidence: number | null
        suspected_tool: string | null; source_org: string | null
        evidence: string[]; full_reasoning: string
      }>('/api/v1/agents/ai-detect', { url }),
    scanFrames: (videoId: string) =>
      post<{
        status: string; video_id: string; title: string
        frames_scanned: number
        frames: {
          frame: string; status: string; reasoning: string
          risk_score: number; flags: string[]; logos_detected: string[]
          timestamp_sec: number; screenshot_url: string | null
        }[]
        all_logos_detected: string[]
        screenshots_saved: string[]
      }>(`/api/v1/agents/scan-frames/${encodeURIComponent(videoId)}`, {}),
    scannable: () =>
      get<{
        items: {
          video_id: string; title: string; platform: string
          n_frames: number; level: string | null; score: number | null
        }[]
      }>('/api/v1/agents/scannable'),
  },

  biometrics: {
    capabilities: () => get<BiometricCapabilities>('/api/v1/biometrics/capabilities'),
    logoReferences: () =>
      get<{ references: LogoReference[]; total: number; request_id: string }>(
        '/api/v1/biometrics/logos/references',
      ),
    reloadLogos: () =>
      post<{ reloaded: number; request_id: string }>('/api/v1/biometrics/logos/reload', {}),
  },
}
