# TwinLine — Five Innovations (Implemented & Verified)

All five innovations are implemented as a **natural extension** of the existing
TwinLine digital twin (FastAPI + SQLAlchemy backend, React/Vite/Tailwind
frontend, Vite proxy `/api` → `:8000`). No existing functionality was broken:
**18/18 backend tests pass**, `npm run build` (tsc + vite) **passes**, and all
pre-existing endpoints return 200.

Each innovation is delivered at **all three production levels**:
Floor Supervisor → Plant Manager → Leadership.

Innovations 1–3 (Observability Advisor, Multi-Causal Contributing-Factor
Analysis, Safe Change Validation + Shadow Simulation) are documented first;
Innovations 4–5 (Defect Traceback & Propagation Analysis, Prediction Validation
& AI Trust) are documented after them.

---

## Innovation 1 — Observability Advisor
*Where is observability poor, WHY, and WHAT to do about it (with expected gain).*

**New backend service:** `backend/app/services/observability_advisor.py`
- Per-station analysis reusing the existing analytics-confidence formula
  (0.45·coverage + 0.35·completeness + 0.20·freshness − 0.30·anomaly density — **unchanged**).
- Levels: `HIGH / MEDIUM / LOW / CRITICAL_GAP`; priority `CRITICAL/HIGH/MEDIUM/LOW` computed
  from coverage gaps, confidence, staleness, anomaly density and bottleneck context.
- Action types: `ADD_SENSOR / IMPROVE_COVERAGE / MANUAL_INSPECTION / FRESHNESS_ACTION / DATA_QUALITY_ACTION`
  (capped 4/row), each with rationale and a **projected confidence** (capped `conf + 0.30`,
  labeled *estimated* — never presented as measured).
- Calibrated so only `stale` telemetry counts as a fault; `low` freshness on an
  intentionally under-instrumented station is a design property, not double-penalized.

**Endpoint:** `GET /api/observability/advisor` → summary `{critical, high, medium, low}` + 42 station rows.

**Config:** `TWIN_OBS_*` knobs in `backend/app/core/config.py` + `.env.example`.

**UI:**
- **Leadership:** full "Observability Advisor" panel — gap map, priority table (click → station),
  top actions with projected confidence.
- **Plant Manager:** advisor summary strip (level counts) above the coverage→confidence table.
- **Floor Supervisor:** critical-gap stations surface in the live alerts feed.
- **Station drawer:** per-station advisor block (level, gap, actions, projected confidence).

**Live-verified:** summary `{critical: 1, high: 7, medium: 25, low: 9}`;
S21 (cov .25, conf .536, stale) → projected .656 (cap respected: S30 .35 → .65, not 1.00).

---

## Innovation 2 — Multi-Causal Contributing-Factor Analysis
*Never "root cause" — relative evidence scores for the factors that actually exist in the data.*

**New backend service:** `backend/app/services/contributing_factors.py`
- Factor set: `tool_wear / process / upstream / operator / environment`, each with an
  **evidence trail** (e.g. "Batch B005: 1/25 scrapped — 4.0% incidence"; "Tool wear up to 85%").
- Scores normalized to **relative shares**; strength `STRONG ≥ 0.5 / MODERATE ≥ 0.25 / WEAK`.
- `detect_intermittent_patterns` — shift / tool-wear / batch / temperature patterns with
  min-sample guards (`MIN_PATTERN_SAMPLE=30`, `MIN_LIFT=1.5`); shifts derived from timestamps.
- `evidence_matrix` — factor × station STRONG/MEDIUM/WEAK/NONE grid (center + neighbours).
- `analyze_vehicle_contributing_factors` — genealogy-based (reuses `vehicle_journey`).
- Reuses `compute_bottlenecks`; no new tables; disclaimers everywhere
  ("Observed associations from available data. Not a causal determination…").
- **Fixed during delivery:** an infinite-recursion bug (analysis ↔ evidence-matrix mutual
  calls) was refactored into a shared `_station_factors` core; S17 analysis dropped from
  a 100 s hang to **~4.6 s** on demand.

