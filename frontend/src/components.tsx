import React from 'react'
import type { StationSnap } from './api'

export const STATUS_STYLE: Record<string, string> = {
  ok: 'border-emerald-700/60 bg-emerald-950/40',
  warning: 'border-amber-600/60 bg-amber-950/40',
  critical: 'border-red-600/70 bg-red-950/50 animate-pulse',
}
export const STATUS_DOT: Record<string, string> = {
  ok: 'bg-emerald-400', warning: 'bg-amber-400', critical: 'bg-red-500',
}

export function StatusPill({ status }: { status: string }) {
  const color = status === 'critical' ? 'text-red-300' : status === 'warning' ? 'text-amber-300' : 'text-emerald-300'
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-mono ${color}`}>
      <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status] ?? 'bg-slate-500'}`} />
      {status.toUpperCase()}
    </span>
  )
}

export function Meter({ value, color = 'bg-cyan-500' }: { value: number; color?: string }) {
  return (
    <div className="h-1.5 w-full rounded bg-slate-800">
      <div className={`h-1.5 rounded ${color}`} style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} />
    </div>
  )
}

export function KpiCard({ label, value, sub, tone = 'text-slate-100' }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${tone}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function StationTile({ station, onClick }: { station: StationSnap; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-24 rounded-lg border p-2 text-left transition hover:scale-[1.03] hover:border-cyan-500/60 ${STATUS_STYLE[station.status]}`}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-bold">{station.code}</span>
        <span className={`h-2 w-2 rounded-full ${STATUS_DOT[station.status]}`} />
      </div>
      <div className="mt-1 space-y-1 font-mono text-[10px] text-slate-400">
        <div className="flex justify-between"><span>util</span><span className="text-slate-200">{(station.utilization * 100).toFixed(0)}%</span></div>
        <div className="flex justify-between"><span>queue</span><span className="text-slate-200">{station.queue_len}</span></div>
        <div className="flex justify-between">
          <span>{station.sensor_profile}</span>
          <span title="sensor coverage">{(station.sensor_coverage * 100).toFixed(0)}%</span>
        </div>
      </div>
      {station.recent_anomalies > 0 && (
        <div className="mt-1 rounded bg-amber-500/20 px-1 text-center text-[9px] text-amber-300">
          {station.recent_anomalies} anomal{station.recent_anomalies > 1 ? 'ies' : 'y'}
        </div>
      )}
    </button>
  )
}

export function ZoneLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 mt-6 text-xs font-semibold uppercase tracking-widest text-slate-500">{children}</div>
}

export function ConfidenceTag({ confidence }: { confidence: number }) {
  const c = confidence >= 0.8 ? 'text-emerald-300' : confidence >= 0.5 ? 'text-amber-300' : 'text-red-300'
  return <span className={`font-mono text-xs ${c}`}>conf {(confidence * 100).toFixed(0)}%</span>
}

export function Panel({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  )
}

export function simClock(t: number | undefined): string {
  if (t === undefined) return '—'
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// ---------- Innovation 1 — Observability Advisor tags ----------
const PRIORITY_STYLE: Record<string, string> = {
  CRITICAL: 'bg-red-600/30 text-red-200 border-red-700/50',
  HIGH: 'bg-amber-600/30 text-amber-200 border-amber-700/50',
  MEDIUM: 'bg-cyan-700/30 text-cyan-200 border-cyan-800/50',
  LOW: 'bg-slate-700/50 text-slate-300 border-slate-700',
}
export function PriorityTag({ priority }: { priority: string }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${PRIORITY_STYLE[priority] ?? PRIORITY_STYLE.LOW}`}>
      {priority}
    </span>
  )
}

const OBS_LEVEL_STYLE: Record<string, string> = {
  HIGH: 'text-emerald-300',
  MEDIUM: 'text-cyan-300',
  LOW: 'text-amber-300',
  CRITICAL_GAP: 'text-red-300',
}
export function ObsLevelTag({ level }: { level: string }) {
  const label = level === 'CRITICAL_GAP' ? 'CRITICAL GAP' : level
  return <span className={`font-mono text-xs font-semibold ${OBS_LEVEL_STYLE[level] ?? 'text-slate-400'}`}>{label}</span>
}

