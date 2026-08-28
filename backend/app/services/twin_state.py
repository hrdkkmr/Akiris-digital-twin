"""Twin state service — the 'digital twin' snapshot each persona view reads from.

Current state per station: queue/utilization/wear (KPI stream), data freshness,
recent anomalies, machine state derivation, and sensor coverage — all computed
from the same underlying tables (no per-persona fake pipelines).
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Anomaly, Sensor, Station, StationKpi, StationType,
                      VehicleEvent)

FULL_SENSOR_REFERENCE = 4  # torque, vibration, temperature, motor_current


def last_sim_time(db: Session) -> float:
    return db.query(func.max(StationKpi.t)).scalar() or 0.0


def station_snapshots(db: Session, line_id: int, lookback_s: float = 3600.0) -> list[dict]:
    stations = (db.query(Station).filter_by(line_id=line_id)
                .order_by(Station.seq).all())
    st_types = {t.id: t.code for t in db.query(StationType).all()}
    now = last_sim_time(db)
    since = max(0.0, now - lookback_s)

    latest_kpi = (db.query(StationKpi.station_id,
                           func.max(StationKpi.t).label("mt"))
                  .group_by(StationKpi.station_id).subquery())
    kpis = (db.query(StationKpi)
            .join(latest_kpi, (StationKpi.station_id == latest_kpi.c.station_id)
                  & (StationKpi.t == latest_kpi.c.mt)).all())
    kpi_by_station = {k.station_id: k for k in kpis}

    sensor_counts = dict(db.query(Sensor.station_id, func.count())
                         .group_by(Sensor.station_id).all())

    recent_events = (db.query(VehicleEvent.station_id, func.count())
                     .filter(VehicleEvent.exited_at >= since)
                     .group_by(VehicleEvent.station_id).all())
    recent_by_station = dict(recent_events)

    anomaly_counts = dict(db.query(Anomaly.station_id, func.count())
                          .filter(Anomaly.t >= since)
                          .group_by(Anomaly.station_id).all())

    out = []
    for st in stations:
        kpi = kpi_by_station.get(st.id)
        queue = kpi.queue_len if kpi else 0
        util = kpi.utilization if kpi else 0.0
        wear = kpi.wear if kpi else None
        anomalies = anomaly_counts.get(st.id, 0)
        n_sensors = sensor_counts.get(st.id, 0)
        coverage = round(n_sensors / FULL_SENSOR_REFERENCE, 2)

        if util >= 0.92 or queue >= 15:
            status = "critical"
        elif util >= 0.80 or anomalies > 0 or (wear or 0) > 0.6:
            status = "warning"
        else:
            status = "ok"

        out.append({
            "id": st.id, "seq": st.seq, "code": st.code, "zone": st.zone,
            "archetype": st_types.get(st.type_id), "sensor_profile": st.sensor_profile,
            "capacity": st.capacity, "is_inspection": st.is_inspection,
            "queue_len": queue, "utilization": round(util, 3),
            "wear": round(wear, 3) if wear is not None else None,
            "status": status,
            "sensor_coverage": coverage,
            "recent_anomalies": anomalies,
            "vehicles_last_hour": recent_by_station.get(st.id, 0),
            "machine_state": _machine_state(util, queue),
        })
    return out


def _machine_state(util: float, queue: int) -> str:
    if util >= 0.95:
        return "saturated"
    if util >= 0.75:
        return "busy"
    if queue >= 8:
        return "blocked"
    return "running"
