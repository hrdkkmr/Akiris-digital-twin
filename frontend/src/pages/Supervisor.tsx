import React, { useState } from 'react'
import { useAnomalies, useBottlenecks, useDefectRisks, useInjectionKinds, useInject, useMlRefresh, useObservabilityAdvisor, useRecommendations, useStations } from '../api'
import { ConfidenceTag, KpiCard, Panel, StationTile, ZoneLabel, simClock } from '../components'
import { MaintenanceCountdown, ShadowSimLab } from '../ShadowSim'
import { DefectTracePanel } from '../DefectTraceback'
import { PredictionTrustPanel } from '../PredictionTrust'
import { useDefectTrace, useDefects, useShadowWindows } from '../api'

/** SCENARIO INJECTION — continue the live twin with a disruption (demo/drill layer). */
function InjectionPanel() {
  const { data: kinds } = useInjectionKinds()
  const inject = useInject()
  const mlRefresh = useMlRefresh()
  const [target, setTarget] = useState('S20')
  const [vehicles, setVehicles] = useState(300)

  const busy = inject.isPending || mlRefresh.isPending
  const rep = inject.data

  return (
    <Panel title="🧪 Scenario injection — continue the live twin with a disruption">
      <div className="flex flex-wrap items-center gap-2">
        {(kinds?.kinds ?? []).map((k) => (
          <button key={k.kind} disabled={busy}
                  title={k.description}
                  onClick={() => inject.mutate({ kind: k.kind, vehicles, target_station: k.kind === 'bottleneck_shock' ? target : null })}
                  className="rounded-md border border-cyan-700/60 bg-cyan-950/40 px-3 py-1.5 text-xs text-cyan-200 transition hover:bg-cyan-900/50 disabled:opacity-40">
            {k.title}
          </button>
        ))}
        <label className="ml-1 flex items-center gap-1 text-[10px] text-slate-500">
          veh <select value={vehicles} disabled={busy} onChange={(e) => setVehicles(+e.target.value)}
                  className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 font-mono text-[10px] text-slate-300">
            {[100, 300, 500].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1 text-[10px] text-slate-500">
          shock @ <input value={target} maxLength={4} disabled={busy}
                  onChange={(e) => setTarget(e.target.value.toUpperCase())}
                  className="w-12 rounded border border-slate-700 bg-slate-900 px-1 py-0.5 font-mono text-[10px] text-slate-300" />
        </label>
        {busy && <span className="animate-pulse text-xs text-amber-300">
          {inject.isPending ? 'simulating continuation… (~15–40s)' : 'retraining & rescoring… (~20–60s)'}</span>}
        {rep && (
          <button onClick={() => mlRefresh.mutate()} disabled={busy}
                  className="ml-auto rounded-md border border-violet-700/60 bg-violet-950/40 px-3 py-1.5 text-xs text-violet-200 hover:bg-violet-900/50 disabled:opacity-40">
            Retrain & rescore fleet (/ml/refresh)
          </button>
        )}
      </div>

      {inject.isError && (
        <div className="mt-2 rounded border border-red-700/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          injection failed: {String((inject.error as Error)?.message)}
        </div>
      )}
      {mlRefresh.isError && (
        <div className="mt-2 rounded border border-red-700/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          refresh failed: {String((mlRefresh.error as Error)?.message)}
        </div>
      )}
      {rep && (
        <div className="mt-3 rounded-md border border-emerald-800/60 bg-emerald-950/30 px-3 py-2 text-xs">
          <div className="font-mono text-emerald-200">
            ✓ {rep.kind} injected @ seed {rep.seed} · sim window {rep.sim_window.t_start.toFixed(0)}→{rep.sim_window.t_end.toFixed(0)}s ·
            spawned {rep.vehicles.injected_spawned} · completed {rep.vehicles.injected_completed} · scrapped {rep.vehicles.injected_scrapped} ·
            fleet now {rep.vehicles.fleet_total}
          </div>
          <div className="mt-1 font-mono text-[11px] text-emerald-300/80">
            anomalies {rep.analytics_refresh.anomalies_written ?? 0} · events scored {rep.analytics_refresh.events_scored ?? 0} ·
            dq rows {rep.analytics_refresh.data_quality_rows ?? 0} · recommendations {rep.analytics_refresh.recommendations ?? 0}
          </div>
          <div className="mt-1.5 space-y-0.5 text-[11px] text-slate-300">
            {Object.values(rep.demo_guides).map((g, i) => <div key={i}>→ {g}</div>)}
          </div>
          <div className="mt-1 text-[10px] text-slate-500">
            the line CONTINUED from its last timestamp — dashboards refresh on their polling cycle; nothing was wiped.
          </div>
        </div>
      )}
      {mlRefresh.data && (
        <div className="mt-1 rounded border border-violet-800/60 bg-violet-950/30 px-3 py-1.5 font-mono text-[11px] text-violet-200">
          ✓ ML refreshed — model registry, predictions, anomalies, data-quality and recommendations are current.
        </div>
      )}
    </Panel>
  )
}

/** FLOOR SUPERVISOR — NOW: line state, current bottleneck, alerts, at-risk vehicles. */
export default function Supervisor({ onSelectStation, onSelectVehicle }: { onSelectStation: (id: number) => void; onSelectVehicle: (id: number) => void }) {
  const { data: board } = useStations()
  const { data: bn } = useBottlenecks()
  const { data: risks } = useDefectRisks(0.4)
  const { data: recs } = useRecommendations()
  const { data: anomalies } = useAnomalies()
  const { data: obs } = useObservabilityAdvisor()
  const { data: win } = useShadowWindows()
  const { data: defects } = useDefects(10)
  const [traceId, setTraceId] = useState<number | null>(null)
  const [showTrust, setShowTrust] = useState(false)
  const { data: trace } = useDefectTrace(traceId)
  const codeToId = Object.fromEntries((board?.stations ?? []).map((s) => [s.code, s.id]))

  const zones = ['body', 'paint', 'final']
  const stations = board?.stations ?? []
  const alerts = [
    ...(anomalies?.anomalies.slice(0, 6).map((a) => ({
      t: a.t, text: `anomaly ${a.score.toFixed(2)} at ${a.station}${a.vin ? ` · ${a.vin}` : ''}`,
      sev: a.severity,
    })) ?? []),
    ...(recs?.recommendations.slice(0, 6).map((r) => ({
      t: r.confidence, text: r.issue, sev: r.severity,
    })) ?? []),
    ...(obs?.stations
      .filter((s) => s.observability_level === 'CRITICAL_GAP' || s.priority === 'CRITICAL')
      .slice(0, 3).map((s) => ({
        t: s.confidence,
        text: `${s.code} — ${s.identified_gap} (coverage ${(s.coverage * 100).toFixed(0)}%, conf ${(s.confidence * 100).toFixed(0)}%)`,
        sev: 'high',
      })) ?? []),
  ].slice(0, 12)

  return (
    <div className="space-y-4">
      {/* bottleneck banner — the one thing a supervisor must see instantly */}
      {bn?.top && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-red-700/60 bg-red-950/40 px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-lg">⚠</span>
            <div>
              <div className="font-mono text-sm font-bold text-red-200">
                CURRENT BOTTLENECK: {bn.top.code}
                <span className="ml-3 font-normal text-red-300/80">score {bn.top.score} · queue {bn.top.evidence.max_queue} · util {(bn.top.evidence.avg_utilization * 100).toFixed(0)}%</span>
              </div>
              <div className="text-xs text-red-300/70">{bn.method_note}</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ConfidenceTag confidence={bn.top.confidence} />
            <button onClick={() => onSelectStation(bn.top!.station_id)}
                    className="rounded-md border border-cyan-700/60 bg-cyan-950/40 px-3 py-1.5 text-xs text-cyan-200 transition hover:bg-cyan-900/50"
                    title="Open contributing-factor analysis for the bottleneck station">
              🔍 Investigate
            </button>
          </div>
        </div>
      )}

      <InjectionPanel />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Sim time" value={simClock(board?.sim_time)} sub={board?.line.name} />
        <KpiCard label="Stations" value={String(stations.length)} sub={`scenario: ${board?.line.scenario ?? '—'}`} />
        <KpiCard label="Critical" value={String(stations.filter((s) => s.status === 'critical').length)} tone="text-red-300" />
        <KpiCard label="At-risk vehicles" value={String(risks?.count ?? 0)} tone="text-amber-300" sub="predicted pre-final-assembly" />
      </div>

      <Panel title="🛡 Safe change validation — maintenance window (Innovation 3)"
             right={<span className="text-[10px] uppercase tracking-widest text-slate-500">shadow mode · live line untouched</span>}>
        <div className="grid gap-3 md:grid-cols-[260px_1fr]">
          <MaintenanceCountdown win={win} />
          <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5 text-[11px] text-slate-400">
            <div className="mb-1 font-semibold text-slate-200">Before anything touches the line, validate it in the shadow twin.</div>
            Any proposed change (cycle time, tool, buffer, sensors) is simulated on an isolated copy of current
            state, compared against the live line, and only queued for the next maintenance window after human
            review. Nothing is applied automatically.
          </div>
        </div>
        <div className="mt-3"><ShadowSimLab compact /></div>
      </Panel>

      <Panel title="🛑 Detected defects — trace back & containment (Innovation 4)"
             right={<span className="text-[10px] uppercase tracking-widest text-slate-500">suspected origin, not root cause</span>}>
        {defects?.defects.length === 0 && <div className="text-xs text-slate-500">No detected defects in the current window.</div>}
        <div className="grid gap-1.5 md:grid-cols-2">
          {(defects?.defects ?? []).map((d) => (
            <div key={d.id} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-xs">
              <div className="min-w-0">
                <span className="font-mono text-cyan-300">{d.vin}</span>{' '}
                <span className="text-slate-300">defect at {d.station}</span>
                <span className="ml-2 font-mono text-[10px] text-slate-500">{simClock(d.t)}</span>
              </div>
              <button onClick={() => setTraceId(d.id)}
                      className="shrink-0 rounded-md border border-red-700/60 bg-red-950/40 px-2 py-1 text-[11px] text-red-200 transition hover:bg-red-900/50">
                TRACE DEFECT
              </button>
            </div>
          ))}
        </div>
        {traceId && (
          <div className="mt-2">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-slate-500">Defect investigation</span>
              <button onClick={() => setTraceId(null)} className="text-[10px] text-slate-500 hover:text-slate-300">✕ close</button>
            </div>
            {trace && <DefectTracePanel trace={trace} onSelectVehicle={onSelectVehicle} onSelectStation={onSelectStation} />}
            {!trace && <div className="text-xs text-slate-400">tracing…</div>}
          </div>
        )}
      </Panel>

      <Panel title={showTrust ? '🧠 AI Prediction Trust (Innovation 5)' : 'Defect-risk predictions — 🧠 Prediction Trust'}
             right={!showTrust && (
               <button onClick={() => setShowTrust(true)}
                       className="rounded-md border border-cyan-700/60 bg-cyan-950/40 px-2.5 py-1 text-[11px] text-cyan-200 transition hover:bg-cyan-900/50">
                 🧠 Prediction Trust
               </button>
             )}>
        {showTrust ? (
          <>
            <PredictionTrustPanel
              onOpenStation={(code) => codeToId[code] && onSelectStation(codeToId[code])}
              onInvestigateFalseAlarms={(code) => codeToId[code] && onSelectStation(codeToId[code])} />
            <div className="mt-2 text-right">
              <button onClick={() => setShowTrust(false)} className="text-[10px] text-slate-500 hover:text-slate-300">✕ close</button>
            </div>
          </>
        ) : (
          <div className="rounded border border-slate-800 bg-slate-900/50 p-3 text-xs text-slate-400">
            Every defect-risk prediction is validated against the actual inspection outcome —
            true positives, false alarms, station-level reliability and a controlled
            path to improve the model. <span className="text-slate-300">Open the panel to see where the AI is trustworthy — and where it isn't.</span>
          </div>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Panel title="Line board — click a station for detail">
          {zones.map((z) => (
            <div key={z}>
              <ZoneLabel>{z} zone</ZoneLabel>
              <div className="flex flex-wrap gap-2">
                {stations.filter((s) => s.zone === z).map((s) => (
                  <StationTile key={s.id} station={s} onClick={() => onSelectStation(s.id)} />
                ))}
              </div>
            </div>
          ))}
        </Panel>

        <div className="space-y-4">
          <Panel title="Active alerts & advisories">
            <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {alerts.map((a, i) => (
                <li key={i} className={`rounded border-l-2 px-2 py-1.5 text-xs ${a.sev === 'high' ? 'border-red-500 bg-red-950/30' : a.sev === 'medium' ? 'border-amber-500 bg-amber-950/20' : 'border-slate-600 bg-slate-900/40'}`}>
                  {a.text}
                </li>
              ))}
              {alerts.length === 0 && <li className="text-xs text-slate-500">line stable — no active alerts</li>}
            </ul>
          </Panel>

          <Panel title="Vehicles at elevated defect risk">
            <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {risks?.vehicles.map((v) => (
                <li key={v.id}>
                  <button onClick={() => onSelectVehicle(v.id)}
                          className="w-full rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-left text-xs hover:border-cyan-600/60">
                    <div className="flex items-center justify-between font-mono">
                      <span className="text-cyan-300">{v.vin}</span>
                      <span className={v.defect_probability! > 0.6 ? 'text-red-300' : 'text-amber-300'}>
                        {(v.defect_probability! * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between text-[10px] text-slate-500">
                      <ConfidenceTag confidence={v.confidence!} />
                      <span>completeness {(v.data_completeness * 100).toFixed(0)}%</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  )
}
