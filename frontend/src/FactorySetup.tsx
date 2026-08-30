import React, { useMemo, useState } from 'react'
import { errMsg, useCreateFactory, useFactories, useSimulateFactory, type FactorySummary } from './api'
import { KpiCard, Legend, Meter, StateNotice } from './components'

/* ===========================================================================
 * CONFIGURE ANY FACTORY — Factory Setup wizard.
 *
 * Flow:  Factory → Lines → Stations → Equipment → Sensors → Review → Create
 *        Digital Twin → Open Twin Dashboard
 *
 * Everything is a draft until "Create Digital Twin" POSTs to /factories — the
 * backend validates, writes a site-config YAML, provisions the real
 * Plant/ProductionLine/Station/Sensor rows and activates the factory. The
 * twin then shows "no historical data connected / simulation mode available"
 * until simulation data is generated (explicitly labeled as such).
 *
 * Observability is COMPUTED from the configured engine sensors
 * (torque/vibration/temperature/motor_current → coverage = engine/4), never
 * entered by hand. cycle_time / throughput / quality are event-derived and do
 * not create Sensor rows — matching the backend exactly.
 * ========================================================================= */

// ---------- domain constants (mirror backend factory_config.py) ----------
export const ENGINE_SENSORS = ['torque', 'vibration', 'temperature', 'motor_current'] as const
export const EVENT_SENSORS = ['cycle_time', 'throughput', 'quality'] as const
export const SENSOR_OPTIONS: { key: string; label: string; unit: string; engine: boolean }[] = [
  { key: 'cycle_time', label: 'Cycle time', unit: 's', engine: false },
  { key: 'throughput', label: 'Throughput', unit: 'units/h', engine: false },
  { key: 'quality', label: 'Quality events', unit: '—', engine: false },
  { key: 'torque', label: 'Torque', unit: 'Nm', engine: true },
  { key: 'vibration', label: 'Vibration', unit: 'mm/s', engine: true },
  { key: 'temperature', label: 'Temperature', unit: '°C', engine: true },
  { key: 'motor_current', label: 'Motor current', unit: 'A', engine: true },
]
export const EQUIPMENT_OPTIONS = [
  { key: 'welding', label: 'Welding', archetype: 'welding' },
  { key: 'torque_tool', label: 'Torque / fastening tool', archetype: 'torque' },
  { key: 'robot', label: 'Robotic cell', archetype: 'fastening' },
  { key: 'paint', label: 'Paint / coating', archetype: 'painting' },
  { key: 'inspection', label: 'Inspection / test', archetype: 'inspection' },
  { key: 'conveyor', label: 'Conveyor / material flow', archetype: 'trim' },
  { key: 'other', label: 'Other / custom', archetype: 'alignment' },
]
export const GENERATION_OPTIONS = [
  { key: 'modern', label: 'Modern (current-gen, networked)' },
  { key: 'mid', label: 'Mid (1 generation old)' },
  { key: 'legacy', label: 'Legacy (older, limited telemetry)' },
]
export const CRITICALITY_OPTIONS = [
  { key: 'critical', label: 'Critical — line stop risk' },
  { key: 'high', label: 'High — frequent monitoring' },
  { key: 'normal', label: 'Normal' },
  { key: 'low', label: 'Low — non-blocking' },
]
export const PROCESS_OPTIONS = [
  'welding', 'torque', 'fastening', 'painting', 'inspection', 'trim', 'sealing', 'alignment',
]

// coverage buckets — identical thresholds to the backend coverage_bucket()
export function coverageOf(sensors: string[]): { coverage: number; bucket: 'high' | 'medium' | 'low' | 'none' } {
  const engine = sensors.filter((s) => (ENGINE_SENSORS as readonly string[]).includes(s)).length
  const coverage = engine / ENGINE_SENSORS.length
  const bucket = coverage >= 0.75 ? 'high' : coverage >= 0.5 ? 'medium' : coverage > 0 ? 'low' : 'none'
  return { coverage, bucket }
}
const COVERAGE_STYLE: Record<string, { label: string; dot: string; text: string; chip: string }> = {
  high: { label: 'High', dot: 'bg-emerald-400', text: 'text-emerald-300', chip: 'bg-emerald-600/20 text-emerald-200 border-emerald-700/50' },
  medium: { label: 'Medium', dot: 'bg-cyan-400', text: 'text-cyan-300', chip: 'bg-cyan-700/25 text-cyan-200 border-cyan-800/50' },
  low: { label: 'Low', dot: 'bg-amber-400', text: 'text-amber-300', chip: 'bg-amber-600/25 text-amber-200 border-amber-700/60' },
  none: { label: 'None — manual only', dot: 'bg-slate-500', text: 'text-slate-400', chip: 'bg-slate-700/50 text-slate-300 border-slate-700' },
}
export const COVERAGE_LEGEND = Object.entries(COVERAGE_STYLE).map(([k, v]) => ({ key: k, label: `${v.label} (${k})`, dot: v.dot }))

