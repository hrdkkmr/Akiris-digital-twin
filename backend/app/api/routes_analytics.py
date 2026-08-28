"""Analytics endpoints: bottlenecks, anomalies, defect risks, predictions,
model performance, recommendations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Anomaly, ModelVersion, Prediction, Recommendation,
                      Station, Vehicle)
from ..services.bottleneck import compute_bottlenecks
from .deps import get_db, get_line_or_404

router = APIRouter(tags=["analytics"])


@router.get("/bottlenecks")
def bottlenecks(window_s: float | None = Query(None, description="analysis window"),
                line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return compute_bottlenecks(db, line.id, window_s=window_s)


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
