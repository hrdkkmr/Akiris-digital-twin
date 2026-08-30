import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export const BASE = (import.meta as any).env?.VITE_API_URL ?? '/api'

/** Structured API error — carries the HTTP status and a human-readable message. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Shared fetch: checks HTTP status first, reads the body safely (JSON or
 * plain text), and surfaces a meaningful message instead of a JSON parse
 * crash like "Unexpected token 'I', 'Internal S...' is not valid JSON". */
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'Unable to reach the Akiris server. Check that the backend is running and try again.')
  }
  const text = await res.text().catch(() => '')
  if (!res.ok) {
    let detail = ''
    try {
      const body = JSON.parse(text)
      detail = typeof body?.detail === 'string' ? body.detail
        : typeof body?.error === 'string' ? body.error : ''
    } catch { detail = text }
    throw new ApiError(res.status,
      detail || `The server returned an error (HTTP ${res.status}).`)
  }
  if (!text) return undefined as T
  try { return JSON.parse(text) as T } catch {
    throw new ApiError(res.status, 'The server returned an unexpected response format.')
  }
}

/** Render-safe error message for UI error states. */
export function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return 'Something went wrong. Please try again.'
}

async function api<T>(path: string): Promise<T> {
  return apiFetch<T>(path)
}

// ===========================================================================
// Active factory / line selector (Configure Any Factory).
// The whole dashboard follows the selected factory: every data hook reads the
// active line and appends ?line_id=, and query keys carry the line id so a
// switch invalidates and refetches every view. Mirrors TwinContext on the
// backend — explicit ?line_id= still wins there; here we always pass it.
// ===========================================================================
let activeLineId: number | null = null
export const setActiveLineId = (id: number | null) => { activeLineId = id }
export const getActiveLineId = () => activeLineId

