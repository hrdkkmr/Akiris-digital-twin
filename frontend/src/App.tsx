import { useState } from 'react'
import { useStations } from './api'
import { StationDrawer } from './StationDrawer'
import { VehiclePanel } from './VehiclePanel'
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
  const { isError } = useStations()

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-800 bg-slate-900/70 px-5 py-3">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-cyan-600 font-mono text-lg font-bold text-slate-950">A</div>
            <div>
              <div className="font-mono text-sm font-bold tracking-wide">Akiris <span className="text-cyan-400">-</span> DigitalTwin.ai</div>
              <div className="text-[10px] uppercase tracking-widest text-slate-500">assembly-line decision support · observe → analyze → predict → recommend</div>
            </div>
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
