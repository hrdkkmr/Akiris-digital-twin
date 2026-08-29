import React from 'react'
import type { ObsResp, ObsRow } from './api'
import { ObsActionTag, ObsLevelTag, PriorityTag } from './components'

/** Innovation 1 — Observability Advisor UI.
 *  Answers: WHERE is observability poor? WHY does it matter? WHAT should we do? */
export function ObsAdvisorPanel({ data, onSelectStation }: { data?: ObsResp; onSelectStation?: (id: number) => void }) {
  const stations: ObsRow[] = [...(data?.stations ?? [])]
  const order: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
  stations.sort((a, b) => (order[a.priority] - order[b.priority]) || (a.confidence - b.confidence))
  const shown = stations.filter((s) => s.priority !== 'LOW' || s.observability_level !== 'HIGH').slice(0, 12)

  return (
    <div className="space-y-2">
      {shown.length === 0 && <div className="text-xs text-slate-500">No material observability gaps — all stations healthy.</div>}
      {shown.map((s) => (
        <div key={s.station_id} className={`rounded-lg border p-3 text-xs ${s.is_bottleneck ? 'border-red-800/60 bg-red-950/20' : 'border-slate-800 bg-slate-900/50'}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-cyan-300">{s.code}</span>
              <ObsLevelTag level={s.observability_level} />
              <PriorityTag priority={s.priority} />
              {s.is_bottleneck && <span className="rounded bg-red-600/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-red-200">bottleneck</span>}
            </div>
            <span className="font-mono text-[10px] text-slate-500">{s.archetype} · {s.sensor_profile} profile</span>
          </div>

          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px] text-slate-400 sm:grid-cols-4">
            <div>coverage <span className={s.coverage < 0.5 ? 'text-amber-300' : 'text-slate-200'}>{(s.coverage * 100).toFixed(0)}%</span></div>
            <div>completeness <span className="text-slate-200">{(s.completeness * 100).toFixed(0)}%</span></div>
            <div>freshness <span className={s.freshness === 'stale' ? 'text-red-300' : 'text-slate-200'}>{s.freshness}</span></div>
            <div>confidence <span className={s.confidence < 0.55 ? 'text-red-300' : s.confidence < 0.75 ? 'text-amber-300' : 'text-emerald-300'}>{(s.confidence * 100).toFixed(0)}%</span></div>
          </div>

          <div className="mt-2 text-slate-300">Why: {s.rationale}</div>

          {s.recommendations.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {s.recommendations.map((r, i) => (
                <li key={i} className="flex items-start gap-2 rounded border border-slate-800 bg-slate-950/60 px-2 py-1.5">
                  <ObsActionTag action={r.action_type} />
                  <span className="text-slate-200">{r.text}</span>
                </li>
              ))}
            </ul>
          )}

          {s.projected_confidence !== null && s.projected_confidence !== undefined && (
            <div className="mt-2 rounded border border-violet-800/50 bg-violet-950/30 px-2 py-1.5 font-mono text-[11px] text-violet-200">
              projected confidence (estimated): {(s.confidence * 100).toFixed(0)}% → ~{(s.projected_confidence * 100).toFixed(0)}%
              <span className="ml-2 text-violet-300/60">after recommended actions</span>
            </div>
          )}

          {onSelectStation && (
            <button onClick={() => onSelectStation(s.station_id)}
                    className="mt-2 rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400 hover:border-cyan-600/60 hover:text-cyan-300">
              View station details →
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

export function ObsAdvisorSummary({ data }: { data?: ObsResp }) {
  const s = data?.summary ?? {}
  return (
    <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
      {(['critical', 'high', 'medium', 'low'] as const).map((k) => (
        <span key={k} className={`rounded px-2 py-0.5 ${k === 'critical' ? 'bg-red-600/25 text-red-200' : k === 'high' ? 'bg-amber-600/25 text-amber-200' : k === 'medium' ? 'bg-cyan-700/25 text-cyan-200' : 'bg-slate-700/40 text-slate-300'}`}>
          {s[k] ?? 0} {k}
        </span>
      ))}
      <span className="text-slate-600">observability gaps</span>
    </div>
  )
}
