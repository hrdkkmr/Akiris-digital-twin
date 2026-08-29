"""Analytics endpoints: bottlenecks, anomalies, defect risks, predictions,
model performance, recommendations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Anomaly, ModelVersion, Prediction, Recommendation,
                      Station, Vehicle)
from ..services.bottleneck import compute_bottlenecks
from ..services.contributing_factors import (analyze_station_contributing_factors,
                                             analyze_vehicle_contributing_factors,
                                             detect_intermittent_patterns,
                                             evidence_matrix)
from ..services.observability_advisor import compute_observability_advisor
from ..services import defect_traceback, prediction_trust, shadow_sim
from .deps import get_db, get_line_or_404, get_station_or_404, get_vehicle_or_404

router = APIRouter(tags=["analytics"])


@router.get("/bottlenecks")
def bottlenecks(window_s: float | None = Query(None, description="analysis window"),
                line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return compute_bottlenecks(db, line.id, window_s=window_s)


@router.get("/observability/advisor")
def observability_advisor(line_id: int | None = None, db: Session = Depends(get_db)):
    """Innovation 1 — Observability Advisor: per-station instrumentation-gap
    analysis with recommended actions, projected confidence (estimated) and
    priority, so the plant can act on poor observability instead of just
    seeing it."""
    line = get_line_or_404(db, line_id)
    return compute_observability_advisor(db, line.id)


@router.get("/contributing-factors/patterns")
def contributing_patterns(line_id: int | None = None, db: Session = Depends(get_db)):
    """Innovation 2 — line-wide intermittent patterns (shift / tool-wear /
    batch / environment) from historical data, with min-sample guards."""
    line = get_line_or_404(db, line_id)
    return {"disclaimer": "Observed associations from available data; not a causal determination.",
            "patterns": detect_intermittent_patterns(db, line.id)}


@router.get("/contributing-factors/{station_ident}")
def contributing_factors_station(station_ident: str,
                                 line_id: int | None = None,
                                 db: Session = Depends(get_db)):
    """Innovation 2 — ranked likely contributing factors for an incident at a
    station (bottleneck / defect risk / degradation). station_ident is the
    station code (e.g. S17) or numeric id."""
    line = get_line_or_404(db, line_id)
    if station_ident.isdigit():
        st = get_station_or_404(db, int(station_ident))
        return analyze_station_contributing_factors(db, line.id, station_id=st.id)
    return analyze_station_contributing_factors(db, line.id, station_code=station_ident)


@router.get("/contributing-factors/vehicle/{vehicle_id}")
def contributing_factors_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    """Innovation 2 — genealogy-based contributing factors for a vehicle."""
    get_vehicle_or_404(db, vehicle_id)
    return analyze_vehicle_contributing_factors(db, vehicle_id)


@router.get("/evidence-matrix/{station_ident}")
def evidence_matrix_endpoint(station_ident: str,
                             line_id: int | None = None,
                             db: Session = Depends(get_db)):
    """Innovation 2 — factor x station evidence-strength grid around a station."""
    line = get_line_or_404(db, line_id)
    st = (get_station_or_404(db, int(station_ident)) if station_ident.isdigit()
          else db.query(Station).filter(Station.line_id == line.id,
                                        Station.code == station_ident).first())
    if not st:
        from fastapi import HTTPException
        raise HTTPException(404, f"station {station_ident} not found")
    return evidence_matrix(db, line.id, st.id)


@router.get("/anomalies")
def anomalies(severity: str | None = None, station: str | None = None,
              limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    q = (db.query(Anomaly, Station.code, Vehicle.vin)
         .join(Station, Station.id == Anomaly.station_id)
         .outerjoin(Vehicle, Vehicle.id == Anomaly.vehicle_id)
         .order_by(Anomaly.t.desc()))
    if severity:
        q = q.filter(Anomaly.severity == severity)
    if station:
        q = q.filter(Station.code == station)
    rows = q.limit(limit).all()
    return {"count": len(rows),
            "anomalies": [{"vin": vin, "station": code, "t": a.t,
                           "score": a.score, "severity": a.severity,
                           "detector": a.detector} for a, code, vin in rows]}


@router.get("/defect-risks")
def defect_risks(threshold: float = Query(0.4, ge=0, le=1),
                 limit: int = Query(50, le=500), db: Session = Depends(get_db)):
    """Vehicles with elevated predicted defect risk — the 'at-risk' board."""
    latest = (db.query(Prediction.vehicle_id, func.max(Prediction.id)
                       .label("mid")).group_by(Prediction.vehicle_id).subquery())
    q = (db.query(Prediction, Vehicle)
         .join(latest, Prediction.id == latest.c.mid)
         .join(Vehicle, Vehicle.id == Prediction.vehicle_id)
         .filter(Prediction.defect_probability >= threshold)
         .order_by(Prediction.defect_probability.desc()).limit(limit))
    out = []
    for p, v in q.all():
        out.append({"vehicle_id": v.id, "vin": v.vin, "variant": v.variant,
                    "status": v.status,
                    "defect_probability": round(p.defect_probability, 3),
                    "confidence": round(p.confidence, 3),
                    "data_completeness": p.data_completeness,
                    "top_features": p.top_features[:3],
                    "outcome": p.outcome, "correct": p.correct})
    return {"threshold": threshold, "count": len(out), "vehicles": out}


@router.get("/predictions")
def predictions(vehicle_id: int | None = None, resolved_only: bool = False,
                limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    q = db.query(Prediction).order_by(Prediction.created_at.desc())
    if vehicle_id:
        q = q.filter(Prediction.vehicle_id == vehicle_id)
    if resolved_only:
        q = q.filter(Prediction.outcome.isnot(None))
    rows = q.limit(limit).all()
    return {"count": len(rows),
            "predictions": [{
                "id": p.id, "vehicle_id": p.vehicle_id, "created_at": p.created_at,
                "defect_probability": p.defect_probability, "confidence": p.confidence,
                "data_completeness": p.data_completeness,
                "model_version_id": p.model_version_id,
                "outcome": p.outcome, "correct": p.correct,
                "top_features": p.top_features[:3]} for p in rows]}


@router.get("/model-performance")
def model_performance(db: Session = Depends(get_db)):
    versions = (db.query(ModelVersion).order_by(ModelVersion.id.desc()).limit(5).all())
    latest_mv = next((m for m in versions if m.name == "defect_risk"), None)
    q_res = db.query(Prediction).filter(Prediction.outcome.isnot(None))
    if latest_mv:
        q_res = q_res.filter(Prediction.model_version_id == latest_mv.id)
    resolved = q_res.all()
    live: dict = {}
    if resolved:
        thr_by_mv = {m.id: m.metrics.get("decision_threshold", 0.5) for m in versions}
        def _flag(p): return p.defect_probability >= thr_by_mv.get(p.model_version_id, 0.5)
        tp = sum(1 for p in resolved if _flag(p) and p.outcome)
        fp = sum(1 for p in resolved if _flag(p) and not p.outcome)
        fn = sum(1 for p in resolved if not _flag(p) and p.outcome)
        tn = len(resolved) - tp - fp - fn
        live = {
            "resolved": len(resolved),
            "precision": round(tp / max(tp + fp, 1), 3),
            "recall": round(tp / max(tp + fn, 1), 3),
            "fpr": round(fp / max(fp + tn, 1), 3),
            "fnr": round(fn / max(fn + tp, 1), 3),
            "note": "live metrics on outcome-resolved predictions (trust loop)",
        }
    return {
        "registered_models": [{
            "id": m.id, "name": m.name, "algo": m.algo, "version": m.version,
            "trained_at": m.trained_at, "metrics": m.metrics} for m in versions],
        "live_prediction_metrics": live,
    }


# --- Innovation 3: Safe change validation + shadow simulation ---
@router.get("/shadow/changes")
def shadow_proposed_changes(line_id: int | None = None, db: Session = Depends(get_db)):
    """Innovation 3 — proposed-changes library, generated from the current
    line state + existing recommendations/observability advisor."""
    line = get_line_or_404(db, line_id)
    return shadow_sim.proposed_changes(db, line.id)


@router.get("/shadow/windows")
def shadow_windows(line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return shadow_sim.maintenance_windows(db, line.id)


@router.get("/shadow/scenarios")
def shadow_scenarios(line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return shadow_sim.scenario_history(db, line.id)


@router.post("/shadow/scenarios")
def shadow_create_scenario(payload: dict, line_id: int | None = None,
                           db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    try:
        return shadow_sim.create_scenario(db, line.id, payload.get("changes", []))
    except ValueError as e:
        return {"error": str(e)}


@router.get("/shadow/scenarios/{scenario_id}")
def shadow_scenario_detail(scenario_id: int, db: Session = Depends(get_db)):
    try:
        return shadow_sim.scenario_view(db, scenario_id)
    except ValueError as e:
        return {"error": str(e)}


@router.post("/shadow/scenarios/{scenario_id}/run")
def shadow_run(scenario_id: int, db: Session = Depends(get_db)):
    try:
        return shadow_sim.run_shadow(db, scenario_id)
    except ValueError as e:
        return {"error": str(e)}


@router.post("/shadow/scenarios/{scenario_id}/status")
def shadow_status(scenario_id: int, payload: dict, db: Session = Depends(get_db)):
    try:
        return shadow_sim.set_scenario_status(db, scenario_id, payload.get("status", "complete"))
    except ValueError as e:
        return {"error": str(e)}


@router.post("/shadow/scenarios/{scenario_id}/queue")
def shadow_queue(scenario_id: int, payload: dict, db: Session = Depends(get_db)):
    """Queue the scenario's changes for the next maintenance window.
    HIGH simulated risk requires explicit acknowledgement (human approval)."""
    try:
        return shadow_sim.queue_for_maintenance(
            db, scenario_id, acknowledge=payload.get("acknowledge", True))
    except ValueError as e:
        return {"error": str(e)}


@router.get("/shadow/queue")
def shadow_queue_view(line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return shadow_sim.maintenance_queue(db, line.id)


# --- Innovation 4: Defect traceback & propagation analysis ---
@router.get("/defects")
def defects_list(limit: int = Query(30, le=200), vehicle_id: int | None = None,
                 line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return defect_traceback.list_defects(db, line.id, limit=limit, vehicle_id=vehicle_id)


@router.get("/defects/{defect_id}/trace")
def defect_trace(defect_id: int, db: Session = Depends(get_db)):
    """Innovation 4 — trace a detected defect backward to suspected origins,
    forward to potentially exposed units, and derive propagation risk +
    containment recommendations (observed associations, never confirmed root cause)."""
    return defect_traceback.trace_defect(db, defect_id)


# --- Innovation 5: Prediction validation & AI trust ---
@router.get("/predictions/trust")
def prediction_trust_view(line_id: int | None = None, db: Session = Depends(get_db)):
    """Innovation 5 — validated-prediction metrics, station-level trust,
    false-alarm monitor, and the production/candidate model lifecycle."""
    line = get_line_or_404(db, line_id)
    return prediction_trust.compute_prediction_trust(db, line.id)


@router.post("/predictions/trust/retrain")
def prediction_retrain_view(line_id: int | None = None, db: Session = Depends(get_db)):
    """Create a CANDIDATE model by revalidating on the validated-outcome corpus.
    Production is never changed here."""
    line = get_line_or_404(db, line_id)
    return prediction_trust.retrain_candidate(db, line.id)


@router.post("/predictions/trust/approve")
def prediction_approve_view(payload: dict, line_id: int | None = None,
                            db: Session = Depends(get_db)):
    """Human approval for the candidate model. Approval schedules deployment
    via the existing maintenance-window workflow; rejection retires the candidate."""
    line = get_line_or_404(db, line_id)
    return prediction_trust.approve_candidate(db, line.id, approve=payload.get("approve", False))


@router.post("/predictions/trust/deploy")
def prediction_deploy_view(line_id: int | None = None, db: Session = Depends(get_db)):
    """Simulate maintenance-window execution: promote the approved candidate
    to production (controlled deployment)."""
    line = get_line_or_404(db, line_id)
    return prediction_trust.deploy_candidate(db, line.id)


@router.get("/recommendations")
def recommendations(severity: str | None = None, limit: int = Query(50, le=500),
                    db: Session = Depends(get_db)):
    q = db.query(Recommendation).order_by(Recommendation.id.desc())
    if severity:
        q = q.filter(Recommendation.severity == severity)
    rows = q.limit(limit).all()
    return {"mode": "advisory-only (read-only / shadow-mode twin)",
            "count": len(rows),
            "recommendations": [{
                "id": r.id, "scope": r.scope, "ref": r.ref_code, "issue": r.issue,
                "action": r.action, "severity": r.severity,
                "confidence": r.confidence, "evidence": r.evidence} for r in rows]}
