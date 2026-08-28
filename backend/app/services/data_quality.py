"""Data-quality / observability service.

Per station: sensor coverage, completeness, freshness, anomaly rate.
Explicitly distinguishes the FOUR missingness situations required by the PS:
  1. random missing readings    -> completeness < 1 on an instrumented station
  2. station without a sensor   -> coverage < 1 (sensor rows absent)
  3. sensor temporarily down    -> freshness grows (future: sensor.status='unavailable')
  4. manual-only station        -> coverage 0; checklist data governs confidence
(sensor malfunction -> future scenario injection; sensor.status='malfunction')
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Anomaly, DataQualityMetric, Sensor, SensorReading,
                      Station, VehicleEvent)
from .twin_state import FULL_SENSOR_REFERENCE, last_sim_time


def compute_station_data_quality(db: Session, line_id: int,
                                 persist: bool = True) -> list[dict]:
    now = last_sim_time(db)
    stations = db.query(Station).filter_by(line_id=line_id).all()

    sensors_by_station: dict[int, int] = dict(
        db.query(Sensor.station_id, func.count()).group_by(Sensor.station_id).all())
    visits: dict[int, int] = dict(
        db.query(VehicleEvent.station_id, func.count())
        .group_by(VehicleEvent.station_id).all())
    ok_readings: dict[int, int] = dict(
        db.query(SensorReading.station_id, func.count())
        .filter(SensorReading.status == "ok")
        .group_by(SensorReading.station_id).all())
    last_reading: dict[int, float] = dict(
        db.query(SensorReading.station_id, func.max(SensorReading.t))
        .group_by(SensorReading.station_id).all())
    n_anom: dict[int, int] = dict(
        db.query(Anomaly.station_id, func.count())
        .group_by(Anomaly.station_id).all())

    out = []
    for st in stations:
        n_sensors = sensors_by_station.get(st.id, 0)
        n_visits = visits.get(st.id, 0)
        expected = n_visits * n_sensors
        ok = ok_readings.get(st.id, 0)
        completeness = round(min(ok / expected, 1.0), 3) if expected else 1.0
        freshness = round(now - last_reading[st.id], 1) if st.id in last_reading else -1.0
        anomaly_rate = round(n_anom.get(st.id, 0) / max(n_visits, 1), 4)
        coverage = n_sensors / FULL_SENSOR_REFERENCE
        # confidence in THIS STATION'S analytics: instrumentation coverage,
        # reading completeness and freshness, penalized by anomaly density.
        fresh_score = 1.0 if 0 <= freshness <= 600 else (0.0 if freshness == -1 else 0.4)
        analytics_confidence = round(min(max(
            0.45 * coverage + 0.35 * completeness + 0.20 * fresh_score
            - 0.30 * anomaly_rate, 0.0), 1.0), 3)
        row = {
            "station_id": st.id, "code": st.code, "zone": st.zone,
            "sensor_profile": st.sensor_profile,
            "sensor_coverage": round(coverage, 2),
            "sensors_registered": n_sensors,
            "completeness": completeness,
            "freshness_s": freshness,
            "freshness": "high" if 0 <= freshness <= 600 else ("low" if freshness == -1 else "stale"),
            "anomaly_rate": anomaly_rate,
            "analytics_confidence": analytics_confidence,
            "vehicles_seen": n_visits,
        }
        out.append(row)
        if persist:
            db.add(DataQualityMetric(
                station_id=st.id, computed_at=now,
                sensor_coverage=row["sensor_coverage"], completeness=completeness,
                freshness_s=max(freshness, 0.0), anomaly_rate=anomaly_rate,
                prediction_confidence=analytics_confidence))
    if persist:
        db.commit()
    return out
