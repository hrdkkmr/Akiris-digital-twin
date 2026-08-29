# TwinLine — run instructions (5 innovations included)

## 1. Backend (FastAPI + SQLAlchemy)
```
cd backend
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
The included demo database (data/generated/twinline.db) already contains the
simulated production data + all five innovations' demo state, so you can start
serving immediately. Health check: http://localhost:8000/docs

## 2. Frontend (React + Vite)
```
cd frontend
npm install            # node_modules is intentionally not shipped
npm run dev            # http://localhost:5173
```
Vite proxies /api -> http://localhost:8000 (see frontend/vite.config.ts).

## 3. Using the three production levels
The top nav switches Floor Supervisor / Plant Manager / Leadership. Every
innovation is surfaced on all three levels.

## 4. (Optional) Regenerate data / retrain
```
python scripts/generate_data.py --fresh --scenario mixed --vehicles 2000
python scripts/train_models.py
```
Then restart the backend. Note: regenerating produces a fresh dataset —
the Innovation 3/5 demo state (maintenance queue, prediction-trust lifecycle)
is re-created on demand from the UI.

## 5. Backend tests
```
cd backend && python -m pytest tests/ -q
```

## Demo flows (60 s each)
- Innovation 1 — Observability Advisor (Leadership): coverage -> confidence -> actions -> projected confidence.
- Innovation 2 — Contributing-Factor Analysis (Supervisor): bottleneck banner -> Investigate S17 -> factors/patterns/evidence matrix.
- Innovation 3 — Shadow Simulation (Manager/Leadership): select changes -> Run shadow -> compare -> risk -> queue for maintenance window.
- Innovation 4 — Defect Traceback (Supervisor): Detected defects -> TRACE DEFECT -> suspected origins -> exposed units -> containment.
- Innovation 5 — Prediction Trust (any level): 🧠 Prediction Trust -> validated metrics -> false alarms -> Retrain -> Approve -> deploy via maintenance window.