**Endpoints:** `GET /api/contributing-factors/{station_ident}` (code S17 or numeric id),
`GET /api/contributing-factors/vehicle/{id}`, `GET /api/contributing-factors/patterns`,
`GET /api/evidence-matrix/{station_ident}`.

**UI:**
- **Leadership:** high-impact intermittent patterns panel.
- **Plant Manager:** patterns panel + contributing factors at the current constraint station.
- **Floor Supervisor:** "🔍 Investigate" on the bottleneck banner (opens the station
  investigation), at-risk vehicles open the enriched vehicle analysis.
- **Station drawer:** full unified investigation — factor bars with evidence, patterns,
  evidence matrix, observability caveat, disclaimer.
- **Vehicle panel:** genealogy-driven factor analysis with batch/shift context.

**Live-verified:** S17 → upstream 38.1% (STRONG, batch B005), tool_wear 34.7% (STRONG, 85% wear),
process 19.1% (MODERATE, queue 687), environment 8.1% (WEAK); matrix S17/S16/S18 populated.

---

## Innovation 3 — Safe Change Validation + Shadow Simulation
*Changes are simulated on an isolated copy — the live line is NEVER mutated.*

**New backend:** `backend/app/services/shadow_sim.py` + models
`SimulationScenario`, `MaintenanceQueueItem` (`backend/app/models/analytics.py`).
- **Proposed-changes library** generated from current line state + existing recommendations
  (cycle-time reduction at bottlenecks, worn-tool replacement, buffer increase, sensor
  coverage, climate control) — nothing hard-coded per station; works for any line.
- **Shadow twin isolation contract:** the simulation is a pure function over an in-memory
  snapshot (baseline metrics + selected changes). No production row is ever written.
- **Multi-change interaction:** changes run as ONE combined configuration (e.g. two
  cycle-time cuts compound throughput; buffers add WIP; constraint easing may move the
  bottleneck) — never simple per-change sums, with explicit warnings.
- **Risk assessment** labeled "Digital Twin simulation risk assessment": LOW / MEDIUM / HIGH
  from defect-risk delta, utilization pressure, bottleneck movement, parameter-change size,
  low-observability stations and concurrency. HIGH requires explicit human acknowledgement.
- **Maintenance windows:** next-window countdown from sim clock; queue with capacity;
  queueing requires human approval; actions END / SAVE / DOWNLOAD REPORT / ADD TO MAINTENANCE QUEUE.

**Endpoints:**
`GET /api/shadow/changes`, `GET /api/shadow/windows`, `GET/POST /api/shadow/scenarios`,
`GET /api/shadow/scenarios/{id}`, `POST /api/shadow/scenarios/{id}/run|status|queue`,
`GET /api/shadow/queue`.

**Config:** `TWIN_MAINT_*` knobs (window start/duration/interval, queue capacity).

**UI (all three levels):**
- **Leadership:** simulation lab + maintenance queue + simulation history + next-window
  countdown (executive view).
- **Plant Manager:** full lab with queue & history side panel.
- **Floor Supervisor:** countdown + compact lab ("nothing touches the line until reviewed").
- Lab shows **Live/Current Twin vs Shadow Twin synchronized panels**, impact comparison
  table with Δ, risk details, warnings, recommendation, and a plain-text downloadable report
  with disclaimer.

**Live-verified:** 52 proposed changes; SIM-0003 (3 changes incl. cycle-time at S01 +
observability at S09) → **HIGH risk** (score 4: bottleneck shift, >15% cycle change,
low-observability station, 3 concurrent changes); queue **rejected without**
`acknowledge=true` with the exact spec message; accepted with ack → queued for window
T−20.1 h; empty selection rejected with a clear error.

---

## Files changed / added

**New backend services:** `contributing_factors.py`, `observability_advisor.py`, `shadow_sim.py`
**Modified backend:** `api/routes_analytics.py` (I2 + I3 routes), `core/config.py`, `models/analytics.py`
(SimulationScenario, MaintenanceQueueItem), `models/__init__.py`, `.env.example`
**New frontend modules:** `ObsAdvisor.tsx`, `CFAnalysis.tsx`, `ShadowSim.tsx`
**Modified frontend:** `api.ts`, `components.tsx`, `pages/Leadership.tsx`, `pages/Manager.tsx`,
`pages/Supervisor.tsx`, `StationDrawer.tsx`, `VehiclePanel.tsx`, `App.tsx`

