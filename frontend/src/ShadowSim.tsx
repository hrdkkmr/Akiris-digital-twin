import { useMemo, useState } from 'react'
import {
  apiPost, createScenario, errMsg, queueScenario, runScenario,
  useShadowChanges, useShadowWindows, useSimHistory,
} from './api'
import type { QueueItem, ShadowChange, SimScenario, ShadowWindows } from './api'
import { Legend, StateNotice } from './components'

/** Innovation 3 — Safe change validation + shadow simulation UI.
 * Framed as a production decision tool: "Plan a Production Change".
 * The live line is NEVER modified — everything is a labeled projection. */

const REPORT_DISCLAIMER = 'Results are digital twin simulation projections and should be validated against real production conditions before implementation. Prepared by Akiris - DigitalTwin.ai.'

const fmtCountdown = (s: number) => {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d} days ${h} hours`
  if (h > 0) return `${h} hours ${m} minutes`
  return `${m} minutes`
}
const fmtClock = (t: number) => `${String(Math.floor(t / 3600) % 24).padStart(2, '0')}:${String(Math.floor((t % 3600) / 60)).padStart(2, '0')}`

export function RiskBadge({ level }: { level: string }) {
  const l = level.toLowerCase()
  const cls = l === 'high' ? 'bg-red-600/30 text-red-200 border-red-700/60'
    : l === 'medium' ? 'bg-amber-600/25 text-amber-200 border-amber-700/60'
    : 'bg-emerald-600/20 text-emerald-200 border-emerald-700/50'
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${l === 'high' ? 'bg-red-400' : l === 'medium' ? 'bg-amber-400' : 'bg-emerald-400'}`} />
      {level}
    </span>
  )
}

export function MaintenanceCountdown({ win }: { win: ShadowWindows | undefined }) {
  if (!win) return null
  const pct = Math.min(100, (win.queued_items / Math.max(win.capacity, 1)) * 100)
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
      <div className="text-xs font-semibold text-slate-200">🛠 Next scheduled maintenance window</div>
      <div className="mt-0.5 text-[10px] text-slate-500">Production changes can be safely applied during this window.</div>
      <div className="mt-1 font-mono text-xl text-slate-100">in {fmtCountdown(win.countdown_s)}</div>
      <div className="mt-0.5 font-mono text-[10px] text-cyan-300">{fmtClock(win.next_window_start)} – {fmtClock(win.next_window_end)} · {win.window_label} · {win.duration_h.toFixed(1)}h planned</div>
      <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-400">
        <div className="h-1.5 flex-1 rounded bg-slate-800">
          <div className="h-1.5 rounded bg-cyan-600" style={{ width: `${pct}%` }} />
        </div>
        <span>{win.queued_items}/{win.capacity} changes queued</span>
      </div>
    </div>
  )
}

const KIND_ICON: Record<string, string> = {
  cycle_time: '⏱', tool_replace: '🔧', buffer: '📦', observability: '📡', environment: '🌡',
}

export function ChangeLibrary({ changes, selected, onToggle, onSelectAll }: {
  changes: ShadowChange[]; selected: Set<string>
  onToggle: (id: string) => void; onSelectAll: (all: boolean) => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest text-slate-500">
          Proposed changes library · {changes.length} available · select what to evaluate
        </div>
        <button onClick={() => onSelectAll(selected.size !== changes.length)}
                className="text-[10px] text-cyan-300 hover:text-cyan-200">
          {selected.size === changes.length ? 'clear all' : `select all (${changes.length})`}
        </button>
      </div>
      <div className="grid gap-1.5 md:grid-cols-2">
        {changes.map((c) => {
          const on = selected.has(c.id)
          const color = c.kind === 'cycle_time' ? 'text-cyan-300' : c.kind === 'tool_replace' ? 'text-red-300'
            : c.kind === 'buffer' ? 'text-amber-300' : c.kind === 'observability' ? 'text-emerald-300' : 'text-sky-300'
          return (
            <label key={c.id} className={`flex cursor-pointer gap-2 rounded border p-2 transition ${on ? 'border-cyan-700/70 bg-cyan-950/30' : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'}`}>
              <input type="checkbox" checked={on} onChange={() => onToggle(c.id)} className="mt-0.5 accent-cyan-500" aria-label={`select ${c.title} at ${c.station}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-xs font-medium ${color}`}><span className="mr-1">{KIND_ICON[c.kind] ?? '•'}</span>{c.title} · {c.station}</span>
                  <span className="font-mono text-[10px] text-slate-500">{c.current} → <span className="text-slate-300">{c.proposed}</span></span>
                </div>
                <div className="mt-0.5 text-[10px] text-slate-400">{c.impact} · expected: {c.expected}</div>
              </div>
            </label>
          )
        })}
      </div>
      {selected.size > 0 && (
        <div className="rounded border border-cyan-800/50 bg-cyan-950/20 px-2 py-1.5 text-[11px] text-cyan-100">
          <span className="mr-1 font-semibold">Selected ({selected.size}):</span>
          {changes.filter((c) => selected.has(c.id)).map((c) => (
            <span key={c.id} className="mr-2">☑ {c.title} — {c.station}</span>
          ))}
        </div>
      )}
    </div>
  )
}

