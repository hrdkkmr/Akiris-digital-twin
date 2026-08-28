import React from 'react'
import { Bar, BarChart, Cell, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts'
import { useBottlenecks, useDQ, useModelPerf, useSummary, useTrends } from '../api'
import { KpiCard, Panel } from '../components'

/** PLANT MANAGER — shift/week trends: throughput, FPY, bottleneck ranking,
 * defect mix, observability and model trust. */
export default function Manager() {
  const { data: sum } = useSummary()
  const [bnWindow, setBnWindow] = React.useState<number | undefined>(undefined)
  const { data: bn } = useBottlenecks(bnWindow)
  const { data: dq } = useDQ()
  const { data: perf } = useModelPerf()
  const { data: trends } = useTrends(50)

  const bnChart = (bn?.ranking ?? []).slice(0, 10).map((r) => ({ code: r.code, score: r.score, status: r.status }))
  const zoneData = Object.entries(sum?.defects_by_zone_found ?? {}).map(([zone, n]) => ({ zone, defects: n }))
  const latest = perf?.registered_models[0]
  const m = latest?.metrics ?? {}

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Throughput" value={`${sum?.throughput_per_hour ?? '—'} veh/h`} sub={`${sum?.span_hours ?? '—'}h window`} />
        <KpiCard label="First-pass yield" value={sum ? `${(sum.fpy * 100).toFixed(1)}%` : '—'} sub={`${sum?.scrapped ?? 0} scrapped / ${sum?.vehicles_total ?? 0} total`} />
        <KpiCard label="Avg lead time" value={sum?.avg_lead_time_s ? `${Math.round(sum.avg_lead_time_s)}s` : '—'} />
        <KpiCard label="Maint. downtime" value={`${sum?.maintenance_downtime_min ?? 0} min`} tone="text-amber-300" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Bottleneck ranking (evidence composite)">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wide text-slate-500">window:</span>
            {([['full', undefined], ['last 1h', 3600], ['last 2h', 7200]] as [string, number | undefined][]).map(([label, w]) => (
              <button key={label} onClick={() => setBnWindow(w)}
                      className={`rounded px-2 py-0.5 font-mono text-[10px] ${bnWindow === w ? 'bg-cyan-600/70 font-semibold text-slate-950' : 'border border-slate-700 text-slate-400 hover:bg-slate-800'}`}>
                {label}
              </button>
            ))}
            {bnWindow !== undefined && (
              <span className="text-[10px] text-amber-300/80">
                shadowing check — windowed top can differ from the full-history bottleneck</span>
            )}
          </div>
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={bnChart} layout="vertical" margin={{ left: 8, right: 16 }}>
                <XAxis type="number" domain={[0, 1]} hide />
                <YAxis type="category" dataKey="code" width={40} tick={{ fill: '#94a3b8', fontSize: 11, fontFamily: 'monospace' }} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }} />
                <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                  {bnChart.map((d) => (
                    <Cell key={d.code} fill={d.status === 'critical' ? '#ef4444' : d.status === 'high' ? '#f59e0b' : '#0891b2'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 text-[10px] text-slate-500">{bn?.method_note}</div>
        </Panel>

        <Panel title="Defects by zone found (delayed-surfacing view)">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={zoneData} margin={{ left: 8, right: 16 }}>
                <XAxis dataKey="zone" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }} />
                <Bar dataKey="defects" fill="#a78bfa" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 text-[10px] text-slate-500">Where defects are DISCOVERED, not where they originate — trace origins per vehicle in the journey view.</div>
        </Panel>
      </div>

      <Panel title="Production trend — FPY % and throughput per 50-vehicle bucket (from twin history)">
        <div className="h-56">
          <ResponsiveContainer>
            <LineChart data={(trends?.buckets ?? []).map((b) => ({ ...b, fpy_pct: +(b.fpy * 100).toFixed(1) }))} margin={{ left: 4, right: 12, top: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="bucket" tick={{ fill: '#94a3b8', fontSize: 11, fontFamily: 'monospace' }} tickLine={false} />
              <YAxis yAxisId="tput" tick={{ fill: '#94a3b8', fontSize: 11 }} domain={['auto', 'auto']} />
              <YAxis yAxisId="fpy" orientation="right" domain={[80, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                       labelFormatter={(l) => `bucket ${l} (${trends?.bucket_size} veh)`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line yAxisId="tput" type="monotone" dataKey="throughput_per_hour" name="veh/h" stroke="#22d3ee" strokeWidth={2} dot={false} />
              <Line yAxisId="fpy" type="monotone" dataKey="fpy_pct" name="FPY %" stroke="#a78bfa" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 text-[10px] text-slate-500">Each bucket = {trends?.bucket_size ?? 50} consecutive completions; dips align with maintenance windows, batch surges and shift ramps.</div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Model performance & trust loop">
          {latest ? (
            <div className="space-y-2 text-xs">
              <div className="flex justify-between font-mono text-slate-400">
                <span>{latest.name} · {latest.algo} · v{latest.version}</span>
                <span className="text-slate-500">threshold {m.decision_threshold}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 font-mono">
                <div>precision <span className="text-cyan-300">{m.precision}</span></div>
                <div>recall <span className="text-cyan-300">{m.recall}</span></div>
                <div>F1 <span className="text-cyan-300">{m.f1}</span></div>
                <div>FPR <span className="text-amber-300">{m.fpr}</span></div>
                <div>FNR <span className="text-red-300">{m.fnr}</span></div>
                <div>ROC-AUC <span className="text-cyan-300">{m.roc_auc}</span></div>
              </div>
              <div className="text-[10px] text-slate-500">{m.split} · {m.threshold_note}</div>
              {perf?.live_prediction_metrics?.resolved != null && (
                <div className="rounded border border-slate-800 bg-slate-900/50 p-2">
                  <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">live (outcome-resolved predictions)</div>
                  <div className="grid grid-cols-4 gap-2 font-mono text-[11px]">
                    <div>n {perf.live_prediction_metrics.resolved}</div>
                    <div>prec {perf.live_prediction_metrics.precision}</div>
                    <div>rec {perf.live_prediction_metrics.recall}</div>
                    <div>fpr {perf.live_prediction_metrics.fpr}</div>
                  </div>
                </div>
              )}
            </div>
          ) : <div className="text-xs text-slate-500">no model trained yet — run scripts/train_models.py</div>}
        </Panel>

        <Panel title="Station observability (coverage → analytics confidence)">
          <div className="max-h-64 overflow-y-auto pr-1">
            <table className="w-full text-xs font-mono">
              <thead className="sticky top-0 bg-slate-900 text-left text-slate-500">
                <tr><th className="py-1">stn</th><th>profile</th><th>cover</th><th>compl.</th><th>fresh</th><th>conf</th></tr>
              </thead>
              <tbody>
                {(dq?.stations ?? []).map((s) => (
                  <tr key={s.code} className="border-t border-slate-800">
                    <td className="py-1 text-cyan-300">{s.code}</td>
                    <td>{s.sensor_profile}</td>
                    <td className={s.sensor_coverage < 0.5 ? 'text-amber-300' : ''}>{(s.sensor_coverage * 100).toFixed(0)}%</td>
                    <td>{(s.completeness * 100).toFixed(0)}%</td>
                    <td className={s.freshness === 'stale' ? 'text-red-300' : ''}>{s.freshness}</td>
                    <td className={s.analytics_confidence < 0.5 ? 'text-red-300' : s.analytics_confidence < 0.7 ? 'text-amber-300' : 'text-emerald-300'}>
                      {(s.analytics_confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-[10px] text-slate-500">
            conf = 0.45·coverage + 0.35·completeness + 0.20·freshness − 0.30·anomaly density —
            persisted per station in data_quality_metrics. The twin knows where it is weak.
          </div>
        </Panel>
      </div>
    </div>
  )
}
