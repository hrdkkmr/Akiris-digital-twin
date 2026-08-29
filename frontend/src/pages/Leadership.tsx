import React, { useState } from 'react'
import { useDefectTrace, useDefects, useMaintenanceQueue, useObservabilityAdvisor, usePatterns, useRecommendations, useROI, useShadowWindows, useSimHistory, useStations, useSummary } from '../api'
import { KpiCard, ObsLevelTag, Panel, simClock } from '../components'
import { ObsAdvisorPanel, ObsAdvisorSummary } from '../ObsAdvisor'
import { PatternCard } from '../CFAnalysis'
import { MaintenanceCountdown, MaintenanceQueuePanel, RiskBadge, ShadowSimLab, SimHistory } from '../ShadowSim'
import { DefectTracePanel } from '../DefectTraceback'
import { PredictionTrustPanel } from '../PredictionTrust'

const money = (n: number | undefined) =>
  n === undefined ? '—' : n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : `$${Math.round(n).toLocaleString()}`

/** LEADERSHIP — business case: costs, ROI scenarios, rollout rationale.
 *  Every number traces to a labeled assumption (never an unsupported claim). */
export default function Leadership({ onSelectStation }: { onSelectStation?: (id: number) => void }) {
  const { data: roi } = useROI()
  const { data: sum } = useSummary()
  const { data: recs } = useRecommendations()
  const { data: obs } = useObservabilityAdvisor()
  const { data: patterns } = usePatterns()
  const { data: stations } = useStations()
  const codeToId = Object.fromEntries((stations?.stations ?? []).map((s) => [s.code, s.id]))

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

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Station observability (coverage → analytics confidence)"
               right={<ObsAdvisorSummary data={obs} />}>
          <div className="max-h-72 overflow-y-auto pr-1">
            <table className="w-full text-xs font-mono">
              <thead className="sticky top-0 bg-slate-900 text-left text-slate-500">
                <tr><th className="py-1">stn</th><th>profile</th><th>cover</th><th>compl.</th><th>fresh</th><th>conf</th><th>level</th></tr>
              </thead>
              <tbody>
                {(obs?.stations ?? []).map((s) => (
                  <tr key={s.code} className="border-t border-slate-800">
                    <td className="py-1 text-cyan-300">{s.code}</td>
                    <td>{s.sensor_profile}</td>
                    <td className={s.coverage < 0.5 ? 'text-amber-300' : ''}>{(s.coverage * 100).toFixed(0)}%</td>
                    <td>{(s.completeness * 100).toFixed(0)}%</td>
                    <td className={s.freshness === 'stale' ? 'text-red-300' : ''}>{s.freshness}</td>
                    <td className={s.confidence < 0.55 ? 'text-red-300' : s.confidence < 0.75 ? 'text-amber-300' : 'text-emerald-300'}>
                      {(s.confidence * 100).toFixed(0)}%</td>
                    <td><ObsLevelTag level={s.observability_level} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-[10px] text-slate-500">
            conf = 0.45·coverage + 0.35·completeness + 0.20·freshness − 0.30·anomaly density — persisted per station in data_quality_metrics.
            {obs && <span className="ml-1 text-slate-600">The Observability Advisor below turns this table into actions.</span>}
          </div>
        </Panel>

        <Panel title="🧭 Observability Advisor — WHERE is observability poor, WHY, and WHAT to do"
               right={<span className="text-[10px] uppercase tracking-wide text-slate-500">Innovation 1</span>}>
          <ObsAdvisorPanel data={obs} onSelectStation={onSelectStation} />
          {obs && (
            <div className="mt-3 rounded border border-slate-800 bg-slate-900/50 p-2 text-[10px] text-slate-500">
              {obs.disclaimer}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="High-impact intermittent patterns — where incidents cluster over time (Innovation 2)"
             right={<span className="text-[10px] uppercase tracking-wide text-slate-500">observed association</span>}>
        {(patterns?.patterns.length ?? 0) === 0 && <div className="text-xs text-slate-500">No statistically meaningful patterns in the current dataset.</div>}
        <div className="grid gap-2 md:grid-cols-2">
          {(patterns?.patterns ?? []).map((p, i) => <PatternCard key={i} pattern={p} />)}
        </div>
      </Panel>

      <LeadershipTraceSection codeToId={codeToId} onSelectStation={onSelectStation} />

      <Panel title="🧠 AI Prediction Trust — is the AI reliable where it matters? (Innovation 5)"
             right={<span className="text-[10px] uppercase tracking-widest text-slate-500">validated against real outcomes</span>}>
        <PredictionTrustPanel
          onOpenStation={(code) => codeToId[code] && onSelectStation?.(codeToId[code])}
          onInvestigateFalseAlarms={(code) => codeToId[code] && onSelectStation?.(codeToId[code])} />
      </Panel>

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

      <Panel title="🧪 Safe change validation — shadow simulation lab (Innovation 3)"
             right={<span className="text-[10px] uppercase tracking-widest text-slate-500">no change touches production</span>}>
        <LeadershipSimSection />
      </Panel>
    </div>
  )
}

/** Executive defect-propagation overview: trace a detected defect back to
 * suspected origins and forward to potentially exposed units. */
function LeadershipTraceSection({ codeToId, onSelectStation }: {
  codeToId: Record<string, number>; onSelectStation?: (id: number) => void
}) {
  const { data: defects } = useDefects(6)
  const [traceId, setTraceId] = useState<number | null>(null)
  const { data: trace } = useDefectTrace(traceId)
  return (
    <Panel title="🛑 Defect propagation overview (Innovation 4)"
           right={<span className="text-[10px] uppercase tracking-widest text-slate-500">trace back · trace forward</span>}>
      <div className="grid gap-1.5 md:grid-cols-3">
        {(defects?.defects ?? []).map((d) => (
          <div key={d.id} className="rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-mono text-cyan-300">{d.vin}</span>
              <span className="font-mono text-[10px] text-slate-500">{simClock(d.t)}</span>
            </div>
            <div className="mt-0.5 text-[11px] text-slate-400">defect at {d.station}</div>
            <button onClick={() => setTraceId(d.id)}
                    className={`mt-1 w-full rounded-md px-2 py-1 text-[10px] transition ${traceId === d.id ? 'bg-cyan-800/70 text-white' : 'border border-red-700/60 bg-red-950/40 text-red-200 hover:bg-red-900/50'}`}>
              TRACE DEFECT
            </button>
          </div>
        ))}
      </div>
      {trace && (
        <div className="mt-2 rounded border border-slate-700/70 bg-slate-900/60 p-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-slate-400">Defect investigation · {trace.vehicle}</span>
            <button onClick={() => setTraceId(null)} className="text-[10px] text-slate-500 hover:text-slate-300">✕ close</button>
          </div>
          <DefectTracePanel trace={trace} onSelectStation={(id) => onSelectStation?.(id)} />
        </div>
      )}
    </Panel>
  )
}

/** Executive view of the shadow-simulation workflow: queue status, history,
 * next maintenance window and the full lab. */
function LeadershipSimSection() {
  const { data: win } = useShadowWindows()
  const { data: queue } = useMaintenanceQueue()
  const [openId, setOpenId] = useState<number | null>(null)

  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-3">
        <MaintenanceCountdown win={win} />
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-400">Maintenance queue</div>
          <div className="text-xs text-slate-300">
            {queue?.count ?? 0} item(s) queued
            <span className="ml-2 text-slate-500">capacity {win?.capacity ?? '—'}</span>
          </div>
          <div className="mt-1.5 max-h-28 space-y-1 overflow-y-auto pr-0.5">
            <MaintenanceQueuePanel items={queue?.items ?? []} windowStart={win?.next_window_start} />
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-400">Simulation history</div>
          <div className="max-h-28 space-y-1 overflow-y-auto pr-0.5">
            <SimHistory onOpen={setOpenId} />
          </div>
        </div>
      </div>

      {openId && <ScenarioDetailPanel id={openId} onClose={() => setOpenId(null)} />}

      <ShadowSimLab />
    </div>
  )
}

function ScenarioDetailPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const [detail, setDetail] = React.useState<import('../api').SimScenario | null>(null)
  React.useEffect(() => {
    let alive = true
    fetch(`/api/shadow/scenarios/${id}`).then((r) => r.json()).then((d) => { if (alive) setDetail(d) }).catch(() => {})
    return () => { alive = false }
  }, [id])
  if (!detail) return <div className="rounded border border-slate-800 bg-slate-900/40 p-2 text-xs text-slate-400">loading {id}…</div>
  const d = detail as unknown as { error?: string }
  if (d.error) return <div className="text-xs text-red-300">{d.error}</div>
  return (
    <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-bold text-cyan-200">{detail.name}</span>
        <div className="flex items-center gap-2">
          <RiskBadge level={detail.risk_level} />
          <button onClick={onClose} className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-800">✕</button>
        </div>
      </div>
      <div className="mt-2 grid gap-1.5 md:grid-cols-2">
        {detail.changes.map((c, i) => (
          <div key={i} className="rounded bg-slate-800/60 px-2 py-1 text-[11px] text-slate-300">
            <span className="text-cyan-300">{c.station}</span> — {c.title} ({c.current} → {c.proposed})
          </div>
        ))}
      </div>
      <div className="mt-2 text-[10px] italic text-slate-500">{detail.note}</div>
    </div>
  )
}