// ---------- draft types ----------
export type StationDraft = {
  id: string; name: string; process: string
  equipmentType: string; generation: string; criticality: string
  manualInspection: boolean; sensors: string[]
}
export type LineDraft = { id: string; name: string; type: string; description: string; stations: StationDraft[] }
export type FactoryDraft = { name: string; id: string; location: string; description: string; lines: LineDraft[] }

const blankStation = (id: string): StationDraft => ({
  id, name: id, process: 'welding', equipmentType: 'welding', generation: 'modern',
  criticality: 'normal', manualInspection: false, sensors: ['cycle_time', 'torque', 'vibration'],
})
const blankLine = (id: string): LineDraft => ({
  id, name: id, type: 'Final Assembly', description: '', stations: [blankStation('S01')],
})
const blankFactory = (): FactoryDraft => ({
  name: '', id: '', location: '', description: '',
  lines: [blankLine('FA-01')],
})

// ---------- validation (human-readable messages; mirror backend) ----------
export function validateDraft(draft: FactoryDraft, existing: FactorySummary[]): string[] {
  const errs: string[] = []
  if (!draft.name.trim()) errs.push('Factory name is required.')
  if (!draft.id.trim()) errs.push('Factory ID is required.')
  else if (!/^[A-Z][A-Z0-9-]{1,15}$/.test(draft.id.trim()))
    errs.push('Factory ID must start with a letter and use only A–Z, 0–9, dashes (e.g. PLANT-B).')
  else if (existing.some((f) => f.code === draft.id.trim()))
    errs.push(`Factory ID ${draft.id.trim()} already exists.`)
  const lineIds = new Set<string>()
  draft.lines.forEach((line, li) => {
    if (!line.id.trim()) { errs.push(`Line ${li + 1} needs an ID.`); return }
    const key = line.id.trim()
    if (lineIds.has(key)) errs.push(`Line ${key} is used more than once — line IDs must be unique.`)
    lineIds.add(key)
    if (!line.name.trim()) errs.push(`Line ${key} needs a name.`)
    if (line.stations.length === 0) errs.push(`Line ${key} needs at least one station.`)
    const stIds = new Set<string>()
    line.stations.forEach((st) => {
      if (!st.id.trim()) { errs.push(`Line ${key}: every station needs an ID.`); return }
      const sid = st.id.trim()
      if (stIds.has(sid)) errs.push(`Station ${sid} already exists on this production line.`)
      stIds.add(sid)
      if (!st.name.trim()) errs.push(`Station ${sid} needs a name.`)
      const seen = new Set<string>()
      st.sensors.forEach((s) => {
        if (seen.has(s)) errs.push(`Station ${sid}: duplicate sensor '${s}' — remove one.`)
        seen.add(s)
        if (!SENSOR_OPTIONS.some((o) => o.key === s)) errs.push(`Station ${sid}: unknown sensor type '${s}'.`)
      })
    })
  })
  return errs
}

// ---------- small presentational pieces ----------
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</span>
        {hint && <span className="text-[10px] text-slate-600">{hint}</span>}
      </div>
      {children}
    </label>
  )
}
const inputCls = 'w-full rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-cyan-500/70 placeholder:text-slate-600'
const btn = 'rounded-md px-3 py-1.5 text-xs font-semibold transition disabled:opacity-40'

function StationCoverageChip({ sensors }: { sensors: string[] }) {
  const { coverage, bucket } = coverageOf(sensors)
  const style = COVERAGE_STYLE[bucket]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[11px] ${style.chip}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {(coverage * 100).toFixed(0)}% · {style.label}
    </span>
  )
}

