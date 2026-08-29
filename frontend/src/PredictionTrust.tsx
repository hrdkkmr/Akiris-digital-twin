import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  approveCandidate, deployCandidate, errMsg, revalidateCandidate, usePredictionTrust,
} from './api'

import { Legend, StateNotice, TechDetails } from './components'

/** Innovation 5 — Prediction validation & AI trust.
 * Framing: "How much should we trust this prediction?"
 * Human summary first; ML metrics (precision/recall/FPR/…) inside Technical details.
 * The history table is labeled "Defect Probability vs Actual Outcome" (accurate —
 * probability, not confidence). */

const RESULT_META: Record<string, { label: string; cls: string; dot: string }> = {
  TP: { label: 'True positive — alarm was correct', cls: 'bg-emerald-600/20 text-emerald-200', dot: 'bg-emerald-400' },
  TN: { label: 'True negative — no alarm, no defect', cls: 'bg-slate-700/40 text-slate-300', dot: 'bg-slate-400' },
  FP: { label: 'False alarm — no defect occurred', cls: 'bg-amber-600/25 text-amber-200', dot: 'bg-amber-400' },
  FN: { label: 'Missed defect — not predicted', cls: 'bg-red-600/25 text-red-200', dot: 'bg-red-400' },
  PENDING: { label: 'Awaiting outcome', cls: 'bg-slate-800 text-slate-500', dot: 'bg-slate-600' },
}

function Meter({ pct, color = 'bg-cyan-500' }: { pct: number; color?: string }) {
  return (
    <div className="h-2 w-full rounded bg-slate-800">
      <div className={`h-2 rounded ${color}`} style={{ width: `${Math.min(100, pct * 100)}%` }} />
    </div>
  )
}

