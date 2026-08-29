import React, { useMemo, useState } from 'react'
import {
  createScenario, queueScenario, runScenario, useMaintenanceQueue,
  useShadowChanges, useShadowWindows, useSimHistory,
} from './api'
import type { QueueItem, ShadowChange, SimScenario, ShadowWindows } from './api'

/** Innovation 3 — Safe change validation + shadow simulation UI. */

const REPORT_DISCLAIMER = 'Results are Digital Twin simulation projections and should be validated against real production conditions before implementation.'

const fmtS = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  return `${h}h ${m}m ${sec}s`
}

export function RiskBadge({ level }: { level: string }) {
  const l = level.toLowerCase()
  const cls = l === 'high' ? 'bg-red-600/30 text-red-200 border-red-700/60'
    : l === 'medium' ? 'bg-amber-600/25 text-amber-200 border-amber-700/60'
    : 'bg-emerald-600/20 text-emerald-200 border-emerald-700/50'
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${cls}`}>{level}</span>
}

export function MaintenanceCountdown({ win }: { win: ShadowWindows | undefined }) {
  if (!win) return null
  const pct = Math.min(100, (win.queued_items / Math.max(win.capacity, 1)) * 100)
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-slate-200">🛠 Next maintenance window</span>
        <span className="font-mono text-cyan-300">{win.window_label}</span>
      </div>
      <div className="mt-1 font-mono text-xl text-slate-100">T−{fmtS(win.countdown_s)}</div>
      <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-400">
        <div className="h-1.5 flex-1 rounded bg-slate-800">
          <div className="h-1.5 rounded bg-cyan-600" style={{ width: `${pct}%` }} />
        </div>
        <span>{win.queued_items}/{win.capacity} items</span>
      </div>
    </div>
  )
}

export function ChangeLibrary({ changes, selected, onToggle, onSelectAll }: {
  changes: ShadowChange[]; selected: Set<string>
  onToggle: (id: string) => void; onSelectAll: (all: boolean) => void
}) {
  const kinds = new Set(changes.map((c) => c.kind))
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest text-slate-500">Proposed changes library · {changes.length} available</div>
        <button onClick={() => onSelectAll(selected.size !== changes.length)}
                className="text-[10px] text-cyan-300 hover:text-cyan-200">
          {selected.size === changes.length ? 'clear all' : 'select all'}
        </button>
      </div>
      <div className="grid gap-1.5 md:grid-cols-2">
        {changes.map((c) => {
          const on = selected.has(c.id)
          const color = c.kind === 'cycle_time' ? 'text-cyan-300' : c.kind === 'tool_replace' ? 'text-red-300'
            : c.kind === 'buffer' ? 'text-amber-300' : c.kind === 'observability' ? 'text-emerald-300' : 'text-sky-300'
          return (
            <label key={c.id} className={`flex cursor-pointer gap-2 rounded border p-2 transition ${on ? 'border-cyan-700/70 bg-cyan-950/30' : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'}`}>
              <input type="checkbox" checked={on} onChange={() => onToggle(c.id)} className="mt-0.5 accent-cyan-500" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-xs font-medium ${color}`}>{c.title} · {c.station}</span>
                  <span className="font-mono text-[10px] text-slate-500">{c.current} → <span className="text-slate-300">{c.proposed}</span></span>
                </div>
                <div className="mt-0.5 truncate text-[10px] text-slate-400">{c.reason} · {c.expected}</div>
              </div>
            </label>
          )
        })}
      </div>
    </div>
  )
}

const METRIC_LABELS: Record<string, string> = {
  throughput_per_hour: 'Throughput (veh/h)', avg_cycle_time_s: 'Avg cycle time (s)',
  total_queue: 'Total queue (WIP)', defect_risk_pct: 'Defect risk (%)',
  avg_utilization_pct: 'Avg utilization (%)', top_bottleneck: 'Top bottleneck',
  mean_analytics_confidence_pct: 'Analytics confidence (%)',
}

export function ImpactTable({ scenario }: { scenario: SimScenario }) {
  const rows = useMemo(() => Object.keys(METRIC_LABELS).filter((k) => k in scenario.current_metrics), [scenario])
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-500">
            <th className="py-1">Metric</th>
            <th className="py-1 text-slate-300">Current</th>
            <th className="py-1 text-cyan-300">Shadow (projected)</th>
            <th className="py-1 text-slate-500">Δ</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((k) => {
            const a = scenario.current_metrics[k], b = scenario.shadow_metrics[k]
            const num = (v: number | string) => (typeof v === 'number' ? v : parseFloat(String(v).replace(/[^0-9.]/g, '')))
            const na = num(a), nb = num(b)
            const delta = !isNaN(na) && !isNaN(nb) ? nb - na : 0
            const color = k.includes('defect_risk') || k.includes('cycle_time') || k.includes('queue')
              ? delta <= 0 ? 'text-emerald-300' : 'text-red-300'
              : delta >= 0 ? 'text-emerald-300' : 'text-red-300'
            return (
              <tr key={k} className="border-t border-slate-800">
                <td className="py-1 text-slate-300">{METRIC_LABELS[k]}</td>
                <td className="py-1 font-mono text-slate-400">{String(a)}</td>
                <td className="py-1 font-mono text-cyan-200">{String(b)}</td>
                <td className={`py-1 font-mono ${color}`}>{delta === 0 ? '—' : `${delta > 0 ? '+' : ''}${Math.round(delta * 100) / 100}`}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** sim-time (s since epoch of twin clock) → wall clock "HH:MM" */
const simClockHm = (t: number) => {
  const h = Math.floor(t / 3600) % 24
  const m = Math.floor((t % 3600) / 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

export function MaintenanceQueuePanel({ items, capacity, windowStart }: {
  items: QueueItem[]; capacity?: number; windowStart?: number
}) {
  const totalMin = items.reduce((a, b) => a + (b.estimated_duration_min ?? 0), 0)
  return (
    <div className="space-y-1.5">
      {items.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
          <span>{items.length} item(s) · combined est. {totalMin} min</span>
          {windowStart !== undefined && (
            <span className="font-mono text-cyan-300">target window {simClockHm(windowStart)}</span>
          )}
        </div>
      )}
      {items.length === 0 && <div className="text-xs text-slate-500">Nothing queued for the maintenance window yet.</div>}
      {items.slice(0, capacity ?? 8).map((it) => (
        <div key={it.id} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900/40 px-2 py-1.5 text-xs">
          <div className="min-w-0">
            <span className="font-mono text-cyan-300">{it.station_code}</span>{' '}
            <span className="text-slate-300">{it.change}</span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <RiskBadge level={it.risk_level} />
            <span className="font-mono text-[10px] text-slate-500">{it.estimated_duration_min}m</span>
            <span className={`rounded px-1.5 py-0.5 text-[10px] capitalize ${it.status === 'approved' ? 'bg-emerald-600/20 text-emerald-200' : 'bg-slate-800 text-slate-400'}`}>{it.status}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

export function SimHistory({ onOpen }: { onOpen: (id: number) => void }) {
  const { data } = useSimHistory()
  if (!data || data.count === 0) return <div className="text-xs text-slate-500">No shadow simulations run yet.</div>
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
  const { data: lib } = useShadowChanges()
  const { data: win } = useShadowWindows()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [scenario, setScenario] = useState<SimScenario | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ackHigh, setAckHigh] = useState(false)
  const [queueMsg, setQueueMsg] = useState<string | null>(null)
  const [showChanges, setShowChanges] = useState(true)

  const changes = lib?.changes ?? []
  const toggle = (id: string) => setSelected((prev) => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const selectAll = (all: boolean) => setSelected(all ? new Set(changes.map((c) => c.id)) : new Set())

  const start = async () => {
    setError(null); setQueueMsg(null); setBusy(true)
    try {
      const pick = changes.filter((c) => selected.has(c.id)).map((c) => ({ ...c, selected: true }))
      const sc = await createScenario(pick)
      if ((sc as unknown as { error?: string }).error) { setError((sc as unknown as { error: string }).error); return }
      const ran = await runScenario(sc.id)
      setScenario(ran); setShowChanges(false)
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const act = async (fn: () => Promise<unknown>) => {
    setError(null); setQueueMsg(null); setBusy(true)
    try {
      const r = await fn() as { error?: string; status?: string; scenario?: string; note?: string }
      if (r?.error) { setError(r.error); return }
      if (r?.status === 'queued') setQueueMsg(`Queued ${r.scenario} → next maintenance window (human approval required before implementation).`)
      setScenario((s) => s ? { ...s, status: r?.status ?? s.status, maintenance_status: r?.status === 'queued' ? 'queued' : s.maintenance_status } : s)
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  if (!lib) return <div className="text-xs text-slate-400">loading proposed changes…</div>
  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-2">
        <MaintenanceCountdown win={win} />
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5 text-[10px] text-slate-400">
          <div className="mb-1 font-semibold text-slate-300">⚙ Shadow twin isolation</div>
          Changes are simulated on a copy of the current line state. Live production,
          station configuration and production records are <span className="text-slate-200">never mutated</span>.
        </div>
      </div>

      {showChanges && (
        <>
          <ChangeLibrary changes={changes} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={start} disabled={selected.size === 0 || busy}
                    className="rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-40">
              {busy ? 'Running shadow…' : `▶ Run shadow simulation (${selected.size} change${selected.size === 1 ? '' : 's'})`}
            </button>
            {!compact && <span className="text-[10px] text-slate-500">estimates only — never applied to production</span>}
          </div>
        </>
      )}

      {error && <div className="rounded border border-red-800 bg-red-950/40 px-2.5 py-1.5 text-xs text-red-200">⚠ {error}</div>}
      {queueMsg && <div className="rounded border border-emerald-800 bg-emerald-950/40 px-2.5 py-1.5 text-xs text-emerald-200">✓ {queueMsg}</div>}

      {scenario && (
        <div className="space-y-2 rounded border border-cyan-800/60 bg-slate-900/40 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-cyan-200">{scenario.name}</span>
              <RiskBadge level={scenario.risk_level} />
              <span className="text-[10px] uppercase tracking-widest text-slate-500">Digital Twin simulation risk assessment</span>
            </div>
            <span className="text-[10px] text-slate-500">status: {scenario.status}</span>
          </div>

          <div className="rounded border border-slate-700/60 bg-slate-950/60 p-2 text-[10px] text-slate-400">
            ⚠ SIMULATION MODE — No changes are being applied to production.
            <span className="ml-1 font-mono text-slate-300">status: {scenario.status} · {scenario.changes.length} change(s) in shadow</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded border border-slate-800 bg-slate-900/50 p-2">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400">
                <span className="h-2 w-2 rounded-full bg-emerald-400" /> Live / Current Twin
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
                <span className="h-2 w-2 rounded-full bg-cyan-400" /> 🧪 Shadow Twin (simulation)
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
          <div className="space-y-1.5">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Risk detail</div>
              {(scenario.risk_detail?.details ?? []).map((d, i) => (
                <div key={i} className="flex gap-1.5 text-[11px] text-slate-300"><span className="text-amber-400">▸</span>{d}</div>
              ))}
              {(scenario.warnings ?? []).map((w, i) => (
                <div key={`w${i}`} className="flex gap-1.5 text-[11px] text-amber-200/90"><span className="text-amber-500">⚠</span>{w}</div>
              ))}
              {scenario.recommendation && <div className="rounded bg-slate-800/70 px-2 py-1 text-[11px] text-slate-300">{scenario.recommendation}</div>}
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
                `TwinLine — Shadow Simulation Report`,
                `Scenario: ${scenario.name}  |  status: ${scenario.status}`,
                `Risk: ${scenario.risk_level.toUpperCase()} (Digital Twin simulation risk assessment)`,
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
            }}
                    className="rounded-md border border-cyan-700/60 px-3 py-1.5 text-xs text-cyan-200 transition hover:bg-cyan-950/50"
                    title="Download a plain-text report of this simulation">
              ⬇ Download report
            </button>
            <button onClick={() => act(() => queueScenario(scenario.id, scenario.risk_level === 'high' ? ackHigh : true))}
                    disabled={busy || (scenario.risk_level === 'high' && !ackHigh) || scenario.maintenance_status === 'queued'}
                    className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-40"
                    title="Add to maintenance queue — human review before implementation">
              ➕ Add to maintenance queue
            </button>
            <button onClick={() => act(async () => { await fetch(`/api/shadow/scenarios/${scenario.id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'saved' }) }); return { status: 'saved' } })}
                    disabled={busy} className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 transition hover:bg-slate-800">
              💾 Save simulation
            </button>
            <button onClick={() => act(async () => { await fetch(`/api/shadow/scenarios/${scenario.id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'discarded' }) }); return { status: 'discarded' } })}
                    disabled={busy} className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-400 transition hover:bg-slate-800">
              ✕ End simulation
            </button>
          </div>
          <div className="text-[9px] italic text-slate-600">{scenario.note}</div>
        </div>
      )}
    </div>
  )
}
