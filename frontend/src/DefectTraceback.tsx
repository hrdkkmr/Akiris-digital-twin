import React, { useState } from 'react'
import type { DefectTrace, ExposedUnit } from './api'

/** Innovation 4 — Defect traceback & propagation analysis UI.
 * SUSPECTED origins / POTENTIAL exposure — never "confirmed root cause". */

const fmtClock = (t: number | undefined | null) => {
  if (t === undefined || t === null) return '—'
  const h = Math.floor(t / 3600) % 24
  const m = Math.floor((t % 3600) / 60)
  const s = Math.floor(t % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const STRENGTH_STYLE: Record<string, string> = {
  STRONG: 'bg-red-600/25 text-red-200',
  MODERATE: 'bg-amber-600/25 text-amber-200',
  WEAK: 'bg-slate-700/50 text-slate-300',
}

function StrengthBadge({ strength }: { strength: string }) {
  const s = strength.toUpperCase()
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${STRENGTH_STYLE[s] ?? 'bg-slate-800 text-slate-500'}`}>{s}</span>
}

/** journey flow: normal → suspected origin → exposed downstream → detection */
function PropagationMap({ trace }: { trace: DefectTrace }) {
  const origin = trace.suspected_origins[0]?.code
  const detected = trace.detection_station
  return (
    <div className="flex flex-wrap items-center gap-1">
      {trace.journey.map((code, i) => {
        let cls = 'border-slate-800 bg-slate-900/60 text-slate-400'
        let icon: string | null = null
        if (code === origin) { cls = 'border-red-600 bg-red-950/50 text-red-200'; icon = '🔴' }
        else if (code === detected) { cls = 'border-red-700/70 bg-red-950/30 text-red-300'; icon = '🛑' }
        return (
          <React.Fragment key={i}>
            <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${cls}`}>
              {icon && <span className="mr-0.5">{icon}</span>}{code}
            </span>
            {i < trace.journey.length - 1 && <span className="text-slate-600">→</span>}
          </React.Fragment>
        )
      })}
    </div>
  )
}

function ExposureTimeline({ trace }: { trace: DefectTrace }) {
  const w = trace.exposure_window
  if (!w) return null
  const events: { t: number; label: string; kind: string }[] = [
    { t: w.start, label: `${w.station} abnormal conditions begin (suspected window)`, kind: 'warn' },
  ]
  trace.potentially_exposed_units.units.slice(0, 4).forEach((u) =>
    events.push({ t: u.exposure_ts, label: `${u.vin} passes through ${w.station}`, kind: 'unit' }))
  if (trace.potentially_exposed_units.units.length > 4)
    events.push({ t: trace.potentially_exposed_units.units[Math.min(4, trace.potentially_exposed_units.units.length - 1)].exposure_ts, label: `… ${trace.potentially_exposed_units.units.length} units pass through`, kind: 'unit' })
  events.push({ t: w.end, label: 'Last potentially exposed unit', kind: 'unit' })
  events.push({ t: trace.detected_at, label: `Defect detected at ${trace.detection_station}`, kind: 'detect' })
  events.sort((a, b) => a.t - b.t)
  return (
    <div className="space-y-1">
      {events.map((e, i) => (
        <div key={i} className="flex items-start gap-2 text-[11px]">
          <span className="w-16 shrink-0 font-mono text-slate-500">{fmtClock(e.t)}</span>
          <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-slate-700" />
          <span className={e.kind === 'detect' ? 'text-red-300' : e.kind === 'warn' ? 'text-amber-300' : 'text-slate-300'}>
            {e.label}
          </span>
        </div>
      ))}
    </div>
  )
}

