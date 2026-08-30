import { useEffect, useState } from 'react'
import { getActiveLineId, setActiveLineId, useActiveFactory, useActivateFactory, useFactories, useSimulateFactory, useStations, errMsg } from './api'
import { StationDrawer } from './StationDrawer'
import { VehiclePanel } from './VehiclePanel'
import FactorySetup from './FactorySetup'
import Supervisor from './pages/Supervisor'
import Manager from './pages/Manager'
import Leadership from './pages/Leadership'

type Persona = 'supervisor' | 'manager' | 'leadership'

const PERSONAS: { id: Persona; label: string; hint: string }[] = [
  { id: 'supervisor', label: 'Floor Supervisor', hint: 'NOW — live line state, alerts, at-risk vehicles' },
  { id: 'manager', label: 'Plant Manager', hint: 'SHIFT/WEEK — trends, bottleneck ranking, model trust' },
  { id: 'leadership', label: 'Leadership', hint: 'QUARTER — ROI, scenarios, rollout case' },
]

export default function App() {
  const [persona, setPersona] = useState<Persona>('supervisor')
  const [stationId, setStationId] = useState<number | null>(null)
  const [vehicleId, setVehicleId] = useState<number | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
  // module-level selector is not reactive — mirror it in state so a switch
  // re-renders App and every data hook picks up the new line id (query keys
  // carry it, so all views refetch for the selected factory).
  const [syncedLine, setSyncedLine] = useState<number | null>(null)
  const { isError } = useStations()
  const { data: factories } = useFactories()
  const { data: active } = useActiveFactory()
  const activate = useActivateFactory()
  const simulate = useSimulateFactory()

  // Keep the module-level selector in sync with the backend's active factory
  // (TwinContext) — covers first paint and remote switches.
  useEffect(() => {
    if (active && getActiveLineId() !== active.line_id) {
      setActiveLineId(active.line_id)
      setSyncedLine(active.line_id)
    }
  }, [active])

  const activeFactory = factories?.factories.find((f) => f.is_active)

  const switchFactory = (code: string) => {
    if (code === active?.factory_code) return
    // optimistically point every hook at the target factory's first line
    const f = factories?.factories.find((x) => x.code === code)
    const targetLine = f?.lines[0]?.id
    if (targetLine != null) {
      setActiveLineId(targetLine)
      setSyncedLine(targetLine)
    }
    activate.mutate(code)
  }

  const openTwin = (factoryCode: string) => {
    setSetupOpen(false)
    switchFactory(factoryCode)
  }

  if (setupOpen) {
    return <FactorySetup onClose={() => setSetupOpen(false)} onOpenTwin={openTwin} />
  }

  return (
    <div key={syncedLine ?? 'none'} className="flex min-h-screen flex-col">
      <header className="border-b border-slate-800 bg-slate-900/70 px-5 py-3">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-cyan-600 font-mono text-lg font-bold text-slate-950">A</div>
            <div>
              <div className="font-mono text-sm font-bold tracking-wide">Akiris <span className="text-cyan-400">-</span> DigitalTwin.ai</div>
              <div className="text-[10px] uppercase tracking-widest text-slate-500">assembly-line decision support · observe → analyze → predict → recommend</div>
            </div>
          </div>

          {/* factory selector — active factory always visible */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1">
              <span className="text-[10px] uppercase tracking-widest text-slate-500">Factory</span>
              <select
                value={active?.factory_code ?? ''}
                onChange={(e) => e.target.value && switchFactory(e.target.value)}
                disabled={activate.isPending}
                className="max-w-[220px] rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-200 outline-none transition focus:border-cyan-500/70 disabled:opacity-40"
              >
                {!active && <option value="">…</option>}
                {(factories?.factories ?? []).map((f) => (
                  <option key={f.code} value={f.code}>{f.name} ({f.code}){f.is_active ? ' ●' : ''}</option>
                ))}
              </select>
              {active && (
                <span className={`ml-1 flex items-center gap-1 text-[10px] font-semibold ${active.has_data ? 'text-emerald-300' : 'text-amber-300'}`}
                  title={active.has_data ? 'Connected to historical/twin data' : 'No historical data connected — simulation mode'}>
                  <span className={`h-1.5 w-1.5 rounded-full ${active.has_data ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                  {active.has_data ? 'DATA' : 'SIM MODE'}
                </span>
              )}
            </div>
            <button onClick={() => setSetupOpen(true)}
              className="rounded-md border border-cyan-700/60 bg-cyan-950/40 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-900/50"
              title="Configure a new factory and provision it as a real digital twin">
              ⚙ Configure Factory
            </button>
          </div>

          <nav className="flex gap-1 rounded-lg border border-slate-800 bg-slate-950 p-1">
            {PERSONAS.map((p) => (
              <button key={p.id} onClick={() => setPersona(p.id)} title={p.hint}
                className={`rounded-md px-3 py-1.5 text-xs transition ${persona === p.id ? 'bg-cyan-600/80 font-semibold text-slate-950' : 'text-slate-400 hover:bg-slate-800'}`}>
                {p.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 p-5">
        {isError && (
          <div className="mb-4 rounded border border-red-700/60 bg-red-950/40 px-4 py-2 text-sm text-red-200">
            Cannot reach the Akiris server ({'<BASE>'}/api). Start the backend:
            <code className="ml-1 rounded bg-slate-900 px-1">cd backend && uvicorn app.main:app --port 8000</code>
          </div>
        )}

        {/* no-data banner for freshly configured factories */}
        {active && !active.has_data && (
          <div className="mb-4 rounded-lg border border-amber-700/50 bg-amber-950/30 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-amber-100">
                <b>{active.factory_name} ({active.factory_code})</b> — no historical data connected. This twin is in{' '}
                <b className="text-amber-300">simulation mode</b>: topology is live, analytics stay empty until data exists.
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => simulate.mutate({ code: active.factory_code, vehicles: 200 })}
                  disabled={simulate.isPending}
                  className="rounded-md border border-amber-600/60 bg-amber-950/40 px-3 py-1.5 text-xs font-semibold text-amber-200 transition hover:bg-amber-900/40 disabled:opacity-40">
                  {simulate.isPending ? '⏳ Generating simulation data…' : '⚡ Generate simulation data (labeled)'}
                </button>
                <button onClick={() => setSetupOpen(true)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-800">
                  ⚙ Factory Setup
                </button>
              </div>
            </div>
            {simulate.isError && <div className="mt-1 text-xs text-red-300">Simulation failed: {errMsg(simulate.error)}</div>}
            {simulate.isSuccess && (
              <div className="mt-1 text-xs text-emerald-300">
                ✓ {simulate.data.ingested.completed} vehicles simulated — clearly labeled as simulated, never presented as real history.
              </div>
            )}
          </div>
        )}

        {persona === 'supervisor' && <Supervisor onSelectStation={setStationId} onSelectVehicle={setVehicleId} />}
        {persona === 'manager' && <Manager />}
        {persona === 'leadership' && <Leadership onSelectStation={setStationId} />}
      </main>

      <footer className="border-t border-slate-800/60 px-5 py-2 text-center text-[10px] text-slate-600">
        <b className="text-slate-500">Akiris - DigitalTwin.ai</b> · prototype on calibrated synthetic data · advisory only · all projections are estimates, never a guarantee
      </footer>

      {stationId !== null && <StationDrawer stationId={stationId} onClose={() => setStationId(null)} />}
      {vehicleId !== null && <VehiclePanel vehicleId={vehicleId} onClose={() => setVehicleId(null)} />}
    </div>
  )
}
