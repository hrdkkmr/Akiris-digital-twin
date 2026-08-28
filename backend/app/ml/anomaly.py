"""Anomaly detection — IsolationForest per sensor profile (stations with the
same instrumentation learn together). Scores are min-max normalized per profile
onto 0..1; threshold = 97th percentile of the training (early-shift) window.

Writes: anomalies rows + vehicle_events.anomaly_score (drives genealogy
highlighting and root-cause evidence).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from ..models import Anomaly, SensorReading, Station, VehicleEvent

FEATURE_MAP = {"mean": "m", "std": "s"}
STAT_COLS = ["cycle_dev"] + [f"{sen}_{ agg}" for sen in
                             ("torque", "vibration", "temperature", "motor_current")
                             for agg in ("m", "s")]


def _frame(db: Session, line_id: int) -> pd.DataFrame:
    stations = pd.read_sql(db.query(Station.id.label("station_id"),
                                    Station.sensor_profile,
                                    Station.code)
                           .filter(Station.line_id == line_id).statement, db.bind)
    ev = pd.read_sql(db.query(VehicleEvent.id, VehicleEvent.vehicle_id,
                              VehicleEvent.station_id, VehicleEvent.exited_at,
                              VehicleEvent.cycle_dev).statement, db.bind)
    rd = pd.read_sql(db.query(SensorReading.vehicle_id, SensorReading.station_id,
                              SensorReading.sensor_name, SensorReading.mean,
                              SensorReading.std)
                     .filter(SensorReading.status == "ok").statement, db.bind)
    if ev.empty or rd.empty:
        return pd.DataFrame()
    wide = rd.pivot_table(index=["vehicle_id", "station_id"],
                          columns="sensor_name", values=["mean", "std"],
                          aggfunc="first")
    wide.columns = [f"{sen}_{FEATURE_MAP[stat]}" for stat, sen in wide.columns]
    df = ev.merge(wide.reset_index(), on=["vehicle_id", "station_id"], how="left") \
           .merge(stations, on="station_id")
    for c in STAT_COLS:
        if c not in df.columns:
            df[c] = np.nan
    return df


def detect_anomalies(db: Session, line_id: int) -> dict:
    df = _frame(db, line_id)
    if df.empty:
        return {"error": "no scorable records"}
    df = df.sort_values("exited_at")
    df["anomaly"] = np.nan
    db.query(Anomaly).delete()
    summary: dict[str, dict] = {}
    inserts: list[dict] = []

    for profile, grp in df.groupby("sensor_profile"):
        if profile in ("sparse", "manual") or len(grp) < 200:
            continue
        X = grp[STAT_COLS]
        med = X.median(numeric_only=True)
        mad = (X - med).abs().median(numeric_only=True).replace(0, 1e-9)
        Z = ((X - med) / mad).clip(-8, 8).fillna(0.0)

        cut = int(len(grp) * 0.6)
        iso = IsolationForest(n_estimators=200, contamination=0.02,
                              random_state=42, n_jobs=-1).fit(Z.iloc[:cut])
        raw = -iso.score_samples(Z)
        r_train = raw[:cut]
        lo, hi = np.min(r_train), np.max(r_train)
        score = np.clip((raw - lo) / max(hi - lo, 1e-9), 0, 1)
        thr = float(np.quantile(score[:cut], 0.99))   # alert-fatigue control
        df.loc[grp.index, "anomaly"] = score
        flagged = grp.index[score > thr]
        summary[profile] = {"records": int(len(grp)), "threshold": round(thr, 3),
                            "flagged": int(len(flagged))}
        for idx in flagged:
            row = grp.loc[idx]
            sc = float(df.loc[idx, "anomaly"])
            inserts.append({
                "vehicle_id": int(row.vehicle_id), "station_id": int(row.station_id),
                "t": float(row.exited_at or 0.0), "detector": "isolation_forest",
                "score": round(sc, 4),
                "severity": "high" if sc > 0.995 else "medium",
                "features": {c: (None if pd.isna(row[c]) else round(float(row[c]), 3))
                             for c in STAT_COLS},
            })

    if inserts:
        for i in range(0, len(inserts), 2000):
            db.bulk_insert_mappings(Anomaly, inserts[i:i + 2000])
    scored = df.dropna(subset=["anomaly"])
    updates = [{"id": int(r.id), "anomaly_score": round(float(r.anomaly), 4)}
               for r in scored.itertuples()]
    from sqlalchemy import update
    for i in range(0, len(updates), 2000):
        db.execute(update(VehicleEvent), updates[i:i + 2000])
    db.commit()
    return {"profiles": summary, "anomalies_written": len(inserts),
            "events_scored": len(updates)}