/** Append ?line_id=<active> to a path, preserving any existing query. */
const withLine = (path: string): string => {
  if (activeLineId == null) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}line_id=${activeLineId}`
}

/** Append the active line id to a query key so a factory switch refetches. */
const lineKey = (...parts: unknown[]) => [...parts, 'line', activeLineId]

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// ---------- types (mirror backend responses) ----------
export type StationSnap = {
  id: number; seq: number; code: string; zone: string; archetype: string
  sensor_profile: string; capacity: number; is_inspection: boolean
  queue_len: number; utilization: number; wear: number | null
  status: 'ok' | 'warning' | 'critical'; sensor_coverage: number
  recent_anomalies: number; vehicles_last_hour: number; machine_state: string
}
export type StationsResp = { line: { id: number; name: string; scenario: string }; sim_time: number; stations: StationSnap[] }
export type BNEvidence = { avg_utilization: number; max_queue: number; avg_abs_cycle_dev_s: number; downtime_s: number; samples: number }
export type BNRow = { station_id: number; seq: number; code: string; zone: string; score: number; status: string; confidence: number; evidence: BNEvidence }
export type BNResp = { generated_at: number; method: string; method_note: string; top: BNRow | null; ranking: BNRow[] }
export type VehicleRow = { id: number; vin: string; variant: string; status: string; quality_score: number | null; defect_probability: number | null; confidence: number | null }
export type VehiclesResp = { count: number; vehicles: VehicleRow[] }
export type RiskVehicle = VehicleRow & { data_completeness: number; top_features: { feature: string; importance: number }[]; outcome: boolean | null; correct: boolean | null }
export type RiskResp = { count: number; vehicles: RiskVehicle[] }
export type JourneyStep = { seq: number; station: string; zone: string; archetype: string; entered_at: number; exited_at: number | null; cycle_time: number | null; cycle_dev: number | null; anomaly_score: number | null; checklist: string | null; inspection: string | null; sensors: Record<string, { mean: number; std: number; max: number | null; unit: string; status: string }>; internal_flags_truth?: string[] }
export type JourneyResp = { vehicle: { id: number; vin: string; variant: string; status: string; started_at: number; quality_score: number | null }; steps: JourneyStep[]; outcome: { status: string; defect_found_at: string | null; true_root_causes: { station: string; contribution: number }[] | null } }
export type Factor = { station: string | null; zone: string | null; type: string; contribution: number; evidence: string[] }
export type FactorResp = { vehicle: string; outcome_station: string | null; language: string; candidates: Factor[]; caveat: string }
export type AnomalyRow = { vin: string | null; station: string; t: number; score: number; severity: string; detector: string }
export type Rec = { id: number; scope: string; ref: string; issue: string; action: string; severity: string; confidence: number; evidence: Record<string, any> }
export type RecsResp = { mode: string; count: number; recommendations: Rec[] }
export type Summary = { generated_at: number; span_hours: number; vehicles_total: number; completed: number; scrapped: number; wip: number; fpy: number; throughput_per_hour: number; avg_lead_time_s: number | null; defects_by_zone_found: Record<string, number>; maintenance_downtime_min: number }
export type ROI = { disclaimer: string; assumptions: Record<string, number>; current_state: Record<string, number>; improvement_scenarios: { assumed_defect_reduction: number; annual_savings_defects: number; assumed_downtime_reduction: number; annual_savings_downtime: number }[] }
export type ModelPerf = { registered_models: { id: number; name: string; algo: string; version: string; metrics: Record<string, any> }[]; live_prediction_metrics: Record<string, any> }
export type DQRow = { station_id: number; code: string; zone: string; sensor_profile: string; sensor_coverage: number; sensors_registered: number; completeness: number; freshness: string; anomaly_rate: number; analytics_confidence: number; vehicles_seen: number }
export type DQResp = { sim_time: number; stations: DQRow[] }
export type TrendBucket = { bucket: number; t_start: number; t_end: number; vehicles: number; scrapped: number; fpy: number; throughput_per_hour: number; avg_lead_time_s: number }
export type TrendResp = { bucket_size: number; buckets: TrendBucket[] }
export type StationDetail = {
  id: number; code: string; zone: string; archetype: string; sensor_profile: string
  baseline: { cycle_mu: number; cycle_sigma: number }
  sensors: { name: string; unit: string; status: string }[]
  current: { queue_len: number; utilization: number; wear: number | null }
  sensor_stats: { sensor: string; avg_mean: number; avg_std: number; max_seen: number | null; samples: number }[]
  data_quality: { sensor_coverage: number; completeness: number; freshness_s: number; anomaly_rate: number } | null
  bottleneck: { score: number; status: string; confidence: number; evidence: BNEvidence } | null
  recent_events: { vin: string; exited_at: number | null; cycle_time: number | null; cycle_dev: number | null; checklist: string | null; anomaly_score: number | null }[]
  recommendations: { issue: string; action: string; severity: string; confidence: number }[]
}

// ---------- hooks ----------
export const useStations = () => useQuery({ queryKey: ['stations'], queryFn: () => api<StationsResp>('/stations'), refetchInterval: 15_000 })
export const useBottlenecks = (windowS?: number) =>
  useQuery({ queryKey: lineKey('bottlenecks', windowS ?? 'full'), queryFn: () => api<BNResp>(withLine(`/bottlenecks${windowS ? `?window_s=${windowS}` : ''}`)), refetchInterval: 15_000 })
export const useVehicles = (status?: string, limit = 60) =>
  useQuery({ queryKey: lineKey('vehicles', status, limit), queryFn: () => api<VehiclesResp>(withLine(`/vehicles?limit=${limit}${status ? `&status=${status}` : ''}`)) })
export const useDefectRisks = (threshold = 0.4) =>
  useQuery({ queryKey: lineKey('defect-risks', threshold), queryFn: () => api<RiskResp>(withLine(`/defect-risks?threshold=${threshold}&limit=40`)), refetchInterval: 20_000 })
export const useJourney = (id: number | null, truth = false) =>
  useQuery({ queryKey: ['journey', id, truth], queryFn: () => api<JourneyResp>(`/vehicles/${id}/journey?truth=${truth}`), enabled: id !== null })
export const useFactors = (id: number | null) =>
  useQuery({ queryKey: ['factors', id], queryFn: () => api<FactorResp>(`/vehicles/${id}/contributing-factors`), enabled: id !== null })
export const useAnomalies = () => useQuery({ queryKey: lineKey('anomalies'), queryFn: () => api<{ anomalies: AnomalyRow[] }>(withLine('/anomalies?limit=30')), refetchInterval: 20_000 })
export const useRecommendations = () => useQuery({ queryKey: lineKey('recs'), queryFn: () => api<RecsResp>(withLine('/recommendations?limit=40')), refetchInterval: 20_000 })
export const useSummary = () => useQuery({ queryKey: lineKey('summary'), queryFn: () => api<Summary>(withLine('/production/summary')), refetchInterval: 15_000 })
export const useROI = () => useQuery({ queryKey: lineKey('roi'), queryFn: () => api<ROI>(withLine('/production/roi')) })
export const useModelPerf = () => useQuery({ queryKey: ['modelperf'], queryFn: () => api<ModelPerf>('/model-performance'), refetchInterval: 30_000 })
export const useDQ = () => useQuery({ queryKey: lineKey('dq'), queryFn: () => api<DQResp>(withLine('/data-quality')), refetchInterval: 30_000 })
export const useTrends = (bucket = 50) => useQuery({ queryKey: lineKey('trends', bucket), queryFn: () => api<TrendResp>(withLine(`/production/trends?bucket_vehicles=${bucket}`)), refetchInterval: 60_000 })
export const useStationDetail = (id: number | null) =>
  useQuery({ queryKey: ['station', id], queryFn: () => api<StationDetail>(`/stations/${id}`), enabled: id !== null })

// ---------- scenario injection (live twin continuation) ----------
export type InjectionKind = { kind: string; title: string; description: string }
export type InjectionReport = {
  status: string; kind: string; target_station: string | null; seed: number
  sim_window: { t_start: number; t_end: number }
  vehicles: Record<string, number | null>
  events_added: Record<string, number>
  analytics_refresh: Record<string, number | null>
  demo_guides: Record<string, string>
}
export const useInjectionKinds = () =>
  useQuery({ queryKey: ['injection-kinds'], queryFn: () => api<{ kinds: InjectionKind[] }>('/injection/kinds'), staleTime: Infinity })
export type InjectVars = { kind: string; vehicles: number; target_station?: string | null }
export const useInject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: InjectVars) => apiPost<InjectionReport>('/injection/inject', v),
    onSuccess: () => { void qc.invalidateQueries() },  // whole twin reacts on next paint
  })
}
export const useMlRefresh = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<Record<string, unknown>>('/ml/refresh', {}),
    onSuccess: () => { void qc.invalidateQueries() },
  })
}

// ---------- Innovation 1 — Observability Advisor ----------
export type ObsRec = { action_type: string; text: string; detail?: string }
export type ObsRow = {
  station_id: number; code: string; zone: string; archetype: string
  sensor_profile: string; coverage: number; completeness: number
  freshness: string; freshness_s: number; anomaly_rate: number; confidence: number
  observability_level: string; identified_gap: string
  recommendations: ObsRec[]; projected_confidence: number | null
  priority: string; rationale: string; is_bottleneck: boolean
}
export type ObsResp = { generated_at: number; disclaimer: string; summary: Record<string, number>; stations: ObsRow[] }
export const useObservabilityAdvisor = () =>
  useQuery({ queryKey: lineKey('obs-advisor'), queryFn: () => api<ObsResp>(withLine('/observability/advisor')), refetchInterval: 30_000 })

// ---------- Innovation 2 — Multi-causal contributing-factor analysis ----------
export type CFFactor = { factor: string; label: string; score: number; strength: string; evidence: string[] }
export type CFPattern = { type: string; title: string; description: string; strength: string; statistics: Record<string, number | string> }
export type CFResp = {
  station: string; station_id: number; zone: string; archetype: string
  incident_type: string; bottleneck: { status: string; score: number } | null
  factors: CFFactor[]; intermittent_patterns: CFPattern[]
  evidence_matrix: { legend: string[]; matrix: Record<string, Record<string, string>>; stations: string[] }
  analysis_note: string | null; disclaimer: string; caveat: string
}
export type VehicleCFResp = {
  vehicle: string; vehicle_id: number; batch: string | null; shift: string
  outcome: { status: string }; factors: CFFactor[]
  genealogy_note: string; disclaimer: string; caveat: string
}
// on-demand analysis (few seconds) — no refetch interval, long stale time
export const useStationFactors = (stationId: number | null) =>
  useQuery({ queryKey: ['cf-station', stationId], queryFn: () => api<CFResp>(`/contributing-factors/${stationId}`), enabled: stationId !== null, staleTime: 5 * 60_000 })
export const useVehicleCF = (vehicleId: number | null) =>
  useQuery({ queryKey: ['cf-vehicle', vehicleId], queryFn: () => api<VehicleCFResp>(`/contributing-factors/vehicle/${vehicleId}`), enabled: vehicleId !== null, staleTime: 5 * 60_000 })
export const usePatterns = () =>
  useQuery({ queryKey: lineKey('cf-patterns'), queryFn: () => api<{ patterns: CFPattern[] }>(withLine('/contributing-factors/patterns')), staleTime: 5 * 60_000 })

// ---------- Innovation 3 — Safe change validation + shadow simulation ----------
export type ShadowChange = {
  id: string; kind: string; station: string; title: string
  current: string; proposed: string; reason: string; impact: string
  expected: string; selected?: boolean
}
export type ShadowWindows = {
  now: number; next_window_start: number; next_window_end: number
  countdown_s: number; duration_h: number; window_label: string
  queued_items: number; capacity: number
}
export type SimScenario = {
  id: number; name: string; created_at: number; status: string
  changes: ShadowChange[]; current_metrics: Record<string, number | string>
  shadow_metrics: Record<string, number | string>
  risk_level: string; risk_detail: { level: string; score: number; details: string[]; note: string }
  warnings: string[]; recommendation: string | null; maintenance_status: string; note: string
}
export type QueueItem = {
  id: number; scenario_id: number; station_code: string; change: string
  priority: string; risk_level: string; estimated_duration_min: number
  target_window: number; status: string
}
const postJson = <T>(url: string, body: unknown) =>
  apiPost<T>(url, body)

export const useShadowChanges = () =>
  useQuery({ queryKey: lineKey('shadow-changes'), queryFn: () => api<{ mode: string; count: number; changes: ShadowChange[] }>(withLine('/shadow/changes')), staleTime: 60_000 })
export const useShadowWindows = () =>
  useQuery({ queryKey: lineKey('shadow-windows'), queryFn: () => api<ShadowWindows>(withLine('/shadow/windows')), staleTime: 30_000, refetchInterval: 30_000 })
export const useSimHistory = () =>
  useQuery({ queryKey: lineKey('sim-history'), queryFn: () => api<{ count: number; scenarios: SimScenario[] }>(withLine('/shadow/scenarios')), staleTime: 15_000 })
export const useMaintenanceQueue = () =>
  useQuery({ queryKey: lineKey('maint-queue'), queryFn: () => api<{ count: number; items: QueueItem[] }>(withLine('/shadow/queue')), staleTime: 15_000 })
export const useScenarioDetail = (id: number | null) =>
  useQuery({ queryKey: ['sim-scenario', id], queryFn: () => api<SimScenario>(`/shadow/scenarios/${id}`), enabled: id !== null, staleTime: 0 })
export const createScenario = (changes: ShadowChange[]) => postJson<SimScenario>('/shadow/scenarios', { changes })
export const runScenario = (id: number) => postJson<SimScenario>(`/shadow/scenarios/${id}/run`, {})
export const queueScenario = (id: number, acknowledge = true) => postJson<{ status: string; scenario: string; items: number; target_window: number; note?: string; error?: string }>(`/shadow/scenarios/${id}/queue`, { acknowledge })

// ---------- Innovation 4 — Defect traceback & propagation ----------
export type DefectRow = { id: number; vehicle_id: number; vin: string; station: string; t: number; severity: string }
export type SuspectedOrigin = { station_id: number; code: string; zone: string; score: number; strength: string; pass_t: number; evidence: string[] }
export type ExposedUnit = { vehicle_id: number; vin: string; status: string; batch: string | null; shift: string; exposure_level: string; exposure_ts: number; confirmed_defect: boolean }
export type DefectTrace = {
  defect_id: number; defect_severity: string; vehicle: string; vehicle_id: number; batch: string | null
  detected_at: number; detection_station: string; journey: string[]
  suspected_origins: SuspectedOrigin[]; multiple_plausible_origins: boolean
  exposure_window: { station: string; start: number; end: number; confidence: string; reason: string[] } | null
  potentially_exposed_units: { total: number; confirmed_defects: number; potentially_affected: number; units: ExposedUnit[] }
  common_exposures: { factor: string; value: string; share: number; label: string }[]
  propagation_risk: { level: string; score: number; note: string; drivers: Record<string, number | string | boolean> }
  containment_recommendations: string[]
  inspection_priority: Record<string, number>
  data_confidence: string; traceability_note: string | null; caveat: string; disclaimer: string
}
export const useDefects = (limit = 12) =>
  useQuery({ queryKey: lineKey('defects', limit), queryFn: () => api<{ count: number; defects: DefectRow[] }>(withLine(`/defects?limit=${limit}`)), staleTime: 30_000 })
export const useDefectTrace = (defectId: number | null) =>
  useQuery({ queryKey: ['defect-trace', defectId], queryFn: () => api<DefectTrace>(`/defects/${defectId}/trace`), enabled: defectId !== null, staleTime: 5 * 60_000 })

// ---------- Innovation 5 — Prediction validation & AI trust ----------
export type TrustHistoryRow = { id: number; vehicle_id: number; vin: string; created_at: number; probability: number; confidence: number; actual: boolean | null; model_version: string; station: string | null; result: string }
export type StationTrust = { station: string; predictions: number; validated: number; precision: number; recall: number; false_alarm_rate: number; tp: number; fp: number }
export type PredictionTrust = {
  generated_at: number; note: string
  overall: { validated: number; pending: number; precision?: number; recall?: number; false_alarm_rate?: number; f1?: number; accuracy?: number; fpr?: number; fnr?: number; tp?: number; fp?: number; tn?: number; fn?: number; insufficient?: boolean }
  history: TrustHistoryRow[]
  station_trust: StationTrust[]
  false_alarm_monitor: { rate: number; worst_station: string | null; alarms: number; false_alarms: number; trend: { bucket: number; alarms: number; false_alarm_rate: number }[]; direction: string }
  confidence_bins: { range: string; n: number; correct_rate: number }[]
  observability_notes: { station: string; precision: number; coverage: number; analytics_confidence: number; note: string }[]
  model_management: {
    production: { id: number; version: string; metrics: Record<string, number | string>; status: string } | null
    candidate: { id: number; version: string; metrics: Record<string, number | string>; status: string } | null
    next_window_start: number; countdown_s: number; window_label: string
  }
}
export const usePredictionTrust = () =>
  useQuery({ queryKey: lineKey('pred-trust'), queryFn: () => api<PredictionTrust>(withLine('/predictions/trust')), staleTime: 15_000, refetchInterval: 60_000 })
/** Revalidate the prediction system on validated outcomes → creates a
 * candidate prediction policy for human review (never touches production). */
export const revalidateCandidate = () => postJson<Record<string, unknown>>('/predictions/trust/revalidate', {})
// legacy alias kept for callers of the old endpoint name
export const retrainCandidate = revalidateCandidate
export const approveCandidate = (approve: boolean) => postJson<Record<string, unknown>>('/predictions/trust/approve', { approve })
/** Controlled deployment — backend-gated to the maintenance window.
 * simulateWindow=true explicitly simulates window execution (prototype). */
export const deployCandidate = (simulateWindow = false) => postJson<Record<string, unknown>>('/predictions/trust/deploy', { simulate_window: simulateWindow })
export const useVehicleDefect = (vehicleId: number | null) =>
  useQuery({ queryKey: ['vehicle-defect', vehicleId], queryFn: () => api<{ count: number; defects: DefectRow[] }>(`/defects?vehicle_id=${vehicleId}&limit=1`), enabled: vehicleId !== null, staleTime: 30_000 })

// ===========================================================================
// Configure Any Factory — factory setup API (mirrors backend /factories).
// ===========================================================================
export type CoverageBuckets = { high: number; medium: number; low: number; none: number }
export type FactoryLineSummary = {
  id: number; code: string; name: string; description: string | null
  stations: number; has_data: boolean
  coverage: CoverageBuckets; equipment: Record<string, number>
  manual_stations: number
}
export type FactorySummary = {
  code: string; name: string; location: string | null; description: string | null
  lines: FactoryLineSummary[]; is_active: boolean
}
export type FactoriesResp = { count: number; factories: FactorySummary[] }
export type ActiveContext = {
  factory_code: string; factory_name: string
  line_id: number; line_code: string; line_name: string
  has_data: boolean
}
export type StationDetailRow = {
  id: number; code: string; name: string; archetype: string | null
  equipment_type: string; zone: string; equipment_generation: string
  criticality: string; sensors: string[]
  manual_inspection: boolean; coverage: number; observability: string
  analytics_confidence: number | null
}
export type FactoryDetailLine = {
  id: number; code: string; name: string; description: string | null
  stations: StationDetailRow[]
  coverage: CoverageBuckets; manual_stations: number
}
export type FactoryDetail = {
  factory: FactorySummary
  lines: FactoryDetailLine[]
  warnings: string[]
}
export type CreateFactoryResult = {
  status: string; factory: FactorySummary; lines: { code: string; stations: number }[]
  warnings: string[]; active_line_id: number | null
}
export type SimulateResult = {
  status: string; simulated: boolean; line_id: number; scenario: string; seed: number
  vehicles: number; ingested: { spawned: number; completed: number; scrapped: number; wall_seconds: number }
  note: string
}

export const useFactories = () =>
  useQuery({ queryKey: ['factories'], queryFn: () => api<FactoriesResp>('/factories'), staleTime: 15_000, refetchInterval: 60_000 })
export const useActiveFactory = () =>
  useQuery({ queryKey: ['factory-active'], queryFn: () => api<ActiveContext>('/factories/active'), staleTime: 10_000, refetchInterval: 30_000 })
export const useFactoryDetail = (code: string | null) =>
  useQuery({ queryKey: ['factory-detail', code], queryFn: () => api<FactoryDetail>(`/factories/${code}`), enabled: code !== null, staleTime: 15_000 })

export const useCreateFactory = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: unknown) => apiPost<CreateFactoryResult>('/factories', payload),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['factories'] }) },
  })
}
export const useActivateFactory = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => apiPost<{ status: string; active: ActiveContext }>(`/factories/${code}/activate`, {}),
    onSuccess: () => { void qc.invalidateQueries() },  // every view refetches for the new factory
  })
}
export const useSimulateFactory = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { code: string; vehicles?: number; seed?: number }) =>
      apiPost<SimulateResult>(`/factories/${vars.code}/simulate?vehicles=${vars.vehicles ?? 200}&seed=${vars.seed ?? 42}`, {}),
    onSuccess: () => { void qc.invalidateQueries() },
  })
}
