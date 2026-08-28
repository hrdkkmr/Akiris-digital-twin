"""Vehicle fleet + genealogy endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Inspection, Prediction, Station, Vehicle
from ..services.genealogy import root_cause_candidates, vehicle_journey
from .deps import get_db, get_line_or_404, get_vehicle_or_404

router = APIRouter(tags=["fleet"])


@router.get("/vehicles")
def list_vehicles(status: str | None = None, variant: str | None = None,
                  min_risk: float | None = Query(None, ge=0, le=1),
                  limit: int = Query(50, ge=1, le=500), offset: int = 0,
                  db: Session = Depends(get_db)):
    q = db.query(Vehicle).order_by(Vehicle.id.desc())
    if status:
        q = q.filter(Vehicle.status == status)
    if variant:
        q = q.filter(Vehicle.variant == variant)
    rows = []
    for v in q.offset(offset).limit(limit * 2).all():
        pred = (db.query(Prediction).filter_by(vehicle_id=v.id)
                .order_by(Prediction.created_at.desc()).first())
        if min_risk is not None and (not pred or pred.defect_probability < min_risk):
            continue
        rows.append({"id": v.id, "vin": v.vin, "variant": v.variant,
                     "batch_id": v.batch_id, "status": v.status,
                     "started_at": v.started_at, "quality_score": v.quality_score,
                     "defect_probability": (round(pred.defect_probability, 3)
                                            if pred else None),
                     "confidence": round(pred.confidence, 3) if pred else None})
        if len(rows) >= limit:
            break
    return {"count": len(rows), "vehicles": rows}


@router.get("/vehicles/{vehicle_id}/journey")
def journey(vehicle_id: int, truth: bool = Query(
        False, description="judge mode: also reveal simulator ground truth"),
        db: Session = Depends(get_db)):
    get_vehicle_or_404(db, vehicle_id)
    data = vehicle_journey(db, vehicle_id, include_truth=truth)
    if not data:
        raise HTTPException(404, "journey not found")
    return data


@router.get("/vehicles/{vehicle_id}/contributing-factors")
def contributing_factors(vehicle_id: int, db: Session = Depends(get_db)):
    """Ranked 'likely contributing factors' — evidence language, not causal claims."""
    get_vehicle_or_404(db, vehicle_id)
    return root_cause_candidates(db, vehicle_id)


@router.get("/inspections")
def list_inspections(result: str | None = None, limit: int = Query(100, le=1000),
                     offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(Inspection, Vehicle.vin, Station.code) \
          .join(Vehicle, Vehicle.id == Inspection.vehicle_id) \
          .join(Station, Station.id == Inspection.station_id) \
          .order_by(Inspection.t.desc())
    if result:
        q = q.filter(Inspection.result == result)
    rows = q.offset(offset).limit(limit).all()
    total = db.query(func.count(Inspection.id)).scalar()
    fails = db.query(func.count(Inspection.id)).filter_by(result="fail").scalar()
    return {"total": total, "fail_count": fails,
            "inspections": [{"vin": vin, "station": code, "t": i.t, "result": i.result,
                             "defect_id": i.defect_id} for i, vin, code in rows]}
