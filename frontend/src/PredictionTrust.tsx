import React, { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  approveCandidate, deployCandidate, retrainCandidate, usePredictionTrust,
} from './api'
import type { PredictionTrust as TrustData } from './api'

/** Innovation 5 — Prediction validation & AI trust.
 * Compact panel: overall trust, history, station-level trust, false-alarm
 * monitor, confidence bins, observability connection and the production /
 * candidate model lifecycle with controlled deployment. */

const RESULT_STYLE: Record<string, string> = {
  TP: 'bg-emerald-600/20 text-emerald-200',
  TN: 'bg-slate-700/40 text-slate-300',
  FP: 'bg-amber-600/25 text-amber-200',
  FN: 'bg-red-600/25 text-red-200',
  PENDING: 'bg-slate-800 text-slate-500',
}

function fmtClock(t: number) {
  const h = Math.floor(t / 3600) % 24
  const m = Math.floor((t % 3600) / 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function Meter({ pct, color = 'bg-cyan-500' }: { pct: number; color?: string }) {
  return (
    <div className="h-2 w-full rounded bg-slate-800">
      <div className={`h-2 rounded ${color}`} style={{ width: `${Math.min(100, pct * 100)}%` }} />
    </div>
  )
}

export function PredictionTrustPanel({ onOpenStation, onInvestigateFalseAlarms }: {
  /** open the station investigation for a station CODE (e.g. "S12") */
  onOpenStation?: (stationCode: string) => void
  onInvestigateFalseAlarms?: (stationCode: string) => void
}) {
  const { data } = usePredictionTrust()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [resultFilter, setResultFilter] = useState('ALL')
  if (!data) return <div className="text-xs text-slate-400">loading prediction validation…</div>

  const o = data.overall
  const mm = data.model_management
  const doAction = async (fn: () => Promise<Record<string, unknown>>) => {
    setBusy(true); setMsg(null)
    try {
      const r = await fn()
      if (r.error) setMsg({ kind: 'err', text: String(r.error) })
      else setMsg({ kind: 'ok', text: String(r.message ?? r.note ?? 'done') })
      qc.invalidateQueries({ queryKey: ['pred-trust'] })
      qc.invalidateQueries({ queryKey: ['maint-queue'] })
    } catch (e) { setMsg({ kind: 'err', text: String(e) }) } finally { setBusy(false) }
  }

  const history = data.history.filter((h) => resultFilter === 'ALL' ? true : h.result === resultFilter)
  const cand = mm.candidate
  const prod = mm.production
  const candMetrics = (m: Record<string, number | string> | null | undefined) => m ?? {}
  const prodM = candMetrics(prod?.metrics)
  const candM = candMetrics(cand?.metrics)

  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-2">
        {/* overall trust */}
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">🧠 AI Prediction Trust</span>
            <span className="font-mono text-[10px] text-slate-500">validated {o.validated} · pending {o.pending}</span>
          </div>
          {o.insufficient || o.validated === 0 ? (
            <div className="text-xs text-slate-400">Insufficient validated outcomes — results would be meaningless.</div>
          ) : (
            <>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-2xl text-slate-100">{(o.precision! * 100).toFixed(0)}%</span>
                <span className="text-[10px] text-slate-500">precision (of alarms, how many were real)</span>
              </div>
              <Meter pct={o.precision ?? 0} color="bg-cyan-500" />
              <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div><div className="font-mono text-sm text-slate-100">{(o.recall! * 100).toFixed(0)}%</div><div className="text-[9px] uppercase text-slate-500">recall</div></div>
                <div><div className="font-mono text-sm text-amber-200">{(o.false_alarm_rate! * 100).toFixed(1)}%</div><div className="text-[9px] uppercase text-slate-500">false alarms</div></div>
                <div><div className="font-mono text-sm text-slate-100">{o.f1}</div><div className="text-[9px] uppercase text-slate-500">f1</div></div>
              </div>
              <div className="mt-1.5 font-mono text-[9px] text-slate-500">TP {o.tp} · FP {o.fp} · TN {o.tn} · FN {o.fn} · accuracy {(o.accuracy! * 100).toFixed(1)}%</div>
            </>
          )}
          <div className="mt-1 text-[9px] italic text-slate-600">{data.note}</div>
        </div>

        {/* model management */}
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-400">Model management · controlled deployment</div>
          <div className="space-y-1 text-[11px]">
            <div className="flex justify-between"><span className="text-slate-400">Production model</span><span className="font-mono text-slate-100">v{prod?.version ?? '—'}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Candidate model</span>
              <span className="font-mono">{cand ? `v${cand.version} · ${cand.status}` : <span className="text-slate-600">none</span>}</span>
            </div>
            <div className="flex justify-between"><span className="text-slate-400">Next maintenance window</span><span className="font-mono text-cyan-300">{mm.window_label} · T−{Math.floor(mm.countdown_s / 3600)}h</span></div>
          </div>

          {!cand && (
            <button onClick={() => doAction(retrainCandidate)} disabled={busy}
                    className="mt-2 w-full rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-600 disabled:opacity-40">
              {busy ? 'Revalidating…' : '🔄 Retrain / Revalidate model (creates candidate — production untouched)'}
            </button>
          )}

          {cand && cand.status === 'candidate' && (
            <div className="mt-2 space-y-1.5">
              <div className="rounded border border-cyan-800/60 bg-cyan-950/20 p-1.5 text-[10px]">
                <table className="w-full">
                  <thead><tr className="text-left text-slate-500"><th className="py-0.5">metric</th><th>current v{prod?.version}</th><th>candidate v{cand.version}</th></tr></thead>
                  <tbody className="font-mono">
                    <tr><td className="text-slate-400">precision</td><td>{((prodM.precision as number) * 100).toFixed(0)}%</td><td className="text-emerald-300">{((candM.precision as number) * 100).toFixed(0)}%</td></tr>
                    <tr><td className="text-slate-400">recall</td><td>{((prodM.recall as number) * 100).toFixed(0)}%</td><td>{((candM.recall as number) * 100).toFixed(0)}%</td></tr>
                    <tr><td className="text-slate-400">false alarms</td><td>{((prodM.false_alarm_rate as number) * 100).toFixed(0)}%</td><td className="text-emerald-300">{((candM.false_alarm_rate as number) * 100).toFixed(0)}%</td></tr>
                    <tr><td className="text-slate-400">validated</td><td>{String(prodM.validated ?? '—')}</td><td>{String(candM.validated ?? '—')}</td></tr>
                  </tbody>
                </table>
                <div className="mt-0.5 italic text-slate-500">threshold re-tuned on the validated outcome corpus — not a new ML artifact</div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => doAction(() => approveCandidate(true))} disabled={busy}
                        className="flex-1 rounded-md bg-emerald-700 px-2 py-1.5 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-40">
                  ✓ Approve for deployment
                </button>
                <button onClick={() => doAction(() => approveCandidate(false))} disabled={busy}
                        className="flex-1 rounded-md border border-slate-600 px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40">
                  ✕ Reject
                </button>
              </div>
            </div>
          )}

          {cand && cand.status === 'approved' && (
            <div className="mt-2 space-y-1.5">
              <div className="rounded border border-emerald-800/60 bg-emerald-950/20 p-1.5 text-[11px] text-emerald-200">
                ✅ Approved — deployment scheduled for the next maintenance window (T−{Math.floor(mm.countdown_s / 3600)}h).
                Production model is NOT live until the window executes.
              </div>
              <button onClick={() => doAction(deployCandidate)} disabled={busy}
                      className="w-full rounded-md border border-emerald-700/70 bg-emerald-950/40 px-3 py-1.5 text-xs text-emerald-200 hover:bg-emerald-900/50 disabled:opacity-40"
                      title="Simulate maintenance-window execution — promote candidate to production">
                🛠 Complete controlled deployment (maintenance window)
              </button>
            </div>
          )}
          {msg && <div className={`mt-1.5 rounded px-2 py-1 text-[10px] ${msg.kind === 'ok' ? 'bg-emerald-950/40 text-emerald-200' : 'bg-red-950/40 text-red-200'}`}>{msg.text}</div>}
        </div>
      </div>

      {/* false alarm monitor */}
      <div className="rounded border border-amber-800/50 bg-amber-950/10 p-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-amber-200">⚠ False alarm monitor</span>
          <span className="font-mono text-[10px] text-amber-200">
            rate {(data.false_alarm_monitor.rate * 100).toFixed(1)}% · worst station {data.false_alarm_monitor.worst_station ?? '—'} · trend {data.false_alarm_monitor.direction}
          </span>
        </div>
        {data.false_alarm_monitor.trend.length > 1 && (
          <div className="mt-1.5 flex h-8 items-end gap-1">
            {data.false_alarm_monitor.trend.map((t, i) => (
              <div key={i} className="flex flex-1 flex-col items-center gap-0.5" title={`alarms ${t.alarms} · FAR ${(t.false_alarm_rate * 100).toFixed(0)}%`}>
                <div className="w-full rounded-t bg-amber-700/60" style={{ height: `${Math.max(4, t.false_alarm_rate * 100 * 0.28)}px` }} />
                <span className="font-mono text-[8px] text-slate-600">{(t.false_alarm_rate * 100).toFixed(0)}</span>
              </div>
            ))}
          </div>
        )}
        {onInvestigateFalseAlarms && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <button onClick={() => onInvestigateFalseAlarms(data.false_alarm_monitor.worst_station ?? '')}
                    className="rounded border border-amber-700/60 bg-amber-950/30 px-2 py-1 text-[10px] text-amber-200 hover:bg-amber-900/40"
                    title="Open multi-causal contributing-factor analysis for the worst false-alarm station">
              🔍 Investigate false alarms (contributing-factor analysis)
            </button>
          </div>
        )}
      </div>

      {/* station-level trust */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Station-level trust</div>
        <div className="grid max-h-44 gap-1 overflow-y-auto pr-1 md:grid-cols-2">
          {data.station_trust.slice(0, 16).map((s) => {
            const warn = s.precision < 0.6
            const obs = data.observability_notes.find((n) => n.station === s.station)
            return (
              <div key={s.station} className="rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5">
                    <button onClick={() => onOpenStation?.(s.station)}
                            className="font-mono text-cyan-300 hover:underline" title="open station investigation">{s.station}</button>
                    {warn ? <span className="text-amber-300">⚠</span> : <span className="text-emerald-300">✓</span>}
                  </span>
                  <span className="font-mono">{(s.precision * 100).toFixed(0)}% prec</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <Meter pct={s.precision} color={warn ? 'bg-amber-500' : 'bg-emerald-500'} />
                  <span className="font-mono text-[9px] text-slate-500">{s.predictions} pred</span>
                </div>
                {obs && (
                  <div className="mt-1 text-[9px] text-amber-200/80">⚡ {obs.note}</div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* confidence bins */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Confidence vs actual outcome</div>
        <div className="grid gap-1 md:grid-cols-4">
          {data.confidence_bins.map((b) => (
            <div key={b.range} className="rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-center">
              <div className="font-mono text-sm text-slate-100">{(b.correct_rate * 100).toFixed(0)}%</div>
              <div className="text-[9px] text-slate-500">{b.range} prob · n={b.n}</div>
            </div>
          ))}
        </div>
      </div>

      {/* prediction history */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">Prediction history · latest {history.length}</span>
          <span className="flex gap-1">
            {['ALL', 'TP', 'FP', 'TN', 'FN', 'PENDING'].map((r) => (
              <button key={r} onClick={() => setResultFilter(r)}
                      className={`rounded px-1.5 py-0.5 text-[9px] ${resultFilter === r ? 'bg-cyan-700/60 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}>{r}</button>
            ))}
          </span>
        </div>
        <div className="max-h-52 overflow-y-auto rounded border border-slate-800">
          <table className="w-full text-[11px] font-mono">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-500">
              <tr><th className="px-2 py-1">vehicle</th><th className="px-1">station</th><th className="px-1">prob</th><th className="px-1">actual</th><th className="px-1">model</th><th className="px-1">result</th></tr>
            </thead>
            <tbody>
              {history.slice(0, 60).map((h) => (
                <tr key={h.id} className="border-t border-slate-800/60">
                  <td className="px-2 py-0.5 text-cyan-300">{h.vin}</td>
                  <td className="px-1 text-slate-400">{h.station ?? '—'}</td>
                  <td className="px-1 text-slate-300">{(h.probability * 100).toFixed(0)}%</td>
                  <td className="px-1 text-slate-400">{h.actual === null ? '—' : h.actual ? 'defect' : 'none'}</td>
                  <td className="px-1 text-slate-500">v{h.model_version}</td>
                  <td className="px-1"><span className={`rounded px-1 py-0.5 text-[9px] font-bold ${RESULT_STYLE[h.result]}`}>{h.result}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  )
}