export function PredictionTrustPanel({ onOpenStation, onInvestigateFalseAlarms }: {
  onOpenStation?: (stationCode: string) => void
  onInvestigateFalseAlarms?: (stationCode: string) => void
}) {
  const { data, isLoading, isError, error } = usePredictionTrust()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [resultFilter, setResultFilter] = useState('ALL')
  const [showDeploySim, setShowDeploySim] = useState(false)

  if (isLoading) return <StateNotice kind="loading" message="Loading validated predictions…" />
  if (isError) return <StateNotice kind="error" title="Unable to load prediction validation" message={errMsg(error)} />
  if (!data) return null

  const o = data.overall
  const mm = data.model_management
  const doAction = async (fn: () => Promise<Record<string, unknown>>, okText?: string) => {
    setBusy(true); setMsg(null)
    try {
      const r = await fn()
      if (r.error) setMsg({ kind: 'err', text: String(r.error) })
      else setMsg({ kind: 'ok', text: okText ?? String(r.message ?? r.note ?? 'Done.') })
      qc.invalidateQueries({ queryKey: ['pred-trust'] })
      qc.invalidateQueries({ queryKey: ['maint-queue'] })
    } catch (e) { setMsg({ kind: 'err', text: errMsg(e) }) } finally { setBusy(false) }
  }

  const history = data.history.filter((h) => resultFilter === 'ALL' ? true : h.result === resultFilter)
  const cand = mm.candidate
  const prod = mm.production
  const candMetrics = (m: Record<string, number | string> | null | undefined) => m ?? {}
  const prodM = candMetrics(prod?.metrics)
  const candM = candMetrics(cand?.metrics)

  const trustPct = o.precision !== undefined ? o.precision : null

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-300">
        <b className="text-slate-100">How much should we trust this prediction?</b> Akiris compares every
        defect-risk prediction against the actual inspection outcome once it exists — nothing is assumed.
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        {/* overall trust — human summary */}
        <div className="rounded border border-slate-800 bg-slate-900/50 p-2.5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">🧠 AI Prediction Trust</span>
            <span className="font-mono text-[10px] text-slate-500">{o.validated} validated · {o.pending} awaiting outcome</span>
          </div>
          {o.insufficient || o.validated === 0 ? (
            <StateNotice kind="empty" message="Insufficient validated outcomes — results would be meaningless." />
          ) : (
            <>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-2xl text-slate-100">{(trustPct! * 100).toFixed(0)}%</span>
                <span className="text-[10px] text-slate-500">of the alarms raised were real defects (precision)</span>
              </div>
              <Meter pct={trustPct ?? 0} color={trustPct! >= 0.75 ? 'bg-emerald-500' : trustPct! >= 0.5 ? 'bg-amber-500' : 'bg-red-500'} />
              <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div><div className="font-mono text-sm text-slate-100">{(o.recall! * 100).toFixed(0)}%</div><div className="text-[9px] uppercase text-slate-500">defects caught</div></div>
                <div><div className="font-mono text-sm text-amber-200">{(o.false_alarm_rate! * 100).toFixed(1)}%</div><div className="text-[9px] uppercase text-slate-500">false alarms</div></div>
                <div><div className="font-mono text-sm text-slate-100">{o.f1}</div><div className="text-[9px] uppercase text-slate-500">f1 balance</div></div>
              </div>
              <TechDetails label="Technical details (precision / recall / FPR / FNR / ROC-AUC)">
                precision {(o.precision! * 100).toFixed(1)}% · recall {(o.recall! * 100).toFixed(1)}% ·
                false-alarm rate {(o.false_alarm_rate! * 100).toFixed(1)}% · FPR {(o.fpr! * 100).toFixed(1)}% ·
                FNR {(o.fnr ? o.fnr * 100 : (o.fn! / Math.max(o.fn! + o.tp!, 1)) * 100).toFixed(1)}% ·
                accuracy {(o.accuracy! * 100).toFixed(1)}% · confusion TP {o.tp} / FP {o.fp} / TN {o.tn} / FN {o.fn}
              </TechDetails>
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
            <button onClick={() => doAction(revalidateCandidate, 'Candidate prediction policy created for review.')} disabled={busy}
                    className="mt-2 w-full rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-600 disabled:opacity-40">
              {busy ? 'Revalidating…' : '🔄 Revalidate Prediction System'}
            </button>
          )}
          {!cand && (
            <div className="mt-1 text-[9px] text-slate-500">
              Uses accumulated validated outcomes to evaluate and create a candidate prediction policy for human review.
              The production model is never changed by this step.
            </div>
          )}

          {cand && cand.status === 'candidate' && (
            <div className="mt-2 space-y-1.5">
              <div className="rounded border border-cyan-800/60 bg-cyan-950/20 p-1.5 text-[10px]">
                <table className="w-full">
                  <thead><tr className="text-left text-slate-500"><th className="py-0.5">metric</th><th>current v{prod?.version}</th><th>candidate v{cand.version}</th></tr></thead>
                  <tbody className="font-mono">
                    <tr><td className="text-slate-400">alarms that were real</td><td>{((prodM.precision as number) * 100).toFixed(0)}%</td><td className="text-emerald-300">{((candM.precision as number) * 100).toFixed(0)}%</td></tr>
                    <tr><td className="text-slate-400">defects caught</td><td>{((prodM.recall as number) * 100).toFixed(0)}%</td><td>{((candM.recall as number) * 100).toFixed(0)}%</td></tr>
                    <tr><td className="text-slate-400">false alarms</td><td>{((prodM.false_alarm_rate as number) * 100).toFixed(0)}%</td><td className="text-emerald-300">{((candM.false_alarm_rate as number) * 100).toFixed(0)}%</td></tr>
                    <tr><td className="text-slate-400">validated samples</td><td>{String(prodM.validated ?? '—')}</td><td>{String(candM.validated ?? '—')}</td></tr>
                  </tbody>
                </table>
                <div className="mt-0.5 italic text-slate-500">decision threshold re-tuned on validated outcomes — not a newly trained ML artifact</div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => doAction(() => approveCandidate(true), 'Approved — deployment scheduled for the next maintenance window.')} disabled={busy}
                        className="flex-1 rounded-md bg-emerald-700 px-2 py-1.5 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-40">
                  ✓ Approve for deployment
                </button>
                <button onClick={() => doAction(() => approveCandidate(false), 'Candidate rejected — production model unchanged.')} disabled={busy}
                        className="flex-1 rounded-md border border-slate-600 px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40">
                  ✕ Reject
                </button>
              </div>
            </div>
          )}

          {cand && cand.status === 'approved' && (
            <div className="mt-2 space-y-1.5">
              <div className="rounded border border-emerald-800/60 bg-emerald-950/20 p-1.5 text-[11px] text-emerald-200">
                ✅ Approved — deployment is scheduled for the next maintenance window (T−{Math.floor(mm.countdown_s / 3600)}h).
                The production model stays unchanged until then.
              </div>
              <button onClick={() => setShowDeploySim((v) => !v)} disabled={busy}
                      className="w-full rounded-md border border-emerald-700/70 bg-emerald-950/40 px-3 py-1.5 text-xs text-emerald-200 hover:bg-emerald-900/50 disabled:opacity-40">
                🛠 Execute deployment (maintenance window)
              </button>
              {showDeploySim && (
                <div className="rounded border border-slate-700 bg-slate-900/70 p-2 text-[10px] text-slate-300">
                  <div className="mb-1 font-semibold text-amber-200">⚠ Currently outside the scheduled maintenance window</div>
                  The system will only deploy during a maintenance window. In this prototype you can
                  explicitly <b>simulate</b> the window execution to see the workflow end-to-end.
                  <div className="mt-1.5 flex gap-2">
                    <button onClick={() => doAction(() => deployCandidate(true), 'Controlled deployment executed (window simulated in prototype) — candidate is now the production model.')} disabled={busy}
                            className="rounded bg-emerald-700 px-2 py-1 text-[11px] font-semibold text-white hover:bg-emerald-600 disabled:opacity-40">
                      ✓ Simulate window execution
                    </button>
                    <button onClick={() => setShowDeploySim(false)} className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-400">Cancel</button>
                  </div>
                </div>
              )}
            </div>
          )}
          {msg && (
            <div className={`mt-1.5 rounded px-2 py-1 text-[10px] ${msg.kind === 'ok' ? 'bg-emerald-950/40 text-emerald-200' : 'bg-red-950/40 text-red-200'}`}>{msg.text}</div>
          )}
        </div>
      </div>

      {/* false alarm monitor */}
      <div className="rounded border border-amber-800/50 bg-amber-950/10 p-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-amber-200">⚠ False alarm monitor</span>
          <span className="font-mono text-[10px] text-amber-200">
            rate {(data.false_alarm_monitor.rate * 100).toFixed(1)}% · most false alarms at {data.false_alarm_monitor.worst_station ?? '—'} · trend {data.false_alarm_monitor.direction}
          </span>
        </div>
        <div className="mt-0.5 text-[10px] text-slate-400">
          Repeated false alarms can erode floor-level trust — this monitor surfaces where the model cries wolf most often.
        </div>
        {data.false_alarm_monitor.trend.length > 1 && (
          <div className="mt-1.5 flex h-8 items-end gap-1">
            {data.false_alarm_monitor.trend.map((t, i) => (
              <div key={i} className="flex flex-1 flex-col items-center gap-0.5" title={`alarms ${t.alarms} · false-alarm rate ${(t.false_alarm_rate * 100).toFixed(0)}%`}>
                <div className="w-full rounded-t bg-amber-700/60" style={{ height: `${Math.max(4, t.false_alarm_rate * 100 * 0.28)}px` }} />
                <span className="font-mono text-[8px] text-slate-600">{(t.false_alarm_rate * 100).toFixed(0)}</span>
              </div>
            ))}
          </div>
        )}
        {onInvestigateFalseAlarms && (
          <button onClick={() => onInvestigateFalseAlarms(data.false_alarm_monitor.worst_station ?? '')}
                  className="mt-1.5 rounded border border-amber-700/60 bg-amber-950/30 px-2 py-1 text-[10px] text-amber-200 hover:bg-amber-900/40"
                  title="Open multi-causal contributing-factor analysis for the worst false-alarm station">
            🔍 Investigate false alarms (contributing-factor analysis)
          </button>
        )}
      </div>

      {/* station-level trust */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Station-level trust · where is the model weaker?</div>
        <Legend items={[{ key: 'ok', label: 'Reliable' }, { key: 'warning', label: 'Lower reliability' }]} className="mb-1" />
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
                    <span className={`inline-flex items-center gap-1 text-[10px] ${warn ? 'text-amber-300' : 'text-emerald-300'}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${warn ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                      {warn ? 'Lower reliability' : 'Reliable'}
                    </span>
                  </span>
                  <span className="font-mono">{(s.precision * 100).toFixed(0)}% real alarms</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <Meter pct={s.precision} color={warn ? 'bg-amber-500' : 'bg-emerald-500'} />
                  <span className="font-mono text-[9px] text-slate-500">{s.predictions} predictions</span>
                </div>
                {obs && (
                  <div className="mt-1 text-[9px] text-amber-200/80">⚡ {obs.note}</div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* confidence vs outcome */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">Do higher probabilities actually predict better?</div>
        <div className="grid gap-1 md:grid-cols-4">
          {data.confidence_bins.map((b) => (
            <div key={b.range} className="rounded border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-center">
              <div className="font-mono text-sm text-slate-100">{(b.correct_rate * 100).toFixed(0)}%</div>
              <div className="text-[9px] text-slate-500">correct at {b.range} probability · n={b.n}</div>
            </div>
          ))}
        </div>
      </div>

      {/* prediction history — labeled accurately */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">Prediction history · Defect Probability vs Actual Outcome</span>
          <span className="flex gap-1">
            {['ALL', 'TP', 'FP', 'TN', 'FN', 'PENDING'].map((r) => (
              <button key={r} onClick={() => setResultFilter(r)}
                      className={`rounded px-1.5 py-0.5 text-[9px] ${resultFilter === r ? 'bg-cyan-700/60 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}>{r}</button>
            ))}
          </span>
        </div>
        <Legend items={Object.entries(RESULT_META).map(([, v]) => ({ label: v.label, dot: v.dot }))} className="mb-1" />
        {history.length === 0 && <StateNotice kind="empty" message="No predictions match this filter yet." />}
        <div className="max-h-52 overflow-y-auto rounded border border-slate-800">
          <table className="w-full text-[11px] font-mono">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-500">
              <tr><th className="px-2 py-1">vehicle</th><th className="px-1">station</th><th className="px-1">predicted prob</th><th className="px-1">actual outcome</th><th className="px-1">model</th><th className="px-1">result</th></tr>
            </thead>
            <tbody>
              {history.slice(0, 60).map((h) => {
                const meta = RESULT_META[h.result] ?? RESULT_META.PENDING
                return (
                  <tr key={h.id} className="border-t border-slate-800/60">
                    <td className="px-2 py-0.5 text-cyan-300">{h.vin}</td>
                    <td className="px-1 text-slate-400">{h.station ?? '—'}</td>
                    <td className="px-1 text-slate-300">{(h.probability * 100).toFixed(0)}%</td>
                    <td className="px-1 text-slate-400">{h.actual === null ? 'not available yet' : h.actual ? 'defect detected' : 'no defect'}</td>
                    <td className="px-1 text-slate-500">v{h.model_version}</td>
                    <td className="px-1">
                      <span className={`inline-flex items-center gap-1 rounded px-1 py-0.5 text-[9px] font-bold ${meta.cls}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                        {h.result}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-1 text-[9px] italic text-slate-600">
          "Predicted prob" is the model's defect probability, not a calibrated confidence score — see Technical details above.
        </div>
      </div>
    </div>
  )
}
