"""Topology + observability endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (DataQualityMetric, Recommendation, Sensor, SensorReading,
                      Station, StationKpi, StationType, Vehicle, VehicleEvent)
from ..services import bottleneck as bn_service
from ..services import data_quality as dq_service
from ..services import twin_state
from .deps import get_db, get_line_or_404, get_station_or_404

router = APIRouter(tags=["meta"])


@router.get("/plants")
def list_plants(db: Session = Depends(get_db)):
    from ..models import Plant
    plants = db.query(Plant).all()
    return [{"id": p.id, "code": p.code, "name": p.name, "industry": p.industry}
            for p in plants]


@router.get("/lines")
def list_lines(db: Session = Depends(get_db)):
    lines = db.query(type(get_line_or_404(db, None))).all()
    return [{"id": l.id, "code": l.code, "name": l.name, "plant_id": l.plant_id,
             "takt_seconds": l.takt_seconds, "scenario": l.scenario,
             "stations": db.query(func.count(Station.id)).filter_by(line_id=l.id).scalar()}
            for l in lines]


@router.get("/stations")
def list_stations(line_id: int | None = None, db: Session = Depends(get_db)):
    """Line board snapshot: current state of every station (supervisor view
    backbone + base layer for the other personas)."""
    line = get_line_or_404(db, line_id)
    return {"line": {"id": line.id, "name": line.name, "scenario": line.scenario},
            "sim_time": twin_state.last_sim_time(db),
            "stations": twin_state.station_snapshots(db, line.id)}


@router.get("/stations/{station_id}")
def station_detail(station_id: int, db: Session = Depends(get_db)):
    st = get_station_or_404(db, station_id)
    st_type = db.get(StationType, st.type_id)
    sensors = db.query(Sensor).filter_by(station_id=st.id).all()
    latest_kpi = (db.query(StationKpi).filter_by(station_id=st.id)
                  .order_by(StationKpi.t.desc()).first())
    # recent reading stats per sensor (last 500 aggregates)
    reading_rows = (db.query(SensorReading.sensor_name,
                             func.avg(SensorReading.mean), func.avg(SensorReading.std),
                             func.max(SensorReading.max), func.count())
                    .filter_by(station_id=st.id)
                    .group_by(SensorReading.sensor_name).all())
    dq = (db.query(DataQualityMetric).filter_by(station_id=st.id)
          .order_by(DataQualityMetric.id.desc()).first())
    recent = (db.query(VehicleEvent, Vehicle.vin)
              .join(Vehicle, Vehicle.id == VehicleEvent.vehicle_id)
              .filter(VehicleEvent.station_id == st.id)
              .order_by(VehicleEvent.exited_at.desc()).limit(15).all())
    ranking = bn_service.compute_bottlenecks(db, st.line_id)["ranking"]
    bn_row = next((r for r in ranking if r["station_id"] == st.id), None)
    recs = (db.query(Recommendation).filter_by(ref_code=st.code)
            .order_by(Recommendation.id.desc()).limit(5).all())
    return {
        "id": st.id, "seq": st.seq, "code": st.code, "zone": st.zone,
        "archetype": st_type.code if st_type else None,
        "sensor_profile": st.sensor_profile, "capacity": st.capacity,
        "is_inspection": st.is_inspection,
        "baseline": {"cycle_mu": st.baseline_cycle_mu, "cycle_sigma": st.baseline_cycle_sigma},
        "sensors": [{"name": s.name, "unit": s.unit, "status": s.status} for s in sensors],
        "current": {"queue_len": latest_kpi.queue_len if latest_kpi else 0,
                    "utilization": latest_kpi.utilization if latest_kpi else 0,
                    "wear": latest_kpi.wear if latest_kpi else None},
        "sensor_stats": [{"sensor": r[0], "avg_mean": round(r[1] or 0, 3),
                          "avg_std": round(r[2] or 0, 3), "max_seen": r[3],
                          "samples": r[4]} for r in reading_rows],
        "data_quality": ({"sensor_coverage": dq.sensor_coverage,
                          "completeness": dq.completeness,
                          "freshness_s": dq.freshness_s,
                          "anomaly_rate": dq.anomaly_rate} if dq else None),
        "bottleneck": bn_row,
        "recent_events": [{"vin": vin, "exited_at": ev.exited_at,
                           "cycle_time": ev.cycle_time, "cycle_dev": ev.cycle_dev,
                           "checklist": ev.checklist_result,
                           "anomaly_score": ev.anomaly_score} for ev, vin in recent],
        "recommendations": [{"issue": r.issue, "action": r.action,
                             "severity": r.severity, "confidence": r.confidence}
                            for r in recs],
    }


@router.get("/data-quality")
def data_quality(line_id: int | None = None, recompute: bool = Query(False),
                 db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    rows = dq_service.compute_station_data_quality(db, line.id, persist=recompute)
    return {"sim_time": twin_state.last_sim_time(db), "stations": rows}