const METRIC_LABELS: Record<string, string> = {
  throughput_per_hour: 'Throughput', avg_cycle_time_s: 'Cycle time',
  total_queue: 'Units in queue (WIP)', defect_risk_pct: 'Predicted defect exposure',
  avg_utilization_pct: 'Average utilization', top_bottleneck: 'Top bottleneck',
  mean_analytics_confidence_pct: 'Analytics confidence',
}
const METRIC_UNITS: Record<string, string> = {
  throughput_per_hour: ' veh/h', avg_cycle_time_s: ' s', total_queue: '', defect_risk_pct: ' %',
  avg_utilization_pct: ' %', top_bottleneck: '', mean_analytics_confidence_pct: ' %',
}

/** CURRENT vs SHADOW comparison with ▲/▼ deltas + explicit color key. */
export function ImpactTable({ scenario }: { scenario: SimScenario }) {
  const rows = useMemo(() => Object.keys(METRIC_LABELS).filter((k) => k in scenario.current_metrics && k in scenario.shadow_metrics), [scenario])
  const num = (v: number | string) => (typeof v === 'number' ? v : parseFloat(String(v).replace(/[^0-9.-]/g, '')))
  return (
    <div className="overflow-x-auto">
      <Legend items={[{ dot: 'bg-slate-300', label: 'Current production line' }, { dot: 'bg-cyan-400', label: 'Shadow / simulated line' }]} className="mb-1.5" />
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-500">
            <th className="py-1">Metric</th>
            <th className="py-1"><span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-slate-300" /> Current</span></th>
            <th className="py-1"><span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-cyan-400" /> Shadow</span></th>
            <th className="py-1">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((k) => {
            const a = scenario.current_metrics[k], b = scenario.shadow_metrics[k]
            const na = num(a), nb = num(b)
            const delta = !isNaN(na) && !isNaN(nb) && isFinite(na) && isFinite(nb) ? nb - na : NaN
            // "good" direction depends on the metric (lower defect/queue/cycle is good)
            const goodDown = k.includes('defect_risk') || k.includes('cycle_time') || k.includes('queue')
            const good = isNaN(delta) ? null : goodDown ? delta <= 0 : delta >= 0
            const color = delta === 0 ? 'text-slate-500' : good ? 'text-emerald-300' : 'text-red-300'
            const arrow = isNaN(delta) ? '—' : delta === 0 ? '→' : delta > 0 ? '▲' : '▼'
            return (
              <tr key={k} className="border-t border-slate-800">
                <td className="py-1 text-slate-300">{METRIC_LABELS[k]}</td>
                <td className="py-1 font-mono text-slate-300">{typeof na === 'number' && !isNaN(na) ? `${Math.round(na * 100) / 100}${METRIC_UNITS[k]}` : String(a)}</td>
                <td className="py-1 font-mono text-cyan-200">{typeof nb === 'number' && !isNaN(nb) ? `${Math.round(nb * 100) / 100}${METRIC_UNITS[k]}` : String(b)}</td>
                <td className={`py-1 font-mono font-semibold ${color}`}>
                  {isNaN(delta) ? '—' : `${arrow} ${delta > 0 ? '+' : ''}${Math.round(delta * 100) / 100}${METRIC_UNITS[k]}`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="mt-1 text-[9px] italic text-slate-600">All shadow values are projected / simulated — estimates, not measured results.</div>
    </div>
  )
}

export function MaintenanceQueuePanel({ items, capacity, windowStart }: {
  items: QueueItem[]; capacity?: number; windowStart?: number
}) {
  const totalMin = items.reduce((a, b) => a + (b.estimated_duration_min ?? 0), 0)
  return (
    <div className="space-y-1.5">
      {items.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
          <span>{items.length} change(s) queued · combined est. downtime {totalMin} min</span>
          {windowStart !== undefined && <span className="font-mono text-cyan-300">window {fmtClock(windowStart)}</span>}
        </div>
      )}
      {items.length === 0 && <StateNotice kind="empty" message="Nothing queued for the next maintenance window yet." />}
      {items.slice(0, capacity ?? 8).map((it) => (
        <div key={it.id} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900/40 px-2 py-1.5 text-xs">
          <div className="min-w-0">
            <span className="font-mono text-cyan-300">{it.station_code}</span>{' '}
            <span className="text-slate-300">{it.change}</span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <RiskBadge level={it.risk_level} />
            <span className="font-mono text-[10px] text-slate-500">{it.estimated_duration_min}m</span>
            <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] capitalize ${it.status === 'approved' ? 'bg-emerald-600/20 text-emerald-200' : it.status === 'complete' ? 'bg-emerald-600/20 text-emerald-200' : 'bg-slate-800 text-slate-400'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${it.status === 'approved' || it.status === 'complete' ? 'bg-emerald-400' : 'bg-slate-500'}`} />
              {it.status}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

export function SimHistory({ onOpen }: { onOpen: (id: number) => void }) {
  const { data } = useSimHistory()
  if (!data) return <div className="text-xs text-slate-400">Loading simulations…</div>
  if (data.count === 0) return <StateNotice kind="empty" message="No shadow simulations run yet." />
  return (
    <div className="space-y-1.5">
      {data.scenarios.slice(0, 8).map((s) => (
        <button key={s.id} onClick={() => onOpen(s.id)}
                className="flex w-full items-center justify-between rounded border border-slate-800 bg-slate-900/40 px-2 py-1.5 text-left text-xs transition hover:border-slate-700">
          <span className="font-mono text-cyan-300">{s.name}</span>
          <span className="flex items-center gap-2">
            <span className="text-slate-400">{s.changes.length} changes</span>
            <RiskBadge level={s.risk_level} />
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] capitalize text-slate-300">{s.status}</span>
          </span>
        </button>
      ))}
    </div>
  )
}

/** Full workflow: select changes → run shadow → compare → risk → queue/end/save. */
export function ShadowSimLab({ compact = false }: { compact?: boolean }) {
  const { data: lib, isLoading, isError, error } = useShadowChanges()
  const { data: win } = useShadowWindows()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [scenario, setScenario] = useState<SimScenario | null>(null)
  const [busy, setBusy] = useState(false)
  const [errorState, setErrorState] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [ackHigh, setAckHigh] = useState(false)
  const [showChanges, setShowChanges] = useState(true)

  const changes = lib?.changes ?? []
  const toggle = (id: string) => setSelected((prev) => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const selectAll = (all: boolean) => setSelected(all ? new Set(changes.map((c) => c.id)) : new Set())

  const start = async () => {
    setErrorState(null); setSuccessMsg(null); setBusy(true)
    try {
      const pick = changes.filter((c) => selected.has(c.id)).map((c) => ({ ...c, selected: true }))
      if (pick.length === 0) { setErrorState('Select at least one change to evaluate before running the simulation.'); return }
      const sc = await createScenario(pick)
      if ((sc as unknown as { error?: string }).error) { setErrorState((sc as unknown as { error: string }).error); return }
      const ran = await runScenario(sc.id)
      if ((ran as unknown as { error?: string }).error) { setErrorState((ran as unknown as { error: string }).error); return }
      setScenario(ran); setShowChanges(false); setSuccessMsg('Shadow simulation completed. No changes have been made to the real production line.')
    } catch (e) { setErrorState(errMsg(e)) } finally { setBusy(false) }
  }

  const act = async (fn: () => Promise<unknown>, okText?: string) => {
    setErrorState(null); setSuccessMsg(null); setBusy(true)
    try {
      const r = await fn() as { error?: string; status?: string; scenario?: string; message?: string }
      if (r?.error) { setErrorState(r.error); return }
      if (r?.status === 'queued') setSuccessMsg(`Queued ${r.scenario ?? ''} for the next maintenance window — human approval required before implementation.`)
      else if (okText) setSuccessMsg(okText)
      setScenario((s) => s ? { ...s, status: r?.status ?? s.status, maintenance_status: r?.status === 'queued' ? 'queued' : s.maintenance_status } : s)
    } catch (e) { setErrorState(errMsg(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="rounded border border-slate-800 bg-slate-900/50 p-3">
        <div className="text-sm font-bold text-slate-100">Plan a Production Change</div>
        <div className="mt-0.5 text-[11px] text-slate-400">
          Select changes you'd like to evaluate before touching the real production line. Everything runs on an isolated shadow copy — the live line is never modified.
        </div>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <MaintenanceCountdown win={win} />
          <div className="rounded border border-cyan-800/40 bg-cyan-950/10 p-2.5 text-[10px] text-slate-400">
            <div className="mb-1 font-semibold text-cyan-300">⚙ Shadow twin isolation</div>
            Changes are simulated on a copy of current state. Live production, station
            configuration and production records are <span className="text-slate-200">never mutated</span>.
            Results are projections — validate before implementation.
          </div>
        </div>
      </div>

      {showChanges && (
        <>
          {isLoading && <StateNotice kind="loading" message="Loading proposed changes…" />}
          {isError && <StateNotice kind="error" title="Unable to load proposed changes" message={errMsg(error)} />}
          {!isLoading && !isError && (
            <>
              <ChangeLibrary changes={changes} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
              <div className="flex flex-wrap items-center gap-3">
                <button onClick={start} disabled={selected.size === 0 || busy}
                        className="rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-40">
                  {busy ? 'Running shadow simulation…' : `▶ Run Shadow Simulation (${selected.size} change${selected.size === 1 ? '' : 's'})`}
                </button>
                {!compact && <span className="text-[10px] text-slate-500">projection only — nothing is applied to production</span>}
              </div>
            </>
          )}
        </>
      )}

      {errorState && <StateNotice kind="error" title="Something went wrong" message={errorState} />}
      {successMsg && <StateNotice kind="success" message={successMsg} />}

      {scenario && (
        <div className="space-y-2 rounded border border-cyan-800/60 bg-slate-900/40 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-cyan-200">{scenario.name}</span>
              <RiskBadge level={scenario.risk_level} />
              <span className="text-[10px] uppercase tracking-widest text-slate-500">simulation risk assessment</span>
            </div>
            <span className="text-[10px] text-slate-500">status: {scenario.status}</span>
          </div>

          <div className="rounded border border-amber-700/50 bg-amber-950/20 px-2 py-1.5 text-[10px] text-amber-100">
            ⚠ <b>No changes have been made to the real production line.</b> This is a simulation/projection of the selected changes.
          </div>

          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded border border-slate-800 bg-slate-900/50 p-2">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400">
                <span className="h-2 w-2 rounded-full bg-slate-300" /> Current production line
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
                {Object.keys(METRIC_LABELS).filter((k) => k in scenario.current_metrics).map((k) => (
                  <div key={k} className="flex justify-between border-b border-slate-800/60 py-0.5">
                    <span className="text-slate-500">{METRIC_LABELS[k]}</span><span className="text-slate-200">{String(scenario.current_metrics[k])}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded border border-cyan-800/60 bg-cyan-950/20 p-2">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-cyan-300">
                <span className="h-2 w-2 rounded-full bg-cyan-400" /> 🧪 Shadow / simulated line
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
                {Object.keys(METRIC_LABELS).filter((k) => k in scenario.shadow_metrics).map((k) => (
                  <div key={k} className="flex justify-between border-b border-cyan-900/50 py-0.5">
                    <span className="text-cyan-400/70">{METRIC_LABELS[k]}</span><span className="text-cyan-100">{String(scenario.shadow_metrics[k])}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <ImpactTable scenario={scenario} />

          {/* recommended decision */}
          <div className="rounded border border-emerald-800/50 bg-emerald-950/20 p-2">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-emerald-300">Recommended decision</div>
            <div className="text-[11px] text-emerald-100">
              {scenario.recommendation ?? 'Review the projected impact below, then queue for the next maintenance window or end the simulation.'}
            </div>
            <div className="mt-1 text-[10px] text-slate-400">
              Expected improvements: {scenario.changes.map((c) => c.expected).join(' · ')}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Risk detail</div>
            {(scenario.risk_detail?.details ?? []).map((d, i) => (
              <div key={i} className="flex gap-1.5 text-[11px] text-slate-300"><span className="text-amber-400">▸</span>{d}</div>
            ))}
            {(scenario.warnings ?? []).map((w, i) => (
              <div key={`w${i}`} className="flex gap-1.5 text-[11px] text-amber-200/90"><span className="text-amber-500">⚠</span>{w}</div>
            ))}
          </div>

          {scenario.risk_level === 'high' && !scenario.maintenance_status && (
            <label className="flex items-center gap-2 rounded border border-red-800/70 bg-red-950/30 px-2 py-1.5 text-[11px] text-red-200">
              <input type="checkbox" checked={ackHigh} onChange={(e) => setAckHigh(e.target.checked)} className="accent-red-500" />
              I acknowledge the HIGH simulated risk and accept controlled validation in a maintenance window.
            </label>
          )}

          <div className="flex flex-wrap gap-2">
            <button onClick={() => {
              const lines = [
                `Akiris - DigitalTwin.ai — Shadow Simulation Report`,
                `Scenario: ${scenario.name}  |  status: ${scenario.status}`,
                `Risk: ${scenario.risk_level.toUpperCase()} (digital twin simulation risk assessment)`,
                ``,
                `SELECTED CHANGES`,
                ...scenario.changes.map((c) => `- [${c.kind}] ${c.station}: ${c.title} (${c.current} -> ${c.proposed})`),
                ``,
                `IMPACT (CURRENT -> SHADOW)`,
                ...Object.keys(METRIC_LABELS).filter((k) => k in scenario.current_metrics)
                  .map((k) => `- ${METRIC_LABELS[k]}: ${scenario.current_metrics[k]} -> ${scenario.shadow_metrics[k]}`),
                ``,
                `RISK DETAILS`,
                ...(scenario.risk_detail?.details ?? []).map((d) => `- ${d}`),
                ...(scenario.warnings ?? []).map((w) => `- WARNING: ${w}`),
                ``,
                `DISCLAIMER`,
                REPORT_DISCLAIMER,
              ].join('\n')
              const blob = new Blob([lines], { type: 'text/plain' })
              const a = document.createElement('a')
              a.href = URL.createObjectURL(blob); a.download = `${scenario.name}-report.txt`; a.click()
              URL.revokeObjectURL(a.href)
              setSuccessMsg('Comparison report downloaded.')
            }}
                    className="rounded-md border border-cyan-700/60 px-3 py-1.5 text-xs text-cyan-200 transition hover:bg-cyan-950/50"
                    title="Download a plain-text comparison report of this simulation">
              ⬇ Download Comparison Report
            </button>
            <button onClick={() => act(() => queueScenario(scenario.id, scenario.risk_level === 'high' ? ackHigh : true))}
                    disabled={busy || (scenario.risk_level === 'high' && !ackHigh) || scenario.maintenance_status === 'queued'}
                    className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-40"
                    title="Add to maintenance queue — human review before implementation">
              ➕ Add to Maintenance Queue
            </button>
            <button onClick={() => act(() => apiPost<{ status: string }>(`/shadow/scenarios/${scenario.id}/status`, { status: 'saved' }), 'Simulation saved for later review.')}
                    disabled={busy} className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 transition hover:bg-slate-800">
              💾 Save Simulation
            </button>
            <button onClick={() => act(() => apiPost<{ status: string }>(`/shadow/scenarios/${scenario.id}/status`, { status: 'discarded' }), 'Simulation ended — no changes were applied.')}
                    disabled={busy} className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-400 transition hover:bg-slate-800">
              ✕ End Simulation
            </button>
          </div>
          <div className="text-[9px] italic text-slate-600">{scenario.note}</div>
        </div>
      )}
    </div>
  )
}
