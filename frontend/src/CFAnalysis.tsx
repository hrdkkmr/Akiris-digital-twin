import React from 'react'
import type { CFFactor, CFPattern, CFResp, VehicleCFResp } from './api'

/** Innovation 2 — Multi-causal contributing-factor analysis UI. */

const STRENGTH_STYLE: Record<string, string> = {
  STRONG: 'bg-red-600/25 text-red-200',
  MODERATE: 'bg-amber-600/25 text-amber-200',
  WEAK: 'bg-slate-700/50 text-slate-300',
  NONE: 'bg-slate-800 text-slate-600',
}

export function StrengthTag({ strength }: { strength: string }) {
  const s = strength.toUpperCase()
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${STRENGTH_STYLE[s] ?? STRENGTH_STYLE.NONE}`}>{s}</span>
}

export function FactorBar({ factor }: { factor: CFFactor }) {
  const pct = (factor.score * 100).toFixed(0)
  const color = factor.strength === 'strong' ? 'bg-red-500' : factor.strength === 'moderate' ? 'bg-amber-500' : 'bg-slate-500'
  return (
    <div className="rounded border border-slate-800 bg-slate-900/50 p-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-slate-200">{factor.label}</span>
        <span className="flex items-center gap-2">
          <span className="font-mono text-cyan-300">{pct}%</span>
          <StrengthTag strength={factor.strength} />
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full rounded bg-slate-800">
        <div className={`h-1.5 rounded ${color}`} style={{ width: `${pct}%` }} />
      </div>
      {factor.evidence.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-[10px] text-slate-400">
          {factor.evidence.map((e, i) => <li key={i} className="flex gap-1"><span className="text-slate-600">•</span><span>{e}</span></li>)}
        </ul>
      )}
    </div>
  )
}

export function PatternCard({ pattern }: { pattern: CFPattern }) {
  return (
    <div className="rounded border border-amber-700/50 bg-amber-950/20 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-200">
          <span>⚠</span> {pattern.title}
        </span>
        <StrengthTag strength={pattern.strength} />
      </div>
      <div className="mt-1 text-[11px] text-slate-300">{pattern.description}</div>
      <div className="mt-1 font-mono text-[10px] text-slate-500">
        {Object.entries(pattern.statistics).map(([k, v]) => (
          <span key={k} className="mr-2">{k}: {v}</span>
        ))}
      </div>
    </div>
  )
}

export function EvidenceMatrixGrid({ data, evidenceByFactor }: {
  data: CFResp['evidence_matrix'] | undefined
  /** per-factor evidence bullets for the center station — shown when a cell is clicked */
  evidenceByFactor?: Record<string, string[]>
}) {
  const [active, setActive] = React.useState<{ factor: string; station: string } | null>(null)
  if (!data || data.stations.length === 0) return null
  const labels: Record<string, string> = {
    tool_wear: 'Tool wear', process: 'Process', upstream: 'Supplier', operator: 'Shift', environment: 'Env',
  }
  const clicked = active ? data.matrix[active.factor]?.[active.station] ?? 'NONE' : null
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="py-1">factor</th>
              {data.stations.map((s) => <th key={s} className="px-1 text-cyan-300">{s}</th>)}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.matrix).map(([factor, row]) => (
              <tr key={factor} className="border-t border-slate-800">
                <td className="py-1 text-slate-300">{labels[factor] ?? factor}</td>
                {data.stations.map((s) => {
                  const v = row[s] ?? 'NONE'
                  const isActive = active?.factor === factor && active.station === s
                  return (
                    <td key={s} className="px-1">
                      <button onClick={() => v === 'NONE' ? setActive(null) : setActive({ factor, station: s })}
                              className={`rounded px-1 py-0.5 text-[10px] font-semibold transition ${STRENGTH_STYLE[v] ?? STRENGTH_STYLE.NONE} ${v !== 'NONE' && !isActive ? 'hover:ring-1 hover:ring-cyan-500' : ''} ${isActive ? 'ring-1 ring-cyan-400' : ''}`}
                              title={v === 'NONE' ? 'no evidence' : `evidence trail for ${labels[factor] ?? factor} @ ${s}`}>
                        {v}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {active && clicked && clicked !== 'NONE' && (
        <div className="mt-1.5 rounded border border-cyan-800/60 bg-cyan-950/20 px-2 py-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-cyan-300">
            Evidence trail · {labels[active.factor] ?? active.factor} @ {active.station} ({clicked})
          </div>
          {(evidenceByFactor?.[active.factor] ?? []).length === 0
            ? <div className="mt-0.5 text-[10px] text-slate-400">Open this station's analysis for its detailed evidence trail.</div>
            : <ul className="mt-0.5 space-y-0.5 text-[10px] text-slate-300">
                {(evidenceByFactor?.[active.factor] ?? []).map((e, i) => <li key={i} className="flex gap-1"><span className="text-cyan-500">▸</span>{e}</li>)}
              </ul>}
        </div>
      )}
      <div className="mt-1.5 flex flex-wrap gap-2 text-[10px] text-slate-500">
        {data.legend.map((l) => <span key={l}>{l} = {l === 'NONE' ? 'little/no evidence' : l.toLowerCase() + ' observed association'}</span>)}
      </div>
    </div>
  )
}

export function StationCFAnalysis({ data }: { data?: CFResp }) {
  if (!data) return null
  const incident = data.bottleneck?.status === 'critical'
    ? `Critical bottleneck incident — ${data.station}`
    : data.bottleneck?.status === 'high'
      ? `Elevated bottleneck pressure — ${data.station}`
      : `Station analysis — ${data.station}`
  return (
    <div className="space-y-3">
      <div className="rounded border border-slate-700 bg-slate-800/50 px-2 py-1 text-[11px] font-semibold text-slate-200">
        Incident: {incident}
        {data.bottleneck && <span className="ml-2 font-normal text-slate-400">bottleneck score {data.bottleneck.score} · {data.zone} zone · {data.archetype}</span>}
      </div>
      {data.analysis_note && (
        <div className="rounded border border-amber-700/60 bg-amber-950/25 px-2.5 py-1.5 text-[11px] text-amber-200">
          ⚠ {data.analysis_note}
        </div>
      )}
      <div>
        <div className="mb-1.5 text-[10px] uppercase tracking-widest text-slate-500">Likely contributing factors · relative evidence</div>
        {data.factors.length === 0 && <div className="text-xs text-slate-400">no strong evidence — incident may be stochastic</div>}
        <div className="space-y-1.5">{data.factors.map((f) => <FactorBar key={f.factor} factor={f} />)}</div>
      </div>
      {data.intermittent_patterns.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] uppercase tracking-widest text-slate-500">Intermittent patterns</div>
          <div className="space-y-1.5">{data.intermittent_patterns.map((p, i) => <PatternCard key={i} pattern={p} />)}</div>
        </div>
      )}
      <div>
        <div className="mb-1.5 text-[10px] uppercase tracking-widest text-slate-500">Evidence matrix · factor × station (click a cell for the evidence trail)</div>
        <EvidenceMatrixGrid data={data.evidence_matrix}
                            evidenceByFactor={Object.fromEntries(data.factors.map((f) => [f.factor, f.evidence]))} />
      </div>
      <div className="rounded border border-slate-800 bg-slate-900/40 p-2 text-[10px] italic text-slate-500">{data.disclaimer}</div>
    </div>
  )
}

export function VehicleCFAnalysis({ data }: { data?: VehicleCFResp }) {
  if (!data) return null
  return (
    <div className="space-y-3">
      <div className="rounded border border-slate-800 bg-slate-900/50 p-2 text-[11px] text-slate-300">{data.genealogy_note}</div>
      <div className="space-y-1.5">{data.factors.map((f) => <FactorBar key={f.factor} factor={f} />)}</div>
      <div className="rounded border border-slate-800 bg-slate-900/40 p-2 text-[10px] italic text-slate-500">{data.disclaimer}</div>
    </div>
  )
}