export function DefectTracePanel({ trace, onSelectVehicle, onSelectStation }: {
  trace: DefectTrace
  onSelectVehicle?: (id: number) => void
  onSelectStation?: (id: number) => void
}) {
  const [filter, setFilter] = useState<'ALL' | 'HIGH' | 'CONFIRMED'>('ALL')
  const units: ExposedUnit[] = trace.potentially_exposed_units.units
  const shown = units.filter((u) =>
    filter === 'ALL' ? true : filter === 'CONFIRMED' ? u.confirmed_defect : u.exposure_level === filter)
  const risk = trace.propagation_risk
  const riskColor = risk.level === 'high' ? 'text-red-300 border-red-700/60 bg-red-950/40'
    : risk.level === 'medium' ? 'text-amber-300 border-amber-700/60 bg-amber-950/30'
    : 'text-emerald-300 border-emerald-700/50 bg-emerald-950/20'

  return (
    <div className="space-y-3">
      {/* incident header */}
      <div className="rounded border border-red-700/60 bg-red-950/30 px-2.5 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-semibold text-red-200">
            🛑 Defect detected at {trace.detection_station} — vehicle {trace.vehicle}
            {trace.batch && <span className="ml-2 font-mono text-slate-300">batch {trace.batch}</span>}
            <span className="ml-2 font-mono text-slate-400">{fmtClock(trace.detected_at)}</span>
          </div>
          <StrengthBadge strength={trace.defect_severity} />
        </div>
        {trace.multiple_plausible_origins && (
          <div className="mt-1 text-[10px] text-amber-300">Multiple plausible exposure points detected — the system acknowledges uncertainty.</div>
        )}
      </div>

      {/* traceback path */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Traceback · production path (genealogy)</div>
        <PropagationMap trace={trace} />
        <div className="mt-1 text-[10px] text-slate-600">🔴 suspected origin · 🛑 detection · rest normal</div>
      </div>

      {/* suspected origins */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Suspected origin points (ranked by evidence)</div>
        {trace.suspected_origins.length === 0 && <div className="text-xs text-slate-400">No upstream station showed sufficient evidence — traceability limited.</div>}
        <div className="space-y-1.5">
          {trace.suspected_origins.map((o) => (
            <div key={o.code} className="rounded border border-slate-800 bg-slate-900/50 p-2">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2">
                  <button onClick={() => onSelectStation?.(o.station_id)}
                          className="font-mono font-bold text-cyan-300 hover:underline" title="open station">{o.code}</button>
                  <span className="text-slate-500">{o.zone}</span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="font-mono text-cyan-300">{o.score.toFixed(2)}</span>
                  <StrengthBadge strength={o.strength} />
                </span>
              </div>
              {o.evidence.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-[10px] text-slate-400">
                  {o.evidence.map((e, i) => <li key={i} className="flex gap-1"><span className="text-slate-600">•</span>{e}</li>)}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* exposure window */}
      {trace.exposure_window && (
        <div className="rounded border border-amber-700/50 bg-amber-950/20 p-2">
          <div className="mb-1 text-[10px] uppercase tracking-widest text-amber-200">Suspected exposure window · {trace.exposure_window.station}</div>
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="font-mono text-slate-200">start {fmtClock(trace.exposure_window.start)}</span>
            <span className="font-mono text-slate-200">end {fmtClock(trace.exposure_window.end)}</span>
            <StrengthBadge strength={trace.exposure_window.confidence} />
          </div>
          {trace.exposure_window.reason.map((r, i) => (
            <div key={i} className="mt-1 text-[10px] text-slate-400">{r}</div>
          ))}
          <div className="mt-2 border-t border-amber-800/40 pt-1.5"><ExposureTimeline trace={trace} /></div>
        </div>
      )}

      {/* affected unit explorer */}
      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-[10px] uppercase tracking-widest text-slate-500">
          <span>Affected unit explorer — {trace.potentially_exposed_units.total} potentially exposed</span>
          <span className="flex gap-1 normal-case">
            {(['ALL', 'HIGH', 'CONFIRMED'] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)}
                      className={`rounded px-1.5 py-0.5 text-[10px] ${filter === f ? 'bg-cyan-700/60 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}>
                {f === 'ALL' ? 'all' : f === 'HIGH' ? 'high exposure' : 'confirmed defects'}
              </button>
            ))}
          </span>
        </div>
        <div className="mb-1 flex gap-3 text-[10px] text-slate-400">
          <span>potentially affected: <b className="text-amber-200">{trace.potentially_exposed_units.potentially_affected}</b></span>
          <span>confirmed defects among them: <b className="text-red-300">{trace.potentially_exposed_units.confirmed_defects}</b></span>
        </div>
        <div className="max-h-64 overflow-y-auto rounded border border-slate-800">
          <table className="w-full text-[11px] font-mono">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-500">
              <tr>
                <th className="px-2 py-1">vehicle</th><th className="px-1">exposure</th><th className="px-1">batch</th>
                <th className="px-1">shift</th><th className="px-1">status</th>
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, 50).map((u) => (
                <tr key={u.vehicle_id} className="border-t border-slate-800/60">
                  <td className="px-2 py-0.5">
                    {onSelectVehicle
                      ? <button onClick={() => onSelectVehicle(u.vehicle_id)} className="text-cyan-300 hover:underline">{u.vin}</button>
                      : u.vin}
                  </td>
                  <td className="px-1">
                    <span className={`rounded px-1 text-[10px] font-semibold ${u.exposure_level === 'HIGH' ? 'bg-red-600/25 text-red-200' : u.exposure_level === 'MEDIUM' ? 'bg-amber-600/25 text-amber-200' : 'bg-slate-700/50 text-slate-400'}`}>{u.exposure_level}</span>
                  </td>
                  <td className="px-1 text-slate-400">{u.batch ?? '—'}</td>
                  <td className="px-1 text-slate-400">{u.shift}</td>
                  <td className="px-1">
                    {u.confirmed_defect ? <span className="text-red-300">DEFECT</span>
                      : u.status === 'scrapped' ? <span className="text-amber-300">scrapped</span>
                      : <span className="text-slate-500">{u.status}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* common exposure */}
      {trace.common_exposures.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Common exposure · shared conditions</div>
          <div className="grid gap-1.5 md:grid-cols-2">
            {trace.common_exposures.map((c, i) => (
              <div key={i} className="rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-[11px]">
                <span className="text-slate-500">{c.factor}: </span>
                <span className="text-slate-200">{c.label}</span>
                <span className="ml-2 font-mono text-[10px] text-cyan-300">{(c.share * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* propagation risk */}
      <div className={`rounded border p-2.5 ${riskColor}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-widest">Propagation risk · {risk.level}</span>
          <span className="font-mono text-[10px] opacity-80">score {risk.score.toFixed(2)} · {risk.note}</span>
        </div>
        <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[10px] md:grid-cols-3">
          <span>exposed: {String(risk.drivers.exposed_units)}</span>
          <span>confirmed: {String(risk.drivers.confirmed_defects)}</span>
          <span>window: {String(risk.drivers.window_h)}h</span>
          <span>common share: {(Number(risk.drivers.common_share) * 100).toFixed(0)}%</span>
          <span>multiple origins: {String(risk.drivers.multiple_origins)}</span>
          <span>obs conf: {(Number(risk.drivers.observability_confidence) * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* containment */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Containment recommendation · advisory</div>
        <ul className="space-y-1">
          {trace.containment_recommendations.map((r, i) => (
            <li key={i} className="flex gap-1.5 text-[11px] text-slate-300"><span className="text-amber-400">{i + 1}.</span>{r}</li>
          ))}
        </ul>
      </div>

      {/* inspection priority + confidence */}
      <div className="grid gap-2 md:grid-cols-2">
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2">
          <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Inspection priority</div>
          <div className="flex gap-2 text-[11px]">
            <span className="rounded bg-red-600/25 px-1.5 py-0.5 text-red-200">HIGH {trace.inspection_priority.HIGH ?? 0}</span>
            <span className="rounded bg-amber-600/25 px-1.5 py-0.5 text-amber-200">MEDIUM {trace.inspection_priority.MEDIUM ?? 0}</span>
            <span className="rounded bg-slate-700/50 px-1.5 py-0.5 text-slate-300">LOW {trace.inspection_priority.LOW ?? 0}</span>
          </div>
        </div>
        {trace.data_confidence === 'LIMITED TRACEABILITY' && (
          <div className="rounded border border-amber-700/60 bg-amber-950/25 p-2 text-[11px] text-amber-200">
            ⚠ LIMITED TRACEABILITY — {trace.traceability_note}
          </div>
        )}
      </div>

      <div className="rounded border border-slate-800 bg-slate-900/40 p-2 text-[10px] italic text-slate-500">{trace.disclaimer}</div>
    </div>
  )
}