function SensorPicker({ value, onChange, disabled }: { value: string[]; onChange: (v: string[]) => void; disabled?: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
      {SENSOR_OPTIONS.map((opt) => {
        const on = value.includes(opt.key)
        return (
          <button key={opt.key} type="button" disabled={disabled} onClick={() => onChange(on ? value.filter((k) => k !== opt.key) : [...value, opt.key])}
            className={`rounded-md border px-2.5 py-1.5 text-left text-xs transition ${on
              ? (opt.engine ? 'border-cyan-500/70 bg-cyan-950/50 text-cyan-100' : 'border-slate-500/60 bg-slate-800/80 text-slate-200')
              : 'border-slate-800 bg-slate-900/40 text-slate-500 hover:border-slate-600'}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{opt.label}</span>
              <span className={`h-2 w-2 rounded-full ${on ? (opt.engine ? 'bg-cyan-400' : 'bg-slate-400') : 'bg-slate-700'}`} />
            </div>
            <div className="mt-0.5 font-mono text-[10px] text-slate-500">
              {opt.unit}{opt.engine ? ' · telemetry' : ' · event-derived'}
            </div>
          </button>
        )
      })}
    </div>
  )
}

/* ===========================================================================
 * Main wizard
 * ========================================================================= */
const STEPS = ['Factory', 'Lines', 'Stations', 'Equipment', 'Sensors', 'Review'] as const

export default function FactorySetup({ onClose, onOpenTwin }: {
  onClose: () => void
  onOpenTwin: (factoryCode: string) => void
}) {
  const { data: existing } = useFactories()
  const create = useCreateFactory()
  const simulate = useSimulateFactory()
  const [draft, setDraft] = useState<FactoryDraft>(blankFactory)
  const [step, setStep] = useState(0)
  const [lineIdx, setLineIdx] = useState(0)      // line under edit in steps 2–4
  const [stIdx, setStIdx] = useState(0)          // station under edit in steps 3–4
  const [bulkText, setBulkText] = useState('')
  const [bulkOpen, setBulkOpen] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [created, setCreated] = useState<{ code: string; warnings: string[] } | null>(null)

  const existingCodes = useMemo(() => (existing?.factories ?? []).map((f) => f.code), [existing])
  const errs = useMemo(() => validateDraft(draft, existing?.factories ?? []), [draft, existing])
  const line = draft.lines[Math.min(lineIdx, Math.max(draft.lines.length - 1, 0))]
  const station = line?.stations[Math.min(stIdx, Math.max(line.stations.length - 1, 0))]

  // live computed summary across the whole draft (used in every step's sidebar)
  const stats = useMemo(() => {
    let stations = 0, engineSensors = 0, eventSensors = 0, manualOnly = 0
    const buckets = { high: 0, medium: 0, low: 0, none: 0 }
    for (const l of draft.lines) {
      stations += l.stations.length
      for (const s of l.stations) {
        const { coverage, bucket } = coverageOf(s.sensors)
        buckets[bucket] += 1
        engineSensors += s.sensors.filter((k) => (ENGINE_SENSORS as readonly string[]).includes(k)).length
        eventSensors += s.sensors.filter((k) => (EVENT_SENSORS as readonly string[]).includes(k)).length
        if (s.sensors.filter((k) => (ENGINE_SENSORS as readonly string[]).includes(k)).length === 0) manualOnly += 1
      }
    }
    return { lines: draft.lines.length, stations, engineSensors, eventSensors, manualOnly, buckets }
  }, [draft])

  const patchLine = (idx: number, fn: (l: LineDraft) => LineDraft) =>
    setDraft((d) => ({ ...d, lines: d.lines.map((l, i) => (i === idx ? fn(l) : l)) }))
  const patchStation = (li: number, si: number, fn: (s: StationDraft) => StationDraft) =>
    patchLine(li, (l) => ({ ...l, stations: l.stations.map((s, i) => (i === si ? fn(s) : s)) }))

  const goNext = () => {
    if (step === STEPS.length - 1) return
    // gate: Stations step needs lines; Lines step needs at least one line
    if (step === 1 && draft.lines.length === 0) { setErrors(['Add at least one production line.']); return }
    setErrors([])
    setStep((s) => s + 1)
  }

  const submit = () => {
    const v = validateDraft(draft, existing?.factories ?? [])
    if (v.length) { setErrors(v); setStep(STEPS.length - 1); return }
    setErrors([])
    create.mutate({
      factory: { name: draft.name.trim(), id: draft.id.trim(), location: draft.location.trim(), description: draft.description.trim() },
      lines: draft.lines.map((l) => ({
        id: l.id.trim(), name: l.name.trim(), type: l.type.trim(), description: l.description.trim(),
        stations: l.stations.map((s) => ({
          id: s.id.trim(), name: s.name.trim(), process: s.process,
          equipment_type: s.equipmentType, equipment_generation: s.generation,
          criticality: s.criticality, manual_inspection: s.manualInspection, sensors: [...s.sensors],
        })),
      })),
    }, {
      onSuccess: (res) => setCreated({ code: res.factory.code, warnings: res.warnings ?? [] }),
    })
  }

  const openTwin = () => {
    if (!created) return
    onOpenTwin(created.code)
  }

  return (
    <div className="min-h-screen bg-slate-950">
      {/* wizard header */}
      <header className="border-b border-slate-800 bg-slate-900/70 px-5 py-3">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-cyan-600 font-mono text-lg font-bold text-slate-950">A</div>
            <div>
              <div className="font-mono text-sm font-bold tracking-wide">Akiris <span className="text-cyan-400">-</span> DigitalTwin.ai <span className="ml-2 rounded border border-cyan-700/60 bg-cyan-950/50 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-300">FACTORY SETUP</span></div>
              <div className="text-[10px] uppercase tracking-widest text-slate-500">configure any factory → provision the real twin</div>
            </div>
          </div>
          <button onClick={onClose} className={`${btn} border border-slate-700 text-slate-300 hover:bg-slate-800`}>
            ← Back to dashboard
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl p-5">
        {/* stepper */}
        <div className="mb-5 flex items-center gap-1 overflow-x-auto">
          {STEPS.map((s, i) => (
            <React.Fragment key={s}>
              {i > 0 && <div className={`h-px w-6 sm:w-10 ${i <= step ? 'bg-cyan-500/70' : 'bg-slate-800'}`} />}
              <button onClick={() => i < step && setStep(i)}
                className={`flex items-center gap-2 whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs font-semibold transition ${i === step ? 'border-cyan-500/70 bg-cyan-950/50 text-cyan-200' : i < step ? 'border-slate-700 bg-slate-900/60 text-slate-300 hover:bg-slate-800' : 'border-slate-800 bg-slate-900/30 text-slate-600'}`}>
                <span className={`flex h-4 w-4 items-center justify-center rounded-full font-mono text-[10px] ${i < step ? 'bg-cyan-600 text-slate-950' : i === step ? 'bg-cyan-500 text-slate-950' : 'bg-slate-800 text-slate-500'}`}>
                  {i < step ? '✓' : i + 1}
                </span>
                {s}
              </button>
            </React.Fragment>
          ))}
          <div className={`ml-2 hidden items-center gap-1.5 text-[11px] sm:flex ${errs.length ? 'text-red-300' : 'text-emerald-300'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${errs.length ? 'bg-red-400' : 'bg-emerald-400'}`} />
            {errs.length ? `${errs.length} issue${errs.length > 1 ? 's' : ''} to fix` : 'draft valid'}
          </div>
        </div>

        {/* global error / success notices */}
        {errors.length > 0 && (
          <div className="mb-4 rounded-lg border border-red-800/60 bg-red-950/30 px-4 py-3">
            <div className="mb-1 text-xs font-bold uppercase tracking-widest text-red-300">Cannot continue — fix the following</div>
            <ul className="list-inside list-disc space-y-0.5 text-xs text-red-200">
              {errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        )}
        {create.isError && (
          <div className="mb-4 rounded-lg border border-red-800/60 bg-red-950/30 px-4 py-3 text-xs text-red-200">
            <b>Create failed: </b>{errMsg(create.error)}
          </div>
        )}

        {/* layout: content + live summary sidebar */}
        <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
          <div className="space-y-4">
            {created && (
              <div className="rounded-lg border border-emerald-800/60 bg-emerald-950/30 p-4">
                <div className="text-sm font-semibold text-emerald-200">✓ Digital twin created — {created.code} is now the active factory</div>
                <p className="mt-1 text-xs text-emerald-300/80">
                  Topology provisioned (plants → lines → stations → sensors). No historical data was fabricated — this twin
                  starts in <b>simulation mode</b> until you generate data.
                </p>
                {created.warnings.length > 0 && (
                  <ul className="mt-2 list-inside list-disc space-y-0.5 text-[11px] text-amber-200/90">
                    {created.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button onClick={openTwin} className={`${btn} bg-cyan-600 text-slate-950 hover:bg-cyan-500`}>Open Twin Dashboard →</button>
                  <button disabled={simulate.isPending}
                    onClick={() => simulate.mutate({ code: created.code, vehicles: 200 })}
                    className={`${btn} border border-cyan-700/60 bg-cyan-950/40 text-cyan-200 hover:bg-cyan-900/50`}>
                    {simulate.isPending ? 'Generating…' : '⚡ Generate simulation data (labeled)'}
                  </button>
                </div>
                {simulate.isSuccess && (
                  <div className="mt-2 text-[11px] text-cyan-200/80">
                    ✓ {simulate.data.ingested.completed} vehicles simulated for {simulate.data.line_id ? created.code : created.code} — dashboards will now show twin data (clearly labeled as simulated).
                  </div>
                )}
                {simulate.isError && (
                  <div className="mt-2 text-[11px] text-red-300">Simulation failed: {errMsg(simulate.error)}</div>
                )}
              </div>
            )}

            {/* STEP 0 — FACTORY */}
            {step === 0 && (
              <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h3 className="mb-1 text-sm font-semibold text-slate-300">Factory profile</h3>
                <p className="mb-4 text-xs text-slate-500">The plant that owns one or more production lines. Everything else inherits from here.</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Factory name" hint="required">
                    <input className={inputCls} value={draft.name} placeholder="e.g. Aurora Motors — Chennai Plant"
                      onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                  </Field>
                  <Field label="Factory ID" hint="A–Z, 0–9, dashes — unique">
                    <input className={inputCls} value={draft.id} placeholder="e.g. PLANT-B"
                      onChange={(e) => setDraft({ ...draft, id: e.target.value.toUpperCase() })} />
                  </Field>
                  <Field label="Location">
                    <input className={inputCls} value={draft.location} placeholder="City, Country"
                      onChange={(e) => setDraft({ ...draft, location: e.target.value })} />
                  </Field>
                  <Field label="Description">
                    <input className={inputCls} value={draft.description} placeholder="Optional note about the plant"
                      onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                  </Field>
                </div>
                <div className="mt-3 text-[11px] text-slate-500">
                  Existing factory IDs: {existingCodes.length ? existingCodes.join(', ') : '…'}
                </div>
              </section>
            )}

            {/* STEP 1 — LINES */}
            {step === 1 && (
              <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-300">Production lines</h3>
                    <p className="text-xs text-slate-500">A factory can have several lines (final assembly, paint, trim…). Each line gets its own site-config.</p>
                  </div>
                  <button onClick={() => { setDraft((d) => ({ ...d, lines: [...d.lines, blankLine(`L${String(d.lines.length + 1).padStart(2, '0')}`)] })); setLineIdx(draft.lines.length) }}
                    className={`${btn} border border-cyan-700/60 bg-cyan-950/40 text-cyan-200 hover:bg-cyan-900/50`}>
                    + Add line
                  </button>
                </div>
                <div className="space-y-2">
                  {draft.lines.map((l, li) => (
                    <div key={li} className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
                      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
                        <Field label="Line ID">
                          <input className={inputCls} value={l.id} placeholder="FA-01"
                            onChange={(e) => patchLine(li, (x) => ({ ...x, id: e.target.value.toUpperCase() }))} />
                        </Field>
                        <Field label="Line name">
                          <input className={inputCls} value={l.name} placeholder="Final Assembly"
                            onChange={(e) => patchLine(li, (x) => ({ ...x, name: e.target.value }))} />
                        </Field>
                        <Field label="Line type">
                          <select className={inputCls} value={l.type} onChange={(e) => patchLine(li, (x) => ({ ...x, type: e.target.value }))}>
                            {['Final Assembly', 'Body Shop', 'Paint Shop', 'Trim', 'Logistics', 'Custom'].map((t) => <option key={t}>{t}</option>)}
                          </select>
                        </Field>
                        <div className="flex items-end gap-1">
                          <button title="Duplicate line" onClick={() => {
                            const copy = { ...l, id: `${l.id}-COPY`, name: `${l.name} (copy)`, stations: l.stations.map((s) => ({ ...s, id: `${s.id}C` })) }
                            setDraft((d) => { const ls = [...d.lines]; ls.splice(li + 1, 0, copy); return { ...d, lines: ls } })
                          }} className={`${btn} border border-slate-700 text-slate-300 hover:bg-slate-800`}>⧉ Dup</button>
                          <button title="Delete line" onClick={() => { setDraft((d) => ({ ...d, lines: d.lines.filter((_, i) => i !== li) })); setLineIdx((i) => Math.max(0, i - 1)) }}
                            className={`${btn} border border-red-900/60 text-red-300 hover:bg-red-950/40`}>✕</button>
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                        <span className="font-mono">{l.stations.length} station{l.stations.length !== 1 ? 's' : ''}</span>
                        <span className="text-slate-700">·</span>
                        <span>coverage:</span>
                        <Legend items={(Object.keys(COVERAGE_STYLE) as (keyof typeof COVERAGE_STYLE)[])
                          .map((k) => ({ key: k, label: `${COVERAGE_STYLE[k].label}: ${statsByLine(l)[k as keyof ReturnType<typeof statsByLine>]}`, dot: COVERAGE_STYLE[k].dot }))} />
                      </div>
                    </div>
                  ))}
                  {draft.lines.length === 0 && <StateNotice kind="empty" title="No lines" message="Add at least one production line." />}
                </div>
              </section>
            )}

            {/* STEP 2 — STATIONS */}
            {step === 2 && (
              <StationStep draft={draft} lineIdx={lineIdx} setLineIdx={setLineIdx}
                patchLine={patchLine} setDraft={setDraft}
                bulkText={bulkText} setBulkText={setBulkText} bulkOpen={bulkOpen} setBulkOpen={setBulkOpen} />
            )}

            {/* STEP 3 — EQUIPMENT */}
            {step === 3 && (
              <EquipmentStep draft={draft} lineIdx={lineIdx} setLineIdx={setLineIdx} stIdx={stIdx} setStIdx={setStIdx}
                patchStation={patchStation} />
            )}

            {/* STEP 4 — SENSORS */}
            {step === 4 && (
              <SensorStep draft={draft} lineIdx={lineIdx} setLineIdx={setLineIdx} stIdx={stIdx} setStIdx={setStIdx}
                patchStation={patchStation} />
            )}

            {/* STEP 5 — REVIEW */}
            {step === 5 && (
              <ReviewStep draft={draft} stats={stats} errors={errs} />
            )}
          </div>

          {/* live summary sidebar */}
          <aside className="space-y-3">
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Live twin summary</h4>
              <div className="grid grid-cols-2 gap-2">
                <KpiCard label="Lines" value={String(stats.lines)} />
                <KpiCard label="Stations" value={String(stats.stations)} />
                <KpiCard label="Engine sensors" value={String(stats.engineSensors)} sub="torque/vib/temp/current" />
                <KpiCard label="Event signals" value={String(stats.eventSensors)} sub="cycle/throughput/quality" />
              </div>
              <div className="mt-3 space-y-1.5 text-[11px] text-slate-400">
                <div className="flex justify-between"><span>Manual-only stations</span><span className="font-mono text-slate-200">{stats.manualOnly}</span></div>
                <div className="flex justify-between"><span>Observability buckets</span>
                  <span className="font-mono">
                    <span className="text-emerald-300">{stats.buckets.high}H</span> · <span className="text-cyan-300">{stats.buckets.medium}M</span> · <span className="text-amber-300">{stats.buckets.low}L</span> · <span className="text-slate-400">{stats.buckets.none}N</span>
                  </span>
                </div>
              </div>
              <div className="mt-3 border-t border-slate-800 pt-2">
                <Legend items={COVERAGE_LEGEND} />
              </div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-[11px] leading-relaxed text-slate-500">
              Observability is <b className="text-slate-300">computed from the sensors you configure</b> — never entered by hand.
              Coverage = engine telemetry signals ÷ 4 (torque, vibration, temperature, motor current).
              Stations with no engine sensors stay in the twin as <b className="text-amber-300">manual / limited-instrumentation</b>.
            </div>
          </aside>
        </div>

        {/* footer nav */}
        <div className="mt-6 flex items-center justify-between border-t border-slate-800 pt-4">
          <button onClick={() => { setErrors([]); setStep((s) => Math.max(0, s - 1)) }} disabled={step === 0}
            className={`${btn} border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-30`}>
            ← Back
          </button>
          <div className="flex items-center gap-2">
            {step < STEPS.length - 1 ? (
              <button onClick={goNext} className={`${btn} bg-cyan-600 text-slate-950 hover:bg-cyan-500`}>Next: {STEPS[step + 1]} →</button>
            ) : (
              <button onClick={submit} disabled={create.isPending || errs.length > 0}
                className={`${btn} ${create.isPending ? 'bg-slate-700 text-slate-300' : 'bg-cyan-600 text-slate-950 hover:bg-cyan-500'}`}>
                {create.isPending ? '⏳ Creating digital twin…' : '✓ Create Digital Twin'}
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

function statsByLine(l: LineDraft) {
  const b = { high: 0, medium: 0, low: 0, none: 0 }
  for (const s of l.stations) b[coverageOf(s.sensors).bucket] += 1
  return b
}

/* ---------- STEP 2: STATIONS ---------- */
function StationStep({ draft, lineIdx, setLineIdx, patchLine, setDraft, bulkText, setBulkText, bulkOpen, setBulkOpen }: {
  draft: FactoryDraft; lineIdx: number; setLineIdx: (i: number) => void
  patchLine: (i: number, fn: (l: LineDraft) => LineDraft) => void
  setDraft: React.Dispatch<React.SetStateAction<FactoryDraft>>
  bulkText: string; setBulkText: (s: string) => void; bulkOpen: boolean
  setBulkOpen: React.Dispatch<React.SetStateAction<boolean>>
}) {
  const line = draft.lines[Math.min(lineIdx, Math.max(draft.lines.length - 1, 0))]
  const addStation = (id: string) => {
    const clean = id.trim().toUpperCase().replace(/\s+/g, '-')
    if (!clean) return
    if (line.stations.some((s) => s.id === clean)) return
    patchLine(draft.lines.indexOf(line), (l) => ({ ...l, stations: [...l.stations, blankStation(clean)] }))
  }
  const addBulk = () => {
    const ids = bulkText.split(/[\s,;]+/).map((s) => s.trim().toUpperCase().replace(/\s+/g, '-')).filter(Boolean)
    patchLine(draft.lines.indexOf(line), (l) => {
      const taken = new Set(l.stations.map((s) => s.id))
      const fresh = ids.filter((id) => !taken.has(id)).map((id) => blankStation(id))
      return { ...l, stations: [...l.stations, ...fresh] }
    })
    setBulkText('')
  }
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Stations</h3>
          <p className="text-xs text-slate-500">Workstations on the selected line — sensor-poor / manual-only stations are fine and stay in the twin.</p>
        </div>
        <div className="flex items-center gap-1.5">
          <label className="text-[11px] text-slate-500">Line</label>
          <select className={inputCls + ' w-44'} value={draft.lines.indexOf(line)} onChange={(e) => setLineIdx(Number(e.target.value))}>
            {draft.lines.map((l, i) => <option key={i} value={i}>{l.id} — {l.name}</option>)}
          </select>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button onClick={() => addStation(`S${String(line.stations.length + 1).padStart(2, '0')}`)}
          className={`${btn} border border-cyan-700/60 bg-cyan-950/40 text-cyan-200 hover:bg-cyan-900/50`}>+ Add station</button>
        <button onClick={() => setBulkOpen((v) => !v)} className={`${btn} border border-slate-700 text-slate-300 hover:bg-slate-800`}>
          ⧉ Bulk add {bulkOpen ? '▴' : '▾'}
        </button>
      </div>
      {bulkOpen && (
        <div className="mb-3 rounded-md border border-slate-800 bg-slate-950/50 p-3">
          <div className="mb-1 text-[11px] text-slate-400">Paste station IDs (spaces / commas / lines). Existing IDs are skipped.</div>
          <div className="flex gap-2">
            <textarea value={bulkText} onChange={(e) => setBulkText(e.target.value)} rows={2} placeholder="S10 S11 S12&#10;S20, S21, S22"
              className={inputCls + ' font-mono'} />
            <button onClick={addBulk} className={`${btn} shrink-0 self-end border border-cyan-700/60 bg-cyan-950/40 text-cyan-200 hover:bg-cyan-900/50`}>Add</button>
          </div>
        </div>
      )}

      {line.stations.length === 0 && <StateNotice kind="empty" title="No stations yet" message="Add a station or bulk-add several at once." />}
      <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {line.stations.map((s, si) => {
          const { bucket } = coverageOf(s.sensors)
          return (
            <div key={si} className="flex items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2">
              <div className="min-w-0">
                <div className="font-mono text-sm font-bold text-slate-200">{s.id}</div>
                <div className="truncate text-[11px] text-slate-500">{s.name}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <StationCoverageChip sensors={s.sensors} />
                <button title="Duplicate station" onClick={() => patchLine(draft.lines.indexOf(line), (l) => {
                  const ls = [...l.stations]; ls.splice(si + 1, 0, { ...s, id: `${s.id}C`, name: `${s.name} (copy)` }); return { ...l, stations: ls }
                })} className={`${btn} border border-slate-700 px-2 text-slate-300 hover:bg-slate-800`}>⧉</button>
                <button title="Delete station" onClick={() => patchLine(draft.lines.indexOf(line), (l) => ({ ...l, stations: l.stations.filter((_, i) => i !== si) }))}
                  className={`${btn} border border-red-900/60 px-2 text-red-300 hover:bg-red-950/40`}>✕</button>
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 text-[11px] text-slate-500">
        {line.stations.length} station{line.stations.length !== 1 ? 's' : ''} on {line.id} ·{' '}
        {statsByLine(line).none} manual-only
      </div>
    </section>
  )
}

/* ---------- STEP 3: EQUIPMENT ---------- */
function EquipmentStep({ draft, lineIdx, setLineIdx, stIdx, setStIdx, patchStation }: {
  draft: FactoryDraft; lineIdx: number; setLineIdx: (i: number) => void
  stIdx: number; setStIdx: (i: number) => void
  patchStation: (li: number, si: number, fn: (s: StationDraft) => StationDraft) => void
}) {
  const line = draft.lines[Math.min(lineIdx, Math.max(draft.lines.length - 1, 0))]
  const station = line.stations[Math.min(stIdx, Math.max(line.stations.length - 1, 0))]
  if (!station) return <StateNotice kind="empty" title="No station selected" message="Add stations in the Stations step first." />
  const li = draft.lines.indexOf(line)
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Equipment profile — {station.id}</h3>
          <p className="text-xs text-slate-500">Equipment generation and criticality are independent of sensor coverage — a legacy machine can be fully instrumented, a modern one manual-only.</p>
        </div>
        <div className="flex items-center gap-1.5">
          <select className={inputCls + ' w-40'} value={li} onChange={(e) => { setLineIdx(Number(e.target.value)); setStIdx(0) }}>
            {draft.lines.map((l, i) => <option key={i} value={i}>{l.id}</option>)}
          </select>
          <select className={inputCls + ' w-28'} value={line.stations.indexOf(station)} onChange={(e) => setStIdx(Number(e.target.value))}>
            {line.stations.map((s, i) => <option key={i} value={i}>{s.id}</option>)}
          </select>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Equipment type" hint="maps to station archetype in the twin">
          <select className={inputCls} value={station.equipmentType} onChange={(e) => patchStation(li, line.stations.indexOf(station), (s) => ({ ...s, equipmentType: e.target.value }))}>
            {EQUIPMENT_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Process / operation">
          <select className={inputCls} value={station.process} onChange={(e) => patchStation(li, line.stations.indexOf(station), (s) => ({ ...s, process: e.target.value }))}>
            {PROCESS_OPTIONS.map((p) => <option key={p}>{p}</option>)}
          </select>
        </Field>
        <Field label="Equipment generation" hint="independent of instrumentation">
          <select className={inputCls} value={station.generation} onChange={(e) => patchStation(li, line.stations.indexOf(station), (s) => ({ ...s, generation: e.target.value }))}>
            {GENERATION_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Criticality">
          <select className={inputCls} value={station.criticality} onChange={(e) => patchStation(li, line.stations.indexOf(station), (s) => ({ ...s, criticality: e.target.value }))}>
            {CRITICALITY_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        </Field>
      </div>

      <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={station.manualInspection}
          onChange={(e) => patchStation(li, line.stations.indexOf(station), (s) => ({ ...s, manualInspection: e.target.checked }))}
          className="h-4 w-4 accent-cyan-500" />
        Manual inspection / no electronic telemetry — keep in twin with <b className="text-amber-300">limited instrumentation</b>
      </label>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span>Legend:</span>
        <Legend items={EQUIPMENT_OPTIONS.map((o) => ({ key: o.archetype, label: o.label.split(' (')[0] }))} />
      </div>
    </section>
  )
}

/* ---------- STEP 4: SENSORS ---------- */
function SensorStep({ draft, lineIdx, setLineIdx, stIdx, setStIdx, patchStation }: {
  draft: FactoryDraft; lineIdx: number; setLineIdx: (i: number) => void
  stIdx: number; setStIdx: (i: number) => void
  patchStation: (li: number, si: number, fn: (s: StationDraft) => StationDraft) => void
}) {
  const line = draft.lines[Math.min(lineIdx, Math.max(draft.lines.length - 1, 0))]
  const station = line.stations[Math.min(stIdx, Math.max(line.stations.length - 1, 0))]
  if (!station) return <StateNotice kind="empty" title="No station selected" message="Add stations in the Stations step first." />
  const li = draft.lines.indexOf(line)
  const { coverage, bucket } = coverageOf(station.sensors)
  const st = COVERAGE_STYLE[bucket]
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Sensor configuration — {station.id}</h3>
          <p className="text-xs text-slate-500">Engine telemetry (cyan) creates real Sensor rows in the twin; event-derived signals (cycle time, throughput, quality) are computed from production events and create no Sensor row.</p>
        </div>
        <div className="flex items-center gap-1.5">
          <select className={inputCls + ' w-40'} value={li} onChange={(e) => { setLineIdx(Number(e.target.value)); setStIdx(0) }}>
            {draft.lines.map((l, i) => <option key={i} value={i}>{l.id}</option>)}
          </select>
          <select className={inputCls + ' w-28'} value={line.stations.indexOf(station)} onChange={(e) => setStIdx(Number(e.target.value))}>
            {line.stations.map((s, i) => <option key={i} value={i}>{s.id}</option>)}
          </select>
        </div>
      </div>

      <SensorPicker value={station.sensors}
        onChange={(v) => patchStation(li, line.stations.indexOf(station), (s) => ({ ...s, sensors: v }))} />

      <div className="mt-4 rounded-md border border-slate-800 bg-slate-950/50 p-3">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">Observability — computed</div>
          <span className={`rounded border px-2 py-0.5 font-mono text-xs font-semibold ${st.chip}`}>
            <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${st.dot}`} />
            {Math.round(coverage * 100)}% · {st.label}
          </span>
        </div>
        <div className="mt-2"><Meter value={coverage} color={bucket === 'none' ? 'bg-slate-600' : bucket === 'low' ? 'bg-amber-500' : bucket === 'medium' ? 'bg-cyan-500' : 'bg-emerald-500'} /></div>
        <div className="mt-2 grid grid-cols-4 gap-1 text-center font-mono text-[10px] text-slate-500">
          {ENGINE_SENSORS.map((s) => (
            <div key={s} className={`rounded border px-1 py-1 ${station.sensors.includes(s) ? 'border-cyan-700/60 bg-cyan-950/40 text-cyan-200' : 'border-slate-800 text-slate-600'}`}>
              {station.sensors.includes(s) ? '●' : '○'} {s}
            </div>
          ))}
        </div>
        <div className="mt-2 text-[11px] text-slate-500">
          {bucket === 'none'
            ? 'No engine telemetry — this station runs as manual / limited-instrumentation. The twin keeps it, with reduced reasoning confidence.'
            : bucket === 'low'
              ? 'One engine signal — low observability; analytics confidence will be limited.'
              : bucket === 'medium'
                ? 'Two engine signals — medium observability.'
                : 'All four engine signals — full observability for this station.'}
        </div>
      </div>
    </section>
  )
}

/* ---------- STEP 5: REVIEW ---------- */
function ReviewStep({ draft, stats, errors }: { draft: FactoryDraft; stats: { lines: number; stations: number; engineSensors: number; eventSensors: number; manualOnly: number; buckets: Record<string, number> }; errors: string[] }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h3 className="mb-1 text-sm font-semibold text-slate-300">Review & create</h3>
      <p className="mb-4 text-xs text-slate-500">Final check before the twin is provisioned. Observability is computed from your sensor selections — no arbitrary scores.</p>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Factory" value={draft.id || '—'} sub={draft.name || 'unnamed'} />
        <KpiCard label="Lines" value={String(stats.lines)} />
        <KpiCard label="Stations" value={String(stats.stations)} />
        <KpiCard label="Manual-only stations" value={String(stats.manualOnly)} tone="text-amber-200" />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {draft.lines.map((l) => (
          <div key={l.id} className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-mono text-sm font-bold text-slate-200">{l.id}</span>
              <span className="text-[11px] text-slate-500">{l.stations.length} stations</span>
            </div>
            <div className="text-[11px] text-slate-500">{l.name}{l.type ? ` · ${l.type}` : ''}</div>
            <div className="mt-2 grid grid-cols-1 gap-1">
              {l.stations.map((s) => {
                const { bucket } = coverageOf(s.sensors)
                return (
                  <div key={s.id} className="flex items-center justify-between gap-2 border-t border-slate-800/60 py-1 text-[11px]">
                    <span className="font-mono text-slate-300">{s.id}</span>
                    <span className="hidden truncate text-slate-500 sm:inline">{s.name}</span>
                    <span className="flex items-center gap-1.5">
                      <span className="text-slate-600">{s.generation}</span>
                      <StationCoverageChip sensors={s.sensors} />
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-md border border-slate-800 bg-slate-950/50 p-3">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Validation</div>
        {errors.length === 0 ? (
          <div className="text-xs text-emerald-300">✓ Draft is valid — Create Digital Twin will provision Plant, Production Lines, Stations and Sensors through the backend and activate this factory.</div>
        ) : (
          <ul className="list-inside list-disc space-y-0.5 text-xs text-red-200">
            {errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        )}
      </div>
    </section>
  )
}
