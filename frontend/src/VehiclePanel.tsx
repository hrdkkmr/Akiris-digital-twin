import React, { useState } from 'react'
import { useFactors, useJourney } from './api'
import { ConfidenceTag, Panel } from './components'

/** Vehicle production journey (digital thread) + ranked contributing factors. */
export function VehiclePanel({ vehicleId, onClose }: { vehicleId: number; onClose: () => void }) {
  const [truth, setTruth] = useState(false)
  const { data, isLoading } = useJourney(vehicleId, truth)
  const { data: factors } = useFactors(vehicleId)

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
              <div className="mt-1 text-xs text-red-300">
                defect surfaced at inspection <b className="font-mono">{data.outcome.defect_found_at}</b> — upstream origin may be earlier
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

        {isLoading && <div className="text-slate-400">loading…</div>}
        {data && (
          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <div>
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
              <Panel title={factors?.language ?? 'Likely contributing factors'}>
                {factors?.candidates.length === 0 && <div className="text-xs text-slate-400">no strong evidence — defect may be stochastic</div>}
                <ul className="space-y-2">
                  {factors?.candidates.map((c, i) => (
                    <li key={i} className="rounded border border-slate-800 bg-slate-900/50 p-2 text-xs">
                      <div className="flex items-center justify-between font-mono">
                        <span className="text-cyan-300">{c.station ?? (c.type === 'batch_evidence' ? 'BATCH' : '?')}</span>
                        <span>{(c.contribution * 100).toFixed(0)}%</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded bg-slate-800">
                        <div className="h-1.5 rounded bg-cyan-500" style={{ width: `${c.contribution * 100}%` }} />
                      </div>
                      <ul className="mt-1 list-inside list-disc text-[10px] text-slate-400">
                        {c.evidence.map((e, j) => <li key={j}>{e}</li>)}
                      </ul>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 text-[10px] italic text-slate-500">{factors?.caveat}</div>
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
