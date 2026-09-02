# AkiRis — Brownfield-Aware Digital Twin for Vehicle Assembly

**Accenture Innovation Challenge 2026 · Round 2 · Track 4 (DigitalTwin.ai)**

A working, full-stack digital twin of a 42-station mixed-model vehicle assembly
line. It shows where bottlenecks are forming (with evidence, not guesses),
predicts which vehicles carry elevated defect risk *before* final assembly,
traces failures back through each vehicle's production genealogy, and reports
its own data quality and confidence — because a twin that can't say "I don't
know" isn't trustworthy on a real floor.

> **Deployment posture: read-only / shadow mode.** The twin observes, analyzes,
> predicts and recommends. It never writes to PLCs. Control-path automation is
> a future phase, gated on validation and scheduled maintenance windows.

Youtube Demo Video URL = https://youtu.be/nfyGfni0x58
Live Demo URL = https://akiris-digital-twin.vercel.app/

---

## Quick Navigation

| Section | Section | Section |
|---|---|---|
| [1. Problem](#1-problem) | [2. Real-world challenges addressed](#2-real-world-challenges-addressed) | [3. Solution overview](#3-solution-overview) |
| [4. Architecture](#4-architecture) | [Dependencies](#dependencies) | [5. Digital Twin model](#5-digital-twin-model) |
| [6. Data model](#6-data-model-18-tables) | [7. Synthetic data generation](#7-synthetic-data-generation) | [8. Coverage scenarios](#8-coverage-scenarios-3-worlds--measured) |
| [9. Public dataset compatibility](#9-public-dataset-compatibility) | [10. ML pipeline](#10-ml-pipeline) | [11. Missing-data strategy](#11-missing-data-strategy) |
| [12. Bottleneck detection](#12-bottleneck-detection) | [13. Root-cause tracing](#13-root-cause-tracing) | [14. Recommendations](#14-recommendations) |
| [15. Stakeholder views](#15-stakeholder-views) | [16. Integration strategy](#16-integration-strategy) | [17. Scalability](#17-scalability) |
| [18. ROI methodology](#18-roi-methodology) | [19. How to run](#19-how-to-run) | [19b. Scenario-injection layer](#19b-scenario-injection-layer-live-twin-continuation--the-demos-crown) |
| [20. Extension points](#20-extension-points-documented-intentionally-not-faked-in-v1) | [Assumptions](#assumptions) | [Known limitations](#known-limitations) |
| [Live Demo](https://akiris-digital-twin.vercel.app/) | [Demo Video](https://youtu.be/nfyGfni0x58) | [GitHub Repository](https://github.com/hrdkkmr/Akiris-digital-twin) |

---

## 1. Problem
Assembly lines are patchworks of legacy and modern equipment. Bottlenecks have
multi-causal, intermittent roots; defects introduced early may only surface at
late inspections; sensor coverage is uneven; and predictions that cry wolf
destroy operator trust. The task: a digital twin that works **despite** these
conditions, on realistic (simulated) production data.

## 2. Real-world challenges addressed
| Challenge from the problem statement | Where it is handled |
|---|---|
| Mixed legacy/modern equipment, uneven sensors | station `sensor_profile` (full/mid/sparse/manual) + per-station `Sensor` registry; four missingness types distinguished |
| Multi-causal intermittent defects | four explicit causal mechanisms in the generator; ranked "likely contributing factors", never causal claims |
| Cannot modify live production | read-only shadow mode; retrofit actions framed for maintenance windows (see Recommendations) |
| Early defect → late detection | per-vehicle `vehicle_events` genealogy; defect surfaces at downstream inspections; journey trace UI |
| Different stakeholders | one twin state → three decision layers (Supervisor/Manager/Leadership tabs) |
| Scale beyond one line | twin core vs site config split (`configs/*.yaml`); station archetypes, zero hard-coded stations |
| Trust + validation | `predictions` resolve against actual outcomes; live precision/recall/FPR/FNR endpoint; confidence + completeness on every prediction |
| Poor observability / incomplete evidence | station-level observability advisor, coverage/completeness/freshness signals, evidence-aware analytics confidence and recommended instrumentation gaps |

## 3. Solution overview
Synthetic-but-calibrated factory (SimPy) → normalized event stream → ingestion
pipeline (stateful, bulk) → relational twin state (PostgreSQL/SQLite) → services
(bottleneck, genealogy, data-quality, recommendations, ROI) → ML (RandomForest
defect risk, IsolationForest anomalies) → FastAPI → React/TS dashboards.

The product experience is organized as **OBSERVE → ANALYZE → PREDICT → RECOMMEND**:
station observability and evidence first, then bottleneck/defect analysis,
vehicle-level prediction and genealogy, followed by advisory actions and safe
shadow validation.

## 4. Architecture
```
simulator / CSV / (future: PLC·OPC-UA·MQTT·MES)
        │  DataSource ABC (app/ingestion/base.py) — registry pattern
        ▼
ingestion.pipeline  — topology upsert, genealogy pairing, sensor aggregation,
        │             inspection resolution, chunked bulk writes
        ▼
database — 18 tables, FK + indexes (plants→lines→stations→sensors;
        vehicles→vehicle_events→inspections→defects; readings, kpis,
        anomalies, predictions, recommendations, model_versions, data_quality)
        ▼
services/ (twin_state · bottleneck · genealogy · data_quality · recommendations · business)
ml/       (features → defect_model · anomaly · registry)
        ▼
FastAPI routers (meta/fleet/analytics/production/ops)  →  React frontend (3 personas)
```

Modular monolith by design (no premature microservices). Every boundary is an
interface; swap-in points are explicit (see §20).

## Dependencies

AkiRis is built as a modular full-stack application using open-source technologies across simulation, data engineering, machine learning, backend APIs, frontend visualization, deployment, and testing.

### Backend & AI

| Technology | Purpose |
|---|---|
| **Python 3.10+** | Core backend, simulation and ML runtime |
| **FastAPI** | REST API layer |
| **SQLAlchemy** | Database ORM and persistence |
| **Pandas / NumPy** | Data processing and feature engineering |
| **scikit-learn** | Defect-risk and anomaly models |
| **SimPy** | Discrete-event manufacturing simulation |
| **Pydantic** | API/data validation |
| **Joblib** | Model artifact serialization |
| **python-dotenv** | Environment/configuration management |
| **Uvicorn** | ASGI application server |

### Frontend

| Technology | Purpose |
|---|---|
| **React** | Web application UI |
| **TypeScript** | Type-safe frontend development |
| **Vite** | Frontend build and development tooling |
| **Tailwind CSS** | UI styling |
| **Axios** | Backend API communication |
| **Recharts** | Production and analytics visualizations |
| **React Router** | Frontend routing |
| **Zustand** | Client-side state management |

### Database & Data

| Technology | Purpose |
|---|---|
| **PostgreSQL** | Production-oriented relational twin state |
| **SQLite** | Zero-config local development |
| **CSV / JSONL** | Replayable data-source format |
| **SimPy event stream** | Synthetic production event generation |

### Industrial Integration

| Technology | Status / Purpose |
|---|---|
| **MQTT / Sparkplug-style topics** | Streaming integration path |
| **OPC-UA** | Future PLC/equipment integration adapter |
| **PLC** | Future production control integration |
| **MES / Historian** | Future enterprise production-data integration |
| **DataSource adapter pattern** | Allows new plant/data sources without changing twin core |

> Industrial control integrations are intentionally adapter-based in V1. AkiRis runs in read-only/shadow mode and does not write commands to live PLCs.

### Infrastructure & Observability

| Technology | Purpose |
|---|---|
| **Docker** | Containerized deployment |
| **Docker Compose** | Local multi-service orchestration |
| **Prometheus** | Metrics collection |
| **Grafana** | Operational monitoring dashboards |

### Testing & Security

| Technology | Purpose |
|---|---|
| **Pytest** | Backend automated tests |
| **Locust** | API/load testing |
| **pip-audit** | Python dependency security auditing |
| **npm audit** | Frontend dependency security auditing |
| **API-key protection** | Protection for mutating operational endpoints |
| **CORS controls** | Deployment-level origin restrictions |

### Project Configuration

Python dependencies are maintained in:

    backend/requirements.txt

Frontend dependencies are maintained in:

    frontend/package.json

Environment-specific configuration is provided through:

    .env.example
    configs/*.yaml

### Live Prototype

**Live Demo:** https://akiris-digital-twin.vercel.app/

**Demo Video:** https://youtu.be/nfyGfni0x58

The live deployment demonstrates the working digital-twin interface, including station observability, bottleneck analysis, vehicle genealogy, defect-risk prediction, recommendations, scenario injection, and model/data-quality signals.

## 5. Digital Twin model
Asset tree: **Plant → ProductionLine → Station (+StationType=archetype) → Sensor**,
state carried by `station_kpis`, `sensor_readings`, `machine_events`.
Product thread: **Vehicle → VehicleEvent (per station visit) → Inspection → Defect**,
with batches and per-cycle sensor aggregates. Current state served from
`services/twin_state.py`; history queryable at every level.

## 6. Data model (18 tables)
`plants, production_lines, station_types, stations, sensors, production_batches,
vehicles, vehicle_events, sensor_readings, inspections, defects, machine_events,
station_kpis, environment_samples, anomalies, predictions, recommendations,
model_versions, data_quality_metrics`. Vehicle genealogy is a first-class FK
relationship — the UI journey is a query, not hard-coded text.

## 7. Synthetic data generation
`backend/app/simulation/` — discrete-event line: 42 stations across body/paint/
final, 11 archetypes, per-station buffers, parallel capacity where realistic,
scheduled tool-wear maintenance, shift learning curves, diurnal environment.

**Four causal defect mechanisms** (tool degradation, supplier batch, operator
shift, paint environment) create *correlated* quality loss carried per vehicle
(`quality` accumulates; latent defect surfaces at inspections). Ground-truth
causes are stored for evaluation only (never shown as twin knowledge unless
`?truth=true` judge mode). Every run is **seeded and replayable**.
Config knobs: stations, vehicles, sensor coverage, missing data rate, defect
rates, operator variability, degradation rate, batch failure rate, environment.

## 8. Coverage scenarios (3 worlds — MEASURED)
`configs/scenarios/{full,mixed,brownfield}.yaml` — ~95–100% / ~70–85% / ~40–60%
effective availability (configurable assumptions, not industry claims).
Same engine, same DB, same models. The experiment has been run and the
measured comparison (databases included under `data/generated/`) is in
[`docs/scenario_report.md`](docs/scenario_report.md).

Headline: **analytics confidence collapses 0.99 → 0.67 → 0.42 as coverage
drops** — which is exactly why the twin reports its observability per station
instead of pretending uniform knowledge.

## 9. Public dataset compatibility
Schemas are adapter-friendly: Bosch Production Line / UCI SECOM / MIMII records
can be mapped into the normalized event shape via `CSVDataSource`-style
adapters (documented in `csv_source.py`; no restricted data redistributed).
Generator distributions are empirically inspired (e.g., ~2–4% scrap pressure
with severe class imbalance, station-coded features à la Bosch `L*_S*`).

## 10. ML pipeline
- **Defect risk** (`ml/defect_model.py`): RandomForest over per-vehicle process
  + sensor-statistic + **upstream-anomaly pressure** (IsolationForest scores
  aggregated pre-as-of) + **twin-state context** features (batch failure
  history, final-zone tool-wear trajectory, recent instability/scrap context
  — all time-safe `merge_asof` features). Current main model: v1.6,
  ROC-AUC 0.598, recall 0.80 at an alert-load-capped threshold; the anomaly
  pass runs *before* defect training so event anomaly scores are available
  as MES-visible features in both train and score time. Leakage-safe: prediction
  at end-of-paint uses only earlier information; label = failure at *later*
  final-zone inspections. Time-ordered 70/30 split (no shuffling); decision
  threshold tuned on inner-validation with alert-load constraint; metrics
  include precision/recall/F1/FPR/FNR/PR-AUC + confusion; artifacts versioned
  in `model_versions`.
- **Anomalies** (`ml/anomaly.py`): IsolationForest per sensor-profile, robust
  z-features, train-quantile thresholds (alert-fatigue control), written back
  onto `vehicle_events.anomaly_score`.
- Predictions store probability + **confidence** (completeness- and
  margin-aware) + **data_completeness** + model version; resolved later
  against outcomes (the trust loop).
- The UI exposes prediction history, model version/trust signals, station-level
  confidence and false-alarm/outcome monitoring so operators can distinguish
  model degradation from genuinely higher production risk.

## 11. Missing-data strategy
Four distinguished situations, preserved as metadata: random missing
(completeness<1), station-without-sensor (coverage<1), temporarily unavailable
(freshness/`sensors.status`), manual-only (checklist data governs confidence).
Nothing is silently imputed at rest; ML imputation medians travel with the
model artifact. Extension points reserved for soft sensors and
value-of-information instrumentation ranking.

The **Observability Advisor** turns this into an actionable view: it identifies
stations with low coverage/completeness/freshness, explains why analytics
confidence is reduced, and points to where additional instrumentation would
most improve decision quality.

## 12. Bottleneck detection
V1 evidence composite: 0.40·utilization + 0.25·max-queue + 0.20·|cycle-dev| +
0.15·downtime (max-normalized), status bands, sample-based confidence.
Verified by test: engineered saturated S17 always recovered top-1.

The dashboard supports both historical and recent-window bottleneck evidence,
so a temporary disruption can be separated from the line's persistent
constraint.

Extension points documented: WIP-queue & low-demand utilization methods with
bottleneck-degree ranking (Kawabata et al. 2022); throughput-sensitivity
ground truth (IEEE CASE 2024 "Bottleneck Mining").

## 13. Root-cause tracing
`services/genealogy.py`: backward trace through the vehicle's journey; candidate
factors ranked from anomaly magnitudes, cycle deviations, torque/vibration
instability, NOK checks and batch-cluster evidence, normalized to a
contribution share, always labeled *"likely contributing factor"* with an
explicit "correlation ≠ causation" caveat. Judge mode (`?truth=true`) reveals
simulator ground truth for side-by-side comparison.

The UI presents an evidence-oriented view of the affected unit, its upstream
exposures and the common factors shared with other affected vehicles. This
supports defect propagation/genealogy analysis without claiming unsupported
causality.

## 14. Recommendations
Advisory rule engine: bottleneck rebalancing (maintenance window), tool-wear
service, torque calibration, batch quarantine, data-gap confidence notices,
manual-process review — each with issue/evidence/action/severity/confidence,
status `advisory`.

Recommendations include containment-oriented actions where appropriate and
surface the evidence, severity and confidence behind the recommendation.
The safe-change workflow keeps proposed changes in **shadow mode** and queues
approved actions for a maintenance window; nothing is applied automatically
to the live line.

## 15. Stakeholder views
One backend → three tabs: **Supervisor** (bottleneck banner, line board, alert
feed, at-risk vehicles, scenario injection), **Manager** (throughput/FPY/lead
time, bottleneck ranking chart, defect-zone mix, model trust, observability
table, evidence/genealogy views), **Leadership** (annualized costs, ROI
scenario grid, assumptions panel, advisory actions, rollout rationale).

The three views are different decision layers over the **same twin state**.
There are no separate fake data pipelines.

## 16. Integration strategy
`DataSource` ABC + registry. Implemented: `SimulatorDataSource` (streams SimPy
events straight into the pipeline), `CSVDataSource` (JSONL/CSV replay — also
the template for Bosch/SECOM/MIMII adapters). Documented futures:
`FutureMQTTDataSource`, `FutureOPCUADataSource`, `FuturePLCDataSource`,
MES/historian file drops. The simulator itself can publish MQTT/Sparkplug-style
topics when a broker is present (`scripts/run_sim.py --mqtt localhost`).

## 17. Scalability
New plant = new YAML (stations/archetypes/sensor mix), zero core-code changes;
stations ordered by config; all services operate on any topology. Ingest is
chunked bulk (10k+ vehicle runs practical; 2000-vehicle build ≈ 31s on a
laptop-class sandbox incl. 1.1M+ events → 500k+ rows).

## 18. ROI methodology
`services/business.py`: current-state costs from twin data → annualized via
`planned_annual_vehicles` extrapolation factor; improvement shown as a
scenario grid of *assumed* reductions (5/10/15/20%) — **never** as claims.
All knobs in `.env` (see `.env.example`); disclaimer rendered in the UI.

## 19. How to run
### A. Local (fastest, sqlite zero-config)
```bash
pip install -r backend/requirements.txt
python scripts/generate_data.py --fresh --scenario mixed --vehicles 2000   # ~31s
python scripts/train_models.py                                             # train+score+anomalies+dq+recs
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000              # API → :8000/docs
cd frontend && npm install && npm run dev                                  # UI  → :5173
```

### B. Docker (PostgreSQL + backend + frontend)
```bash
docker compose up --build
# backend seeds 1500 vehicles + trains on first boot (TWIN_SEED_VEHICLES)
```

Frontend: http://localhost:5173 · API: http://localhost:8000/docs

### C. Scenario comparison
```bash
for s in full brownfield; do
  python scripts/generate_data.py --fresh --scenario $s --vehicles 2000 \
      --db data/generated/twinline_$s.db
  python scripts/train_models.py --db data/generated/twinline_$s.db
done
```

### D. Regenerate / retrain / tests
```bash
python scripts/generate_data.py --fresh --vehicles 10000     # larger build
python scripts/train_models.py
cd backend && python -m pytest tests/ -q                     # 16 tests
```

### E. Production hardening knobs
```bash
cd backend && alembic upgrade head     # schema migrations (create_all is only a dev fallback)
TWIN_API_KEY=<secret> uvicorn app.main:app   # mutating ops endpoints now require X-API-Key
TWIN_CORS_ORIGINS="https://twin.example.com" # tighten CORS per deployment
TWIN_RATE_LIMIT_PER_MIN=120                  # per-IP mutation rate limit (GETs unaffected)
pip-audit -r backend/requirements.txt        # security audit
locust -f load/locustfile.py --headless -u 60 -r 15 -t 60s --host http://localhost:8000
docker compose --profile ops up              # + Prometheus (:9090) & Grafana (:3000)
```

Health probe `/health` + readiness `/ready`; structured access logs carry
`x-request-id`; **Prometheus `/metrics`** exposes HTTP counters/latency
histograms + twin gauges (top-bottleneck score, at-risk vehicles, resolved
predictions, mean analytics confidence, active model version); security
headers on all responses (`docs/security_audit.md`);
load-tested 60 concurrent users / 1,062 requests / **0 failures**
(`docs/load_test_report.md`). CI runs backend tests, frontend build and a
pip-audit/npm-audit **security gate** on every push.

## 19b. Scenario-injection layer (LIVE twin continuation — the demo's crown)

Not a re-run, not a mock: the line **continues** from its last simulated
timestamp with one disruption knob turned up; ingestion appends to the same
database (append-mode topology reuse); anomalies rescore, data quality
recomputes, recommendations regenerate; dashboards react on their normal
polling cycle. Defect-model retrain stays a deliberate button (POST
`/ml/refresh`).

- API: `GET /injection/kinds` · `POST /injection/inject {kind, vehicles,
  target_station?, seed?}` (mutation-guarded, rate-limited)
- UI: supervisor tab 🧪 panel — four buttons + vehicle-count selector +
  shock-target input + report card + retrain action
- Kinds: **tool drift surge** (tools 80% worn, 8× wear → torque anomalies +
  maintenance downtime) · **bad supplier batches** (4 forced-bad + 35% rate →
  scrap cluster + batch-cluster RCA evidence) · **plant sensor outage** (60%
  sample loss → completeness/confidence collapse, explained) · **flow shock**
  (target station ×2.6 → **windowed bottleneck flips while full history keeps
  S17 — the shadowing effect, demonstrated live**; verified: shock @ S30 →
  windowed top S30 0.813 vs S17 0.652)
- Seeds derive per injection (`10_000 + vehicle_count`) so any DB state has a
  deterministic continuation → the stage act is rehearsable and replayable.
- The live act script: 1) Supervisor shows steady state (S17 banner) 2)
  inject **Flow shock @ S30** (300 veh) 3) Manager → bottleneck panel →
  window "last 2h" → S30 dethrones S17 → the paper insight, on stage 4)
  inject **Tool drift** → alert feed + advisories light up 5) **Sensor
  outage** → Manager observability column visibly degrades 6) **Retrain** →
  live trust loop shows metric drift under regime shift: the twin TELLS you
  its model degraded instead of failing silently (why calibration monitoring
  is V2, not V1). Reset afterwards: `generate_data.py --fresh` (stop the API
  first — SQLite sidecar files must not survive a swap).

## 20. Extension points (documented, intentionally NOT faked in V1)
1. Soft sensors for uninstrumented stations
2. Conformal prediction / calibrated uncertainty (prediction ledger)
3. KPI-paper bottleneck methods + sensitivity-analysis ground truth +
   bottleneck-degree leaderboard
4. Temporal causal root-cause graph (Neo4j-ready genealogy)
5. Value-of-information sensor advisor (`data_quality_metrics` is the substrate)
6. Observability score as a business KPI
7. Transferable station archetypes / cross-plant transfer
8. Shadow→Advisory→Controlled automation ladder
9. Real-time streaming (MQTT→Kafka/Flink documented production path)
10. Additional live injection knobs beyond the shipped four (sensor drift /
    sensor malfunction states; the injection service is the seam)

## Assumptions
Synthetic calibrated data stands in for proprietary plant data (explicitly
allowed by the brief); financial assumptions are configurable knobs; ~2–4%
scrap pressure with severe class imbalance mirrors published manufacturing
benchmarks (Bosch Kaggle ~0.58% defect rate at plant scale); takt 45s, 3×8h
shift cadence, paint-zone environment coupling.

## Known limitations
Prediction-as-of is fixed at end-of-paint (per-vehicle multi-stage scoring is
V2); final-zone failure class is rare at prototype volumes (honest metrics —
time-ordered splits + PR-AUC shown; a flag-rate cap protects the alert
channel); anomaly thresholds are per-profile quantiles (adaptive/CUSUM drift
detectors are V2); Docker build not executed in this sandbox (compose is
provided and the exact same commands run locally in section 19A); sensor
*malfunction* injection (distinct from dropout) is a scenario hook, not yet a
demo scenario; the API-key guard covers mutating ops endpoints only — full
RBAC belongs with the eventual SSO/IAM integration, not a prototype.

---

*Prototype · advisory only · no control authority over production equipment.*
