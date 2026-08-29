import { useState } from 'react'
import { errMsg, useDefectTrace, useJourney, useVehicleCF, useVehicleDefect } from './api'
import { Legend, Panel, StateNotice } from './components'
import { VehicleCFAnalysis } from './CFAnalysis'
import { DefectTracePanel } from './DefectTraceback'

/** Vehicle production journey (digital thread) + ranked contributing factors. */
export function VehiclePanel({ vehicleId, onClose }: { vehicleId: number; onClose: () => void }) {
  const [truth, setTruth] = useState(false)
  const { data, isLoading, isError, error } = useJourney(vehicleId, truth)
  const { data: cf, isLoading: cfLoading, isError: cfError, error: cfErr } = useVehicleCF(vehicleId)
  const { data: vdef } = useVehicleDefect(vehicleId)
  const [showTrace, setShowTrace] = useState(false)
  const defectId = vdef?.defects?.[0]?.id ?? null
  const { data: trace, isLoading: traceLoading, isError: traceError, error: traceErr } = useDefectTrace(showTrace ? defectId : null)

  return (
    <div className="fixed inset-0 z-40 flex justify-center bg-black/60 p-6" onClick={onClose}>
      <div className="h-full w-full max-w-4xl overflow-y-auto rounded-xl border border-slate-700 bg-slate-950 p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="font-mono text-xl font-bold">
              {data?.vehicle.vin ?? '…'}
              <span className="ml-3 text-xs font-normal text-slate-400">
                {data?.vehicle.variant} · {data?.vehicle.status.toUpperCase()}
              </span>
            </h2>
            {data?.outcome.defect_found_at && (
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-red-300">
                <span>defect surfaced at inspection <b className="font-mono">{data.outcome.defect_found_at}</b> — upstream origin may be earlier</span>
                {defectId && (
                  <button onClick={() => setShowTrace((s) => !s)}
                          className={`rounded-md px-2 py-0.5 text-[10px] font-semibold transition ${showTrace ? 'bg-cyan-800/70 text-white' : 'border border-red-700/60 bg-red-950/40 text-red-200 hover:bg-red-900/50'}`}>
                    {showTrace ? '✕ close trace' : 'TRACE DEFECT'}
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-400" title="judge mode: reveal simulator ground truth">
              <input type="checkbox" checked={truth} onChange={(e) => setTruth(e.target.checked)} className="accent-cyan-400" />
              ground-truth mode
            </label>
            <button onClick={onClose} className="rounded border border-slate-700 px-2 py-1 text-sm hover:bg-slate-800">✕</button>
          </div>
        </div>

        {isLoading && <StateNotice kind="loading" message="Rebuilding the vehicle's production journey…" />}
        {isError && <StateNotice kind="error" title="Unable to load vehicle journey" message={errMsg(error)} />}
        {data && (
          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <div>
              <Legend items={[
                { dot: 'bg-red-500', label: 'Inspection failure (defect surfaced here)' },
                { dot: 'bg-amber-400', label: 'Abnormal reading (anomaly / deviation / NOK)' },
                { dot: 'bg-slate-500', label: 'Normal station' },
                { dot: 'bg-fuchsia-400', label: 'Simulator ground truth (judge mode)' },
              ]} className="mb-2" />
              <div className="relative space-y-0.5">
                {data.steps.map((s, i) => {
                  const failed = s.station === data.outcome.defect_found_at
                  const abnormal = (s.anomaly_score ?? 0) > 0.9 || (s.cycle_dev ?? 0) > 6 || s.checklist === 'NOK'
                  const truthFlag = truth && (s.internal_flags_truth?.length ?? 0) > 0
                  return (
                    <div key={i} className={`flex items-start gap-3 rounded border-l-4 px-3 py-1.5 text-xs
                      ${failed ? 'border-red-500 bg-red-950/40' : abnormal ? 'border-amber-500/70 bg-amber-950/20' : 'border-slate-700 bg-slate-900/30'}`}>
                      <span className="w-10 shrink-0 font-mono font-bold">{s.station}</span>
                      <div className="flex-1">
                        <span className="text-slate-400">{s.archetype}</span>
                        <span className="ml-2 font-mono">
                          {s.cycle_time != null ? `${s.cycle_time}s` : '…'}
                          {s.cycle_dev != null && Math.abs(s.cycle_dev) > 4 && (
                            <span className="ml-1 text-amber-300">Δ{s.cycle_dev > 0 ? '+' : ''}{s.cycle_dev}</span>)}
                        </span>
                        {s.checklist && <span className={`ml-2 font-mono ${s.checklist === 'NOK' ? 'text-red-400' : 'text-slate-500'}`}>chk:{s.checklist}</span>}
                        {s.anomaly_score != null && s.anomaly_score > 0.9 && <span className="ml-2 text-amber-300">anom {s.anomaly_score.toFixed(2)}</span>}
                        {failed && <span className="ml-2 rounded bg-red-600/40 px-1.5 py-0.5 font-semibold text-red-200">INSPECTION FAIL</span>}
                        {s.inspection === 'pass' && <span className="ml-2 text-emerald-500">✓ inspected</span>}
                        {truthFlag && <span className="ml-2 rounded bg-fuchsia-600/30 px-1.5 text-fuchsia-200">truth: {s.internal_flags_truth!.join(', ')}</span>}
                        {Object.keys(s.sensors).length > 0 && (
                          <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] text-slate-500">
                            {Object.entries(s.sensors).map(([name, r]) => (
                              <span key={name}>{name} μ{r.mean}σ{r.std}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="space-y-4">
              {showTrace && traceLoading && <StateNotice kind="loading" message="Tracing the defect through production history…" />}
              {showTrace && traceError && <StateNotice kind="error" title="Unable to complete the trace" message={errMsg(traceErr)} />}
              {showTrace && trace && (
                <Panel title="🛑 Defect traceback & propagation (Innovation 4)"
                       right={<span className="text-[10px] uppercase tracking-widest text-slate-500">suspected origin · potential exposure</span>}>
                  <DefectTracePanel trace={trace} />
                </Panel>
              )}
              <Panel title="🔍 Contributing-factor analysis (Innovation 2)"
                     right={cf ? <span className="text-[10px] text-slate-500">{cf.batch ? `batch ${cf.batch} · shift ${cf.shift}` : `shift ${cf.shift}`}</span> : undefined}>
                {cfLoading && <StateNotice kind="loading" message="Correlating genealogy, batch & shift evidence…" />}
                {cfError && <StateNotice kind="error" title="Analysis unavailable" message={errMsg(cfErr)} />}
                {cf && <VehicleCFAnalysis data={cf} />}
              </Panel>

              {truth && data.outcome.true_root_causes && (
                <Panel title="Simulator ground truth (judge mode)">
                  <ul className="space-y-1 font-mono text-xs text-fuchsia-200">
                    {data.outcome.true_root_causes.map((c, i) => (
                      <li key={i}>{c.station} — {(c.contribution * 100 / 1).toFixed(3)} raw</li>
                    ))}
                  </ul>
                </Panel>
              )}
              {data.vehicle.quality_score != null && (
                <div className="text-right font-mono text-[10px] text-slate-500">
                  final latent quality {(data.vehicle.quality_score * 100).toFixed(2)}%
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
