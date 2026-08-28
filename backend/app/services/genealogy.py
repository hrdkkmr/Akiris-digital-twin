"""Genealogy (digital thread) + root-cause ranking.

Epistemics rule (from the PS and our design docs): contribution scores are
'likely contributing factors' derived from anomaly magnitudes and deviations —
NOT causal proof. Ground truth stays behind include_truth (judge/validation mode).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (Defect, Inspection, SensorReading, Station, StationType,
                      Vehicle, VehicleEvent)

CAVEAT = ("Contribution scores rank evidence correlation, not causal proof. "
          "Confirmed causality requires engineering investigation.")


def vehicle_journey(db: Session, vehicle_id: int, include_truth: bool = False) -> dict | None:
    veh = db.get(Vehicle, vehicle_id)
    if not veh:
        return None
    st_types = {t.id: t.code for t in db.query(StationType).all()}
    rows = (db.query(VehicleEvent, Station)
            .join(Station, Station.id == VehicleEvent.station_id)
            .filter(VehicleEvent.vehicle_id == vehicle_id)
            .order_by(VehicleEvent.entered_at).all())

    readings = (db.query(SensorReading)
                .filter(SensorReading.vehicle_id == vehicle_id).all())
    readings_by_station: dict[int, dict] = {}
    for r in readings:
        readings_by_station.setdefault(r.station_id, {})[r.sensor_name] = {
            "mean": round(r.mean or 0, 3), "std": round(r.std or 0, 3),
            "min": r.min, "max": r.max, "unit": r.unit, "status": r.status}

    inspections = (db.query(Inspection)
                   .filter(Inspection.vehicle_id == vehicle_id).all())
    defect = (db.query(Defect)
              .filter(Defect.vehicle_id == vehicle_id).first())
    defect_station = defect.station_id if defect else None

    steps = []
    for ev, st in rows:
        steps.append({
            "seq": st.seq, "station": st.code, "zone": st.zone,
            "archetype": st_types.get(st.type_id),
            "entered_at": ev.entered_at, "exited_at": ev.exited_at,
            "cycle_time": ev.cycle_time, "cycle_dev": ev.cycle_dev,
            "anomaly_score": ev.anomaly_score,
            "checklist": ev.checklist_result,
            "inspection": ("fail" if st.id == defect_station else ev.inspection_result),
            "sensors": readings_by_station.get(st.id, {}),
            **({"internal_flags_truth": ev.internal_flags} if include_truth else {}),
        })
    return {
        "vehicle": {
            "id": veh.id, "vin": veh.vin, "variant": veh.variant,
            "batch_id": veh.batch_id, "status": veh.status,
            "started_at": veh.started_at, "completed_at": veh.completed_at,
            "quality_score": veh.quality_score,
        },
        "steps": steps,
        "outcome": {
            "status": veh.status,
            "defect_found_at": (db.get(Station, defect_station).code
                                if defect_station else None),
            "true_root_causes": defect.true_root_causes if (defect and include_truth) else None,
        },
    }


def root_cause_candidates(db: Session, vehicle_id: int, top_k: int = 5) -> dict:
    """Rank likely contributing stations/factors for a vehicle's defect."""
    journey = vehicle_journey(db, vehicle_id, include_truth=False)
    if not journey:
        return {"candidates": [], "caveat": CAVEAT}
    steps = journey["steps"]

    scored = []
    for s in steps:
        reasons = []
        score = 0.0
        if s["anomaly_score"] is not None:
            score += 0.45 * min(s["anomaly_score"], 1.0)
            if s["anomaly_score"] > 0.7:
                reasons.append("anomalous sensor signature")
        if s["cycle_dev"] is not None:
            dev_ratio = min(abs(s["cycle_dev"]) / 10.0, 1.0)
            score += 0.30 * dev_ratio
            if abs(s["cycle_dev"]) > 4:
                reasons.append(f"cycle time {s['cycle_dev']:+.1f}s vs baseline")
        sensors = s.get("sensors", {})
        if "torque" in sensors and sensors["torque"]["std"] > 2.5:
            score += 0.15
            reasons.append(f"torque instability (σ={sensors['torque']['std']:.2f} Nm)")
        if "vibration" in sensors and sensors["vibration"]["mean"] > 2.6:
            score += 0.15
            reasons.append(f"elevated vibration (μ={sensors['vibration']['mean']:.2f} mm/s)")
        if s["checklist"] == "NOK":
            score += 0.10
            reasons.append("manual check reported NOK")
        if score > 0:
            scored.append({"station": s["station"], "zone": s["zone"],
                           "type": "station_evidence", "raw": score,
                           "evidence": reasons[:3] or ["weak statistical signal"]})

    # batch-level evidence: sibling vehicles from same supplier batch also failing
    veh = db.get(Vehicle, vehicle_id)
    if veh:
        siblings = (db.query(Vehicle)
                    .filter(Vehicle.batch_id == veh.batch_id,
                            Vehicle.status == "scrapped",
                            Vehicle.id != vehicle_id).count())
        if siblings >= 2:
            scored.append({"station": None, "zone": None, "type": "batch_evidence",
                           "raw": 0.20 + 0.05 * siblings,
                           "evidence": [f"{siblings} other vehicles from same batch scrapped"]})

    total = sum(c["raw"] for c in scored) or 1.0
    ranked = sorted(scored, key=lambda c: -c["raw"])[:top_k]
    for c in ranked:
        c["contribution"] = round(c["raw"] / total, 3)
        del c["raw"]

    return {"vehicle": journey["vehicle"]["vin"],
            "outcome_station": journey["outcome"]["defect_found_at"],
            "language": "Likely contributing factors",
            "candidates": ranked, "caveat": CAVEAT}
