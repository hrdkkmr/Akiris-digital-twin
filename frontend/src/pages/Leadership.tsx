import React from 'react'
import { useRecommendations, useROI, useSummary } from '../api'
import { KpiCard, Panel } from '../components'

const money = (n: number | undefined) =>
  n === undefined ? '—' : n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : `$${Math.round(n).toLocaleString()}`

/** LEADERSHIP — business case: costs, ROI scenarios, rollout rationale.
 *  Every number traces to a labeled assumption (never an unsupported claim). */
export default function Leadership() {
  const { data: roi } = useROI()
  const { data: sum } = useSummary()
  const { data: recs } = useRecommendations()

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-700 bg-slate-900/60 px-4 py-2 text-xs text-slate-400">
        {roi?.disclaimer ?? '…'}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Annualized defect cost" value={money(roi?.current_state.annualized_defect_cost)}
                 sub={`from ${sum?.scrapped ?? 0} scrapped in sim`} tone="text-red-300" />
        <KpiCard label="Annualized downtime cost" value={money(roi?.current_state.annualized_downtime_cost)}
                 sub={`${sum?.maintenance_downtime_min ?? 0} min in sim`} tone="text-amber-300" />
        <KpiCard label="First-pass yield" value={sum ? `${(sum.fpy * 100).toFixed(1)}%` : '—'} />
        <KpiCard label="Throughput" value={`${sum?.throughput_per_hour ?? '—'} veh/h`} sub="vs takt plan 80/h" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Improvement scenarios (annualized, assumption-driven)">
          <table className="w-full text-xs font-mono">
            <thead><tr className="text-left text-slate-500">
              <th className="py-1">defect reduction*</th><th>savings (defects)</th><th>savings (downtime)</th><th>total</th>
            </tr></thead>
            <tbody>
              {(roi?.improvement_scenarios ?? []).map((s) => (
                <tr key={s.assumed_defect_reduction} className="border-t border-slate-800">
                  <td className="py-1.5">{(s.assumed_defect_reduction * 100).toFixed(0)}%</td>
                  <td className="text-emerald-300">{money(s.annual_savings_defects)}</td>
                  <td className="text-emerald-300">{money(s.annual_savings_downtime)}</td>
                  <td className="font-semibold text-emerald-200">{money(s.annual_savings_defects + s.annual_savings_downtime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 text-[10px] text-slate-500">* assumed, not claimed — per-scenario improvement is a labeled knob (TWIN_* env vars).</div>
        </Panel>

        <Panel title="Assumptions (all configurable)">
          <div className="space-y-1.5 font-mono text-xs">
            {roi && Object.entries(roi.assumptions).map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-slate-800/60 py-1">
                <span className="text-slate-400">{k}</span><span>{typeof v === 'number' && v > 100 ? `$${v.toLocaleString()}` : v}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded border border-slate-800 bg-slate-900/50 p-2 text-[11px] text-slate-400">
            Scaling model: the twin core is site-agnostic — a new plant is a YAML configuration
            (stations, archetypes, sensor mix), not new code. Rollout cost ≈ configuration +
            instrumentation for observed gaps, not re-engineering.
          </div>
        </Panel>
      </div>

      <Panel title={`Top advisory actions this period (${recs?.count ?? 0})`}>
        <div className="grid gap-2 md:grid-cols-2">
          {(recs?.recommendations.slice(0, 6) ?? []).map((r) => (
            <div key={r.id} className="rounded border border-slate-800 bg-slate-900/50 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${r.severity === 'high' ? 'bg-red-600/30 text-red-200' : r.severity === 'medium' ? 'bg-amber-600/30 text-amber-200' : 'bg-slate-700 text-slate-300'}`}>{r.severity}</span>
                <span className="font-mono text-[10px] text-slate-500">{(r.confidence * 100).toFixed(0)}% conf</span>
              </div>
              <div className="mt-1.5 text-slate-200">{r.issue}</div>
              <div className="mt-1 text-slate-400">→ {r.action}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-[10px] text-slate-500">
          Deployment posture: read-only / shadow mode — the twin observes, analyzes and recommends.
          Control-path automation is a future phase gated on validation + scheduled maintenance windows (IEC 62443 zones/conduits).
        </div>
      </Panel>
    </div>
  )
}
