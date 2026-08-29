
import type { ObsResp, ObsRow } from './api'
import { Legend, ObsActionTag, ObsLevelTag, PriorityTag, TechDetails } from './components'

/** Innovation 1 — Observability Advisor UI.
 *  Answers: WHERE is observability poor? WHY does it matter? WHAT should we do?
 *  Human-readable decision first; technical values inside "Technical details". */
export function ObsAdvisorPanel({ data, onSelectStation }: { data?: ObsResp; onSelectStation?: (id: number) => void }) {
  const stations: ObsRow[] = [...(data?.stations ?? [])]
  const order: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
  stations.sort((a, b) => (order[a.priority] - order[b.priority]) || (a.confidence - b.confidence))
  const shown = stations.filter((s) => s.priority !== 'LOW' || s.observability_level !== 'HIGH').slice(0, 12)

  return (
    <div className="space-y-2">
      <Legend items={[
        { key: 'critical', label: 'Critical gap' },
        { key: 'warning', label: 'Needs attention' },
        { key: 'info', label: 'Monitor' },
      ]} />
      {shown.length === 0 && <div className="text-xs text-slate-500">No material observability gaps — all stations healthy.</div>}
      {shown.map((s) => {
        const limited = s.coverage < 0.5
        const headline = limited
          ? `Limited visibility at ${s.code}`
          : s.freshness === 'stale'
            ? `Stale sensor data at ${s.code}`
            : `Observability review — ${s.code}`
        return (
          <div key={s.station_id} className={`rounded-lg border p-3 text-xs ${s.is_bottleneck ? 'border-red-800/60 bg-red-950/20' : 'border-slate-800 bg-slate-900/50'}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-cyan-300">{s.code}</span>
                <ObsLevelTag level={s.observability_level} />
                <PriorityTag priority={s.priority} />
                {s.is_bottleneck && (
                  <span className="inline-flex items-center gap-1 rounded bg-red-600/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-red-200">
                    <span className="h-1.5 w-1.5 rounded-full bg-red-400" /> bottleneck
                  </span>
                )}
              </div>
              <span className="font-mono text-[10px] text-slate-500">{s.archetype} · {s.sensor_profile} profile</span>
            </div>

            {/* human-readable decision */}
            <div className="mt-2 text-slate-100">{headline}</div>
            {limited && (
              <div className="mt-0.5 text-[11px] text-slate-400">
                Only {(s.coverage * 100).toFixed(0)}% of the expected sensor signals are available at this station.
              </div>
            )}
            <div className="mt-1 text-[11px] text-slate-300">
              <b className="text-slate-400">Why it matters:</b> {s.rationale}
            </div>

            {s.recommendations.length > 0 && (
              <div className="mt-2">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Recommendation</div>
                <ul className="space-y-1.5">
                  {s.recommendations.map((r, i) => (
                    <li key={i} className="flex items-start gap-2 rounded border border-slate-800 bg-slate-950/60 px-2 py-1.5">
                      <ObsActionTag action={r.action_type} />
                      <span className="text-slate-200">{r.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {s.projected_confidence !== null && s.projected_confidence !== undefined && (
              <div className="mt-2 inline-flex items-center gap-2 rounded border border-violet-800/50 bg-violet-950/30 px-2 py-1.5 text-[11px] text-violet-200">
                <span>📈 Expected gain (estimated): {(s.confidence * 100).toFixed(0)}% → ~{(s.projected_confidence * 100).toFixed(0)}%</span>
                <span className="text-violet-300/60">after recommended actions</span>
              </div>
            )}

            <TechDetails label="Technical details">
              coverage {(s.coverage * 100).toFixed(0)}% · completeness {(s.completeness * 100).toFixed(0)}% ·
              freshness {s.freshness} ({s.freshness_s}s) · analytics confidence {(s.confidence * 100).toFixed(0)}% ·
              anomaly rate {(s.anomaly_rate * 100).toFixed(1)}%{s.identified_gap ? ` · gap: ${s.identified_gap}` : ''}
            </TechDetails>

            {onSelectStation && (
              <button onClick={() => onSelectStation(s.station_id)}
                      className="mt-2 rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400 hover:border-cyan-600/60 hover:text-cyan-300">
                View station details →
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function ObsAdvisorSummary({ data }: { data?: ObsResp }) {
  const s = data?.summary ?? {}
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <Legend items={[
        { key: 'critical', label: 'Critical gaps' },
        { key: 'warning', label: 'Needs attention' },
        { key: 'info', label: 'Monitor' },
        { key: 'ok', label: 'Healthy' },
      ]} />
      <div className="flex items-center gap-2 font-mono">
        {(['critical', 'high', 'medium', 'low'] as const).map((k) => (
          <span key={k} className={`inline-flex items-center gap-1 rounded px-2 py-0.5 ${k === 'critical' ? 'bg-red-600/25 text-red-200' : k === 'high' ? 'bg-amber-600/25 text-amber-200' : k === 'medium' ? 'bg-cyan-700/25 text-cyan-200' : 'bg-slate-700/40 text-slate-300'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${k === 'critical' ? 'bg-red-400' : k === 'high' ? 'bg-amber-400' : k === 'medium' ? 'bg-cyan-400' : 'bg-slate-400'}`} />
            {s[k] ?? 0} {k}
          </span>
        ))}
        <span className="text-slate-600">stations with gaps</span>
      </div>
    </div>
  )
}