export function ObsActionTag({ action }: { action: string }) {
  const map: Record<string, string> = {
    ADD_SENSOR: 'bg-violet-600/25 text-violet-200 border-violet-700/50',
    IMPROVE_COVERAGE: 'bg-cyan-700/25 text-cyan-200 border-cyan-800/50',
    MANUAL_INSPECTION: 'bg-amber-600/25 text-amber-200 border-amber-700/50',
    FRESHNESS_ACTION: 'bg-orange-600/25 text-orange-200 border-orange-700/50',
    DATA_QUALITY_ACTION: 'bg-slate-600/25 text-slate-200 border-slate-700',
  }
  const label = action.replace(/_/g, ' ').toLowerCase()
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${map[action] ?? map.DATA_QUALITY_ACTION}`}>{label}</span>
}

// ===========================================================================
// SEMANTIC COLOR TOKENS — one source of truth for what a color means.
// Color is NEVER the only signal: every chip pairs a dot + a text label.
// ===========================================================================
export const SEMANTIC = {
  critical: { label: 'Critical', dot: 'bg-red-500', text: 'text-red-300', chip: 'bg-red-600/25 text-red-200 border-red-700/60' },
  warning: { label: 'Needs attention', dot: 'bg-amber-400', text: 'text-amber-300', chip: 'bg-amber-600/25 text-amber-200 border-amber-700/60' },
  elevated: { label: 'Elevated risk', dot: 'bg-orange-400', text: 'text-orange-300', chip: 'bg-orange-600/25 text-orange-200 border-orange-700/60' },
  healthy: { label: 'Healthy', dot: 'bg-emerald-400', text: 'text-emerald-300', chip: 'bg-emerald-600/20 text-emerald-200 border-emerald-700/50' },
  info: { label: 'Informational / Simulated', dot: 'bg-cyan-400', text: 'text-cyan-300', chip: 'bg-cyan-700/25 text-cyan-200 border-cyan-800/50' },
  unknown: { label: 'No data', dot: 'bg-slate-500', text: 'text-slate-400', chip: 'bg-slate-700/50 text-slate-300 border-slate-700' },
} as const
export type SemanticKey = keyof typeof SEMANTIC

/** Map an app-level status string to a semantic key (centralized). */
export const STATUS_TO_SEMANTIC: Record<string, SemanticKey> = {
  critical: 'critical', high: 'critical', fail: 'critical', FAIL: 'critical', DEFECT: 'critical',
  warning: 'warning', watch: 'warning', medium: 'warning', MEDIUM: 'warning',
  elevated: 'elevated', low: 'elevated', LOW: 'elevated',
  ok: 'healthy', healthy: 'healthy', pass: 'healthy', PASS: 'healthy', stable: 'healthy',
  info: 'info', simulated: 'info', pending: 'unknown', queued: 'info', approved: 'healthy',
}

/** Compact legend/key: dots + labels, visually near the visualization. */
export function Legend({ items, className = '' }: { items: { key?: string; label: string; dot?: string }[]; className?: string }) {
  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-400 ${className}`}>
      {items.map((it, i) => {
        const dot = it.dot ?? (it.key && SEMANTIC[STATUS_TO_SEMANTIC[it.key] ?? 'unknown']?.dot) ?? 'bg-slate-500'
        return (
          <span key={i} className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${dot}`} />
            {it.label}
          </span>
        )
      })}
    </div>
  )
}

/** Icon + text status chip — color is paired with a label for accessibility. */
export function StatusChip({ status, label }: { status: string; label?: string }) {
  const sem = SEMANTIC[STATUS_TO_SEMANTIC[status] ?? 'unknown']
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${sem.chip}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${sem.dot}`} />
      {label ?? status}
    </span>
  )
}

/** Loading / empty / error / success notice for panels (Part 21). */
export function StateNotice({ kind, title, message }: {
  kind: 'loading' | 'empty' | 'error' | 'success'
  title?: string; message?: string
}) {
  const style = kind === 'error' ? 'border-red-800/60 bg-red-950/30 text-red-200'
    : kind === 'success' ? 'border-emerald-800/60 bg-emerald-950/30 text-emerald-200'
    : kind === 'loading' ? 'border-slate-700 bg-slate-900/50 text-slate-300'
    : 'border-slate-800 bg-slate-900/40 text-slate-400'
  const icon = kind === 'loading' ? '⏳' : kind === 'error' ? '⚠' : kind === 'success' ? '✓' : '·'
  return (
    <div className={`rounded border px-2.5 py-2 text-xs ${style}`}>
      <span className="mr-1.5">{icon}</span>
      {title && <b className="mr-1.5">{title}</b>}
      {message ?? (kind === 'loading' ? 'Loading…' : kind === 'empty' ? 'Nothing to show yet.' : kind === 'error' ? 'Please try again.' : 'Done.')}
    </div>
  )
}

/** Collapsible "Technical details" layer — keeps the main screen human,
 * keeps the numbers one click away (Part 19). */
export function TechDetails({ label = 'Technical details', children }: { label?: string; children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)
  return (
    <div className="mt-1.5">
      <button onClick={() => setOpen((v) => !v)}
              className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-widest text-slate-500 transition hover:text-slate-300">
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
        {label}
      </button>
      {open && <div className="mt-1 rounded border border-slate-800 bg-slate-900/60 p-2 font-mono text-[10px] text-slate-400">{children}</div>}
    </div>
  )
}