## Demo flow (suggested)

1. **Innovation 1 (Leadership):** Observability Advisor → note summary {1 critical, 7 high};
   open S21 → gap + actions + projected confidence (estimated).
2. **Innovation 2 (Supervisor):** bottleneck banner → 🔍 Investigate S17 → 4 factors with
   evidence, pattern cards, evidence matrix; open a scrapped vehicle → genealogy factors.
3. **Innovation 3 (Manager/Leadership):** select 2–3 proposed changes → Run shadow →
   compare Current vs Shadow panels → HIGH risk (if aggressive) → acknowledge → queue for
   maintenance window; watch countdown; download report.

## Limitations (honest)

- All projections/estimates are advisory, labeled "simulated / estimated" — never measured.
- Innovation 2 associations are from available synthetic data; causality requires
  engineering investigation (stated in every payload + UI).
- Innovation 3's shadow physics is a deterministic projection layer over existing station
  metrics, not a real PLC/physics simulation (per spec: do not pretend otherwise).
- Tool-wear / environment evidence depends on stations actually carrying those sensors.
- The maintenance queue is capacity-limited (8/window) — overflow requires waiting for the
  next window.

---

## Innovation 4 — Defect Traceback & Propagation Analysis
*Where was the defect found → where might it have entered → which other units were exposed?*

**New backend service:** `backend/app/services/defect_traceback.py`
- `GET /api/defects` (recent detected defects) + `GET /api/defects/{id}/trace` (full investigation).
- **Trace back:** ranks the vehicle's actual upstream stations (reuses `genealogy.vehicle_journey`)
  with evidence from per-pass anomaly score, cycle deviation, tool wear (StationKpi), station-level
  anomalies, batch incidence and ambient conditions — scored 0..1 with STRONG/MODERATE/WEAK and an
  evidence trail for WHY each station ranked where it did.
- **Exposure window:** derived from actual abnormal-condition timestamps (anomalies, high wear/utilization),
  never an arbitrary fixed duration; falls back to station-activity bounds with a LIMITED TRACEABILITY note.
- **Trace forward:** all units that passed the suspected station during the window, with
  HIGH/MEDIUM/LOW exposure level, batch, shift (derived), status, and CONFIRMED-defect flag.
- **Common exposure, propagation risk** (labeled "Digital Twin propagation-risk estimate"),
  **containment recommendations** (advisory), **inspection priority** buckets, and an observability
  confidence gate (LIMITED TRACEABILITY when origin observability is low).
- Honest epistemology throughout: SUSPECTED ORIGIN / POTENTIAL EXPOSURE — never "confirmed root cause";
  supports multiple plausible origins. ~0.3 s per trace (indexed queries; no full-DB scans).
- Integrates with Innovation 2 (CFA, same evidence language) and Innovation 1 (observability gate).

**UI (all three levels):**
- **Supervisor:** "Detected defects — trace back" panel with [TRACE DEFECT] → full investigation
  (propagation map, origin ranking, window + timeline, affected-unit explorer, common exposures,
  risk, containment, priority).
- **Plant Manager:** defect propagation panel with inline investigation.
- **Leadership:** defect propagation overview with trace workflow.
- **Vehicle panel:** [TRACE DEFECT] button for any vehicle with a detected defect.

**Live-verified:** defect 103 (V002683 @ S12) → S03 STRONG (0.71; anomaly 0.90, cycle dev −11.6 s,
tool wear 66%) → window derived from 3 anomaly events → 87 potentially exposed units, 1 confirmed
defect → HIGH propagation risk (0.68) → containment recommendations. Multiple-origin and
limited-traceability paths also verified across defects 90–103.

---

## Innovation 5 — Prediction Validation & AI Trust
*Predictions are measured against real outcomes — trust is earned, not assumed.*

