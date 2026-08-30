"""Recommendation engine — advisory only (read-only / shadow-mode twin).

Rules map evidence -> action. Every recommendation carries evidence, severity
and confidence; none issues control commands. Retrofit-type actions are framed
for scheduled maintenance windows (PS complexity #3).
"""
from __future__ import annotations

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from ..models import (Defect, Recommendation, Sensor, SensorReading, Station,
                      StationKpi, Vehicle, VehicleEvent)
from .bottleneck import compute_bottlenecks
from .twin_state import last_sim_time


def _add(db: Session, now: float, scope: str, ref: str, issue: str,
         action: str, severity: str, confidence: float, evidence: dict,
         line_id: int | None = None) -> None:
    db.add(Recommendation(line_id=line_id, created_at=now, scope=scope, ref_code=ref,
                          issue=issue, action=action, severity=severity,
                          confidence=confidence, evidence=evidence, status="advisory"))


def generate_recommendations(db: Session, line_id: int, replace: bool = True) -> int:
    if replace:
        # per-line replace: a multi-factory twin must not delete another
        # factory's advisories when one line refreshes
        db.query(Recommendation).filter(Recommendation.line_id == line_id).delete()
    now = last_sim_time(db)
    stations = {s.id: s for s in db.query(Station).filter_by(line_id=line_id).all()}
    count = 0

    # 1) bottleneck advisories (top-2 critical/high)
    bn = compute_bottlenecks(db, line_id)
    for r in bn["ranking"][:2]:
        if r["status"] in ("critical", "high"):
            _add(db, now, "station", r["code"],
                 issue=f"Station {r['code']} is the line bottleneck (score {r['score']})",
                 action=(f"Review cycle-time distribution and buffering at {r['code']}; "
                         "consider rebalancing work content in the next maintenance window."),
                 severity="high" if r["status"] == "critical" else "medium",
                 confidence=r["confidence"], evidence=r["evidence"], line_id=line_id)
            count += 1

    # 2) tool-wear advisories (per line)
    wear_rows = (db.query(StationKpi.station_id, func.max(StationKpi.wear))
                 .join(Station, Station.id == StationKpi.station_id)
                 .filter(Station.line_id == line_id, StationKpi.wear.isnot(None))
                 .group_by(StationKpi.station_id).all())
    for sid, w in wear_rows:
        if w and w > 0.55:
            code = stations[sid].code
            _add(db, now, "station", code,
                 issue=f"Tool wear at {code} trending high ({w:.2f})",
                 action=("Inspect fastening/welding tool; schedule tool service in the "
                         "next planned maintenance window (no live-line intervention)."),
                 severity="medium", confidence=0.85, evidence={"wear": round(w, 3)}, line_id=line_id)
            count += 1

    # 3) torque instability (fastening/torque stations, per line)
    torque = (db.query(SensorReading.station_id,
                       func.avg(SensorReading.std).label("s"),
                       func.avg(SensorReading.mean).label("m"))
              .join(Station, Station.id == SensorReading.station_id)
              .filter(Station.line_id == line_id,
                      SensorReading.sensor_name == "torque")
              .group_by(SensorReading.station_id).all())
    for sid, s_std, s_mean in torque:
        if s_std and s_std > 3.0:
            code = stations[sid].code
            _add(db, now, "station", code,
                 issue=f"Torque instability at {code} (σ={s_std:.2f} Nm)",
                 action="Inspect torque/fastening tool calibration and fixturing.",
                 severity="medium", confidence=0.8,
                 evidence={"torque_std": round(s_std, 3), "torque_mean": round(s_mean, 2)}, line_id=line_id)
            count += 1

    # 4) batch-cluster defects (per line)
    batch_rows = (db.query(Vehicle.batch_id, func.count())
                  .filter(Vehicle.line_id == line_id,
                          Vehicle.status == "scrapped")
                  .group_by(Vehicle.batch_id).all())
    for batch_id, n in batch_rows:
        if n >= 2:
            _add(db, now, "batch", f"BATCH-{batch_id}",
                 issue=f"{n} vehicles from one supplier batch were scrapped",
                 action=("Quarantine and inspect remaining incoming components from this "
                         "batch; notify supplier quality."),
                 severity="high", confidence=0.9, evidence={"scrapped_in_batch": n}, line_id=line_id)
            count += 1

    # 5) data-gap advisories (instrumented but incomplete, per line)
    expected = (db.query(VehicleEvent.station_id, func.count())
                .join(Station, Station.id == VehicleEvent.station_id)
                .filter(Station.line_id == line_id)
                .group_by(VehicleEvent.station_id).all())
    ok = dict(db.query(SensorReading.station_id, func.count())
              .join(Station, Station.id == SensorReading.station_id)
              .filter(Station.line_id == line_id)
              .group_by(SensorReading.station_id).all())
    sensors_n = dict(db.query(Station.id, func.count())
                     .filter(Station.line_id == line_id)
                     .join(Sensor, Sensor.station_id == Station.id)
                     .group_by(Station.id).all())
    for sid, visits in expected:
        n_sensors = sensors_n.get(sid, 0)
        if n_sensors:
            completeness = ok.get(sid, 0) / max(visits * n_sensors, 1)
            if completeness < 0.75:
                code = stations[sid].code
                _add(db, now, "station", code,
                     issue=f"Prediction confidence limited at {code}: data gaps ({completeness:.0%} complete)",
                     action="Investigate sensor telemetry dropouts; consider edge-gateway diagnostics.",
                     severity="low", confidence=0.95,
                     evidence={"completeness": round(completeness, 3)}, line_id=line_id)
                count += 1

    # 6) manual-process variation (per line)
    nok = (db.query(VehicleEvent.station_id,
                    func.sum((VehicleEvent.checklist_result == "NOK").cast(Integer)).label("nok"),
                    func.count().label("n"))
           .join(Station, Station.id == VehicleEvent.station_id)
           .filter(Station.line_id == line_id,
                   VehicleEvent.checklist_result.isnot(None))
           .group_by(VehicleEvent.station_id).all())
    for sid, n_nok, n in nok:
        if n and n_nok / n > 0.03:
            code = stations[sid].code
            _add(db, now, "station", code,
                 issue=f"Manual checks failing at {code} ({n_nok}/{n} NOK)",
                 action="Review manual process variation, fixturing aids and operator instructions.",
                 severity="medium", confidence=0.75,
                 evidence={"nok_rate": round(n_nok / n, 4)}, line_id=line_id)
            count += 1

    db.commit()
    return count
