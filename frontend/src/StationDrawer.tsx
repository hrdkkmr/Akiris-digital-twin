import React from 'react'
import { useObservabilityAdvisor, useStationDetail, useStationFactors } from './api'
import { ConfidenceTag, Meter, ObsActionTag, ObsLevelTag, Panel, PriorityTag, simClock } from './components'
import { StationCFAnalysis } from './CFAnalysis'

export function StationDrawer({ stationId, onClose }: { stationId: number; onClose: () => void }) {
  const { data, isLoading } = useStationDetail(stationId)
  const { data: obs } = useObservabilityAdvisor()
  const advisor = obs?.stations.find((s) => s.station_id === stationId)
  const { data: cf, isLoading: cfLoading, isError: cfError } = useStationFactors(stationId)
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <div className="h-full w-full max-w-xl overflow-y-auto border-l border-slate-700 bg-slate-950 p-5"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-mono text-xl font-bold">
            {data ? `${data.code} — ${data.archetype}` : '…'}
            {data && <span className="ml-3 text-xs font-normal text-slate-400">{data.zone} zone · profile {data.sensor_profile}</span>}
          </h2>
          <button onClick={onClose} className="rounded border border-slate-700 px-2 py-1 text-sm hover:bg-slate-800">✕</button>
        </div>
        {isLoading && <div className="text-slate-400">loading…</div>}
        {data && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <Panel title={`Utilization ${(data.current.utilization * 100).toFixed(0)}%`}>
                <Meter value={data.current.utilization} color={data.current.utilization > 0.9 ? 'bg-red-500' : 'bg-cyan-500'} />
              </Panel>
              <Panel title={`Queue ${data.current.queue_len}`}>
                <Meter value={Math.min(data.current.queue_len / 20, 1)} color={data.current.queue_len > 10 ? 'bg-red-500' : 'bg-amber-500'} />
              </Panel>
              <Panel title={`Tool wear ${data.current.wear === null ? 'n/a' : (data.current.wear * 100).toFixed(0) + '%'}`}>
                <Meter value={data.current.wear ?? 0} color={(data.current.wear ?? 0) > 0.6 ? 'bg-red-500' : 'bg-emerald-500'} />
              </Panel>
            </div>

            {data.bottleneck && (
              <Panel title="Bottleneck evidence"
                     right={<ConfidenceTag confidence={data.bottleneck.confidence} />}>
                <div className="grid grid-cols-2 gap-2 font-mono text-xs">
                  <div>score <span className="text-cyan-300">{data.bottleneck.score}</span></div>
                  <div>status <span className="text-cyan-300">{data.bottleneck.status}</span></div>
                  <div>avg util {(data.bottleneck.evidence.avg_utilization * 100).toFixed(1)}%</div>
                  <div>max queue {data.bottleneck.evidence.max_queue}</div>
                  <div>avg |cycle dev| {data.bottleneck.evidence.avg_abs_cycle_dev_s}s</div>
                  <div>downtime {data.bottleneck.evidence.downtime_s}s</div>
                </div>
              </Panel>
            )}

            <Panel title={`Sensors (${data.sensors.length})`}>
              {data.sensors.length === 0 && (
                <div className="text-xs text-slate-400">
                  No physical sensors — this station is {data.sensor_profile === 'manual' ? 'manual-checklist only' : 'cycle/count only'}.
                  The twin reasons with reduced confidence here.
                </div>
              )}
              <table className="w-full text-xs">
                <thead><tr className="text-left text-slate-500">
                  <th className="py-1">name</th><th>avg mean</th><th>avg σ</th><th>max</th><th>samples</th></tr></thead>
                <tbody className="font-mono">
                  {data.sensor_stats.map((s) => (
                    <tr key={s.sensor} className="border-t border-slate-800">
                      <td className="py-1 text-slate-300">{s.sensor}</td>
                      <td>{s.avg_mean}</td><td>{s.avg_std}</td><td>{s.max_seen ?? '—'}</td><td>{s.samples}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            {data.data_quality && (
              <Panel title="Data quality / observability">
                <div className="grid grid-cols-2 gap-2 font-mono text-xs">
                  <div>coverage {(data.data_quality.sensor_coverage * 100).toFixed(0)}%</div>
                  <div>completeness {(data.data_quality.completeness * 100).toFixed(1)}%</div>
                  <div>freshness {data.data_quality.freshness_s}s</div>
                  <div>anomaly rate {(data.data_quality.anomaly_rate * 100).toFixed(1)}%</div>
                </div>
              </Panel>
            )}

            {advisor && (
              <Panel title="Observability advisor (Innovation 1)"
                     right={<PriorityTag priority={advisor.priority} />}>
                <div className="flex items-center gap-2 text-xs">
                  <ObsLevelTag level={advisor.observability_level} />
                  <span className="text-slate-400">{advisor.identified_gap}</span>
                  {advisor.is_bottleneck && <span className="rounded bg-red-600/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-red-200">bottleneck</span>}
                </div>
                <div className="mt-2 text-[11px] text-slate-400">{advisor.rationale}</div>
                {advisor.recommendations.length > 0 && (
                  <ul className="mt-2 space-y-1.5">
                    {advisor.recommendations.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 rounded border border-slate-800 bg-slate-950/60 px-2 py-1.5 text-[11px]">
                        <ObsActionTag action={r.action_type} />
                        <span className="text-slate-200">{r.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {advisor.projected_confidence !== null && advisor.projected_confidence !== undefined && (
                  <div className="mt-2 rounded border border-violet-800/50 bg-violet-950/30 px-2 py-1.5 font-mono text-[11px] text-violet-200">
                    projected confidence (estimated): {(advisor.confidence * 100).toFixed(0)}% → ~{(advisor.projected_confidence * 100).toFixed(0)}%
                  </div>
                )}
              </Panel>
            )}

            {data.recommendations.length > 0 && (
              <Panel title="Advisory recommendations">
                <ul className="space-y-2">
                  {data.recommendations.map((r, i) => (
                    <li key={i} className="rounded border border-slate-800 bg-slate-900/50 p-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-200">{r.issue}</span>
                        <ConfidenceTag confidence={r.confidence} />
                      </div>
                      <div className="mt-1 text-slate-400">→ {r.action}</div>
                      <div className="mt-0.5 text-[10px] uppercase text-slate-500">{r.severity} · advisory only</div>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}

            <Panel title="🔍 Contributing-factor analysis (Innovation 2)"
                   right={<span className="animate-pulse text-[10px] text-slate-500">{cfLoading ? 'analyzing…' : cf?.factors.length ? `${cf.factors.length} factors` : ''}</span>}>
              {cfLoading && <div className="text-xs text-slate-400">correlating equipment, process, batch, shift & environment evidence…</div>}
              {cfError && <div className="text-xs text-red-300">analysis unavailable — {String((cfError as unknown as Error)?.message ?? cfError)}</div>}
              {cf && <StationCFAnalysis data={cf} />}
            </Panel>

            <Panel title="Recent vehicles through this station">
              <table className="w-full text-xs font-mono">
                <thead><tr className="text-left text-slate-500"><th>VIN</th><th>cycle</th><th>dev</th><th>anom</th><th>chk</th></tr></thead>
                <tbody>
                  {data.recent_events.map((e, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="py-1 text-cyan-300">{e.vin}</td>
                      <td>{e.cycle_time ?? '—'}</td>
                      <td className={(e.cycle_dev ?? 0) > 4 ? 'text-amber-300' : ''}>{e.cycle_dev ?? '—'}</td>
                      <td>{e.anomaly_score?.toFixed(2) ?? '—'}</td>
                      <td className={e.checklist === 'NOK' ? 'text-red-400' : ''}>{e.checklist ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
            <div className="text-right text-[10px] text-slate-600">baseline cycle μ={data.baseline.cycle_mu}s σ={data.baseline.cycle_sigma}s · {simClock(data.current.utilization)}</div>
          </div>
        )}
      </div>
    </div>
  )
}