**New backend service:** `backend/app/services/prediction_trust.py`
- **Endpoints:** `GET /api/predictions/trust`, `POST /api/predictions/trust/retrain|approve|deploy`.
- **Classification lifecycle:** TP / TN / FP / FN from the existing decision threshold; predictions
  without an outcome are PENDING (never counted as validated). Reuses the existing Prediction /
  ModelVersion system — no fake ML.
- **Overall trust:** validated count, precision, recall, false-alarm rate, F1 — all **calculated**
  from the resolved corpus (1,937 validated), with "Insufficient validated outcomes" instead of
  pretending when data is thin.
- **Station-level trust:** predictions attributed to the station in each vehicle's journey with the
  strongest anomaly signal (batched query) — shows where the model is weaker.
- **False-alarm monitor:** rate, worst station, 6-bucket trend, direction.
- **Confidence vs outcome bins** (does high confidence actually predict better?).
- **Observability connection:** stations with low precision AND low sensor coverage get
  "may be affected by incomplete sensor coverage" notes (never a causal claim).
- **Model lifecycle:** production vs candidate; `[RETRAIN]` creates a **candidate** by re-tuning the
  decision threshold on the validated corpus (real computed metrics: precision 0.099 → 0.667,
  false-alarm rate 0.901 → 0.333) — production is never changed by retraining. Human **approve/reject**;
  approval schedules a "Deploy AI prediction model vX" item into the existing **maintenance queue**
  (Innovation 3); **controlled deployment** executes via the maintenance window and promotes the
  candidate to production (old model → superseded). Predictions retain their model version.

**UI (all three levels):** compact "🧠 Prediction Trust" panel —
overall trust + history (result filters) + station trust + false-alarm monitor (+ [Investigate] →
opens the CFA station) + confidence bins + model management with retrain/approve/deploy.
- **Supervisor:** entry button beside the at-risk vehicles panel → full panel.
- **Plant Manager:** full panel (augments the existing model-performance panel).
- **Leadership:** full panel + station links.
- Deep link between Innovations 1, 2 and 5 (observability notes, investigate false alarms).

**Live-verified (proxy):** retrain → candidate v1.1 (precision 0.099→0.667, FAR 0.901→0.333) →
approve → model-deploy item in maintenance queue → deploy → production v1.1; demo state reset to
production v1.0.

---

## Files changed / added (Innovations 4 & 5)
- **New backend:** `services/defect_traceback.py`, `services/prediction_trust.py`
- **Modified backend:** `api/routes_analytics.py` (defects + predictions/trust routes),
  `models/analytics.py` (ModelVersion.status, MaintenanceQueueItem.item_type + nullable scenario_id),
  `db/session.py` (idempotent `ensure_schema` migration)
- **New frontend:** `DefectTraceback.tsx`, `PredictionTrust.tsx`
- **Modified frontend:** `api.ts`, `pages/{Supervisor, Manager, Leadership}.tsx`, `VehiclePanel.tsx`

## Demo flow (60 s each)
1. **Innovation 4 (Supervisor):** Defect panel → [TRACE DEFECT] on a recent defect → origin ranking,
   window, 87 exposed units, HIGH risk, containment → "Instead of manually searching production
   history, TwinLine traces back to suspected origins and forward to exposed units."
2. **Innovation 5 (any level):** 🧠 Prediction Trust → validated 1,937, precision 9.9%, false alarms
   90% (honest!) → station S21/S22 weak + observability notes → [Retrain] → candidate v1.1
   precision 66.7% → [Approve] → scheduled for maintenance window → queue item appears →
   [Complete controlled deployment] → production v1.1.

## Limitations (honest)
- Traceback evidence is limited to signals that actually exist (no supplier field → supplier not
  used; shifts derived from timestamps). Origin ranking is observed association, not causality.
- The exposure window is derived from abnormal signals; when a station is under-instrumented the
  trace shows LIMITED TRACEABILITY instead of pretending.
- Model metrics are computed on the current validated corpus (1,937 rows) — a small sample; the
  panel says "Insufficient validated outcomes" if it ever gets too thin.
- Candidate revalidation re-tunes the decision threshold on validated outcomes — it is not a newly
  trained model artifact (clearly labeled in the UI).
- Model deployment is a controlled simulated workflow (per spec: no real ML artifact is swapped).
