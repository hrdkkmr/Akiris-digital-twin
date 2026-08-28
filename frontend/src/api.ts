import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export const BASE = (import.meta as any).env?.VITE_API_URL ?? '/api'

async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
  return res.json() as Promise<T>
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = `API ${res.status}: ${path}`
    try { msg = (await res.json())?.detail ?? msg } catch { /* keep default */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return res.json() as Promise<T>
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
  useQuery({ queryKey: ['bottlenecks', windowS ?? 'full'], queryFn: () => api<BNResp>(`/bottlenecks${windowS ? `?window_s=${windowS}` : ''}`), refetchInterval: 15_000 })
export const useVehicles = (status?: string, limit = 60) =>
  useQuery({ queryKey: ['vehicles', status, limit], queryFn: () => api<VehiclesResp>(`/vehicles?limit=${limit}${status ? `&status=${status}` : ''}`) })
export const useDefectRisks = (threshold = 0.4) =>
  useQuery({ queryKey: ['defect-risks', threshold], queryFn: () => api<RiskResp>(`/defect-risks?threshold=${threshold}&limit=40`), refetchInterval: 20_000 })
export const useJourney = (id: number | null, truth = false) =>
  useQuery({ queryKey: ['journey', id, truth], queryFn: () => api<JourneyResp>(`/vehicles/${id}/journey?truth=${truth}`), enabled: id !== null })
export const useFactors = (id: number | null) =>
  useQuery({ queryKey: ['factors', id], queryFn: () => api<FactorResp>(`/vehicles/${id}/contributing-factors`), enabled: id !== null })
export const useAnomalies = () => useQuery({ queryKey: ['anomalies'], queryFn: () => api<{ anomalies: AnomalyRow[] }>('/anomalies?limit=30'), refetchInterval: 20_000 })
export const useRecommendations = () => useQuery({ queryKey: ['recs'], queryFn: () => api<RecsResp>('/recommendations?limit=40'), refetchInterval: 20_000 })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: () => api<Summary>('/production/summary'), refetchInterval: 15_000 })
export const useROI = () => useQuery({ queryKey: ['roi'], queryFn: () => api<ROI>('/production/roi') })
export const useModelPerf = () => useQuery({ queryKey: ['modelperf'], queryFn: () => api<ModelPerf>('/model-performance'), refetchInterval: 30_000 })
export const useDQ = () => useQuery({ queryKey: ['dq'], queryFn: () => api<DQResp>('/data-quality'), refetchInterval: 30_000 })
export const useTrends = (bucket = 50) => useQuery({ queryKey: ['trends', bucket], queryFn: () => api<TrendResp>(`/production/trends?bucket_vehicles=${bucket}`), refetchInterval: 60_000 })
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
