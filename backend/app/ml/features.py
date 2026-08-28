"""Feature engineering for defect-risk prediction.

Scope decision (leakage-safe by construction):
  Prediction happens at END OF PAINT (configurable zone), using ONLY information
  available up to that point. Label = failure at a LATER (final-zone) inspection.
  Simulator ground-truth mechanism flags are NEVER used as features.
Sparse-instrumentation handling: per-sensor availability indicators + median
imputation (fit on train split only, carried with the artifact).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..models import (Defect, EnvironmentSample, Sensor, SensorReading,
                      Station, StationKpi, Vehicle, VehicleEvent)

PREDICT_AFTER_ZONE = "paint"          # predict when the vehicle leaves paint
SENSORS = ["torque", "vibration", "temperature", "motor_current"]


def _station_maps(db: Session, line_id: int) -> tuple[dict, dict, int]:
    stations = db.query(Station).filter_by(line_id=line_id).all()
    seq = {s.id: s.seq for s in stations}
    as_of_seq = max(s.seq for s in stations if s.zone == PREDICT_AFTER_ZONE)
    n_sensors = dict(db.query(Sensor.station_id, Sensor.name)
                     .all())
    sensors_per_station: dict[int, int] = {}
    for sid, _ in n_sensors.items():
        sensors_per_station[sid] = sensors_per_station.get(sid, 0) + 1
    return seq, sensors_per_station, as_of_seq


def build_vehicle_frame(db: Session, line_id: int) -> tuple[pd.DataFrame, dict]:
    seq, sensors_per_station, as_of_seq = _station_maps(db, line_id)

    vehicles = pd.read_sql(
        db.query(Vehicle).filter(Vehicle.line_id == line_id).statement, db.bind)
    events = pd.read_sql(
        db.query(VehicleEvent).statement, db.bind)
    if vehicles.empty or events.empty:
        return pd.DataFrame(), {"as_of_seq": as_of_seq}

    events["seq"] = events.station_id.map(seq)
    readings = pd.read_sql(db.query(SensorReading)
                           .filter(SensorReading.status == "ok").statement, db.bind)
    if not readings.empty:
        readings["seq"] = readings.station_id.map(seq)

    defects = pd.read_sql(db.query(Defect).statement, db.bind)
    defects["seq"] = defects.station_id.map(seq) if not defects.empty else []

    reached = set(events.loc[events.seq > as_of_seq, "vehicle_id"])
    cand = vehicles[vehicles.id.isin(reached)].copy()
    if cand.empty:
        return pd.DataFrame(), {"as_of_seq": as_of_seq}

    # label: defect found strictly AFTER the as-of point
    fail_later = (defects.loc[defects.seq > as_of_seq, "vehicle_id"].unique()
                  if not defects.empty else np.array([]))
    cand["label"] = cand.id.isin(fail_later).astype(int)

    ev_pre = events[events.seq <= as_of_seq]
    g = ev_pre.groupby("vehicle_id")
    feats = pd.DataFrame({
        "n_events": g.size(),
        "mean_cycle_dev": g.cycle_dev.mean(),
        "max_cycle_dev": g.cycle_dev.max(),
        "sum_pos_cycle_dev": g.apply(lambda x: x.cycle_dev.clip(lower=0).sum(),
                                     include_groups=False),
        "n_big_dev": g.apply(lambda x: (x.cycle_dev.abs() > 4).sum(),
                             include_groups=False),
        "max_queue_seen": g.queue_seen.max(),
        "mean_queue_seen": g.queue_seen.mean(),
        "n_nok": g.checklist_result.apply(lambda s: (s == "NOK").sum()),
        "n_checklists": g.checklist_result.apply(lambda s: s.notna().sum()),
        "as_of_time": g.exited_at.max(),
    })

    # upstream anomaly pressure: count of pre-as-of events with an elevated
    # IsolationForest score (>=0.7 on the per-profile 0..1 scale — catches
    # lifts below the hard 0.99 alert threshold). Zeros before an anomaly
    # pass has run. MES-visible, leakage-safe (pre-as-of events only).
    feats["upstream_anomaly_count"] = (
        ev_pre.assign(flag=(ev_pre.anomaly_score.fillna(0.0) >= 0.7).astype(int))
              .groupby("vehicle_id").flag.sum())

    if not readings.empty:
        r_pre = readings[readings.seq <= as_of_seq]
        for sensor in SENSORS:
            rs = r_pre[r_pre.sensor_name == sensor]
            grp = rs.groupby("vehicle_id")
            feats[f"{sensor}_mean"] = grp["mean"].mean()
            feats[f"{sensor}_std_max"] = grp["std"].max()
            feats[f"{sensor}_max"] = grp["max"].max()
            feats[f"has_{sensor}"] = grp.size().gt(0).astype(int)
        # completeness: ok readings / expected over visited stations
        expected = ev_pre.assign(exp=ev_pre.station_id.map(sensors_per_station)) \
                         .groupby("vehicle_id").exp.sum()
        ok = r_pre.groupby("vehicle_id").size()
        feats["completeness"] = (ok.reindex(expected.index, fill_value=0)
                                 / expected.replace(0, np.nan)).fillna(1.0)
    else:
        feats["completeness"] = 1.0
        for sensor in SENSORS:
            feats[f"{sensor}_mean"] = np.nan
            feats[f"{sensor}_std_max"] = np.nan
            feats[f"{sensor}_max"] = np.nan
            feats[f"has_{sensor}"] = 0

    env = pd.read_sql(db.query(EnvironmentSample).order_by(EnvironmentSample.t).statement,
                      db.bind)
    cand = cand.sort_values("started_at")
    if not env.empty:
        cand = pd.merge_asof(cand, env[["t", "temp_c", "humidity"]],
                             left_on="started_at", right_on="t", direction="backward")
    else:
        cand["temp_c"], cand["humidity"] = np.nan, np.nan

    out = cand.merge(feats, left_on="id", right_index=True, how="left")
    out["shift_idx"] = (out.started_at // 28_800 % 3).astype(int)
    out = pd.get_dummies(out, columns=["variant"], prefix="variant")
    out["batch_ordinal"] = out.batch_id

    # batch quality history (MES-legal: only failures completed BEFORE this
    # vehicle's as-of time are counted — no leakage)
    scr = vehicles.loc[vehicles.status == "scrapped", ["batch_id", "completed_at"]]
    if not scr.empty and not out.empty:
        s = scr.sort_values("completed_at").copy()
        s["fail_cum"] = s.groupby("batch_id").cumcount() + 1
        tmp = out[["id", "batch_id", "as_of_time"]].sort_values("as_of_time")
        m = pd.merge_asof(tmp, s[["batch_id", "completed_at", "fail_cum"]],
                          left_on="as_of_time", right_on="completed_at", by="batch_id")
        out["batch_prior_failures"] = (m.set_index("id")["fail_cum"]
                                       .reindex(out.id).fillna(0.0).to_numpy())
    else:
        out["batch_prior_failures"] = 0.0

    # ---- twin-state context at as-of time (all MES-visible, time-safe) ----
    out = _station_state_context(db, line_id, vehicles, out)

    meta = {"as_of_seq": as_of_seq}
    return out, meta


def _asof_merge(tmp: pd.DataFrame, series: pd.DataFrame,
                value_col: str, on: str = "as_of_time") -> pd.Series:
    """merge_asof helper: value of a time-sorted series at each row's as_of_time."""
    if series.empty:
        return pd.Series(0.0, index=tmp.index)
    m = pd.merge_asof(tmp.sort_values(on), series, left_on=on,
                      right_on="t", direction="backward")
    return m.set_index("id")[value_col]


def _station_state_context(db: Session, line_id: int,
                           vehicles: pd.DataFrame, out: pd.DataFrame) -> pd.DataFrame:
    final_ids = [s.id for s in db.query(Station)
                 .filter(Station.line_id == line_id, Station.zone == "final").all()]
    tmp = out[["id", "as_of_time"]].copy()

    # (1) tool-wear trajectory of final-zone stations (KPI stream)
    wear = pd.read_sql(
        db.query(StationKpi.t, StationKpi.wear)
        .filter(StationKpi.station_id.in_(final_ids), StationKpi.wear.isnot(None))
        .order_by(StationKpi.t).statement, db.bind)
    if not wear.empty:
        wmax = (wear.groupby("t").wear.agg(["max", "mean"]).reset_index()
                .rename(columns={"max": "wear_final_max", "mean": "wear_final_mean"})
                .sort_values("t"))
        for col in ("wear_final_max", "wear_final_mean"):
            out[col] = (_asof_merge(tmp, wmax[["t", col]], col)
                        .reindex(out.id).fillna(0.0).to_numpy())
    else:
        out["wear_final_max"], out["wear_final_mean"] = 0.0, 0.0

    # (2) recent torque instability of final-zone stations (rolling 30 min)
    rq = (db.query(SensorReading.t, SensorReading.std)
          .filter(SensorReading.station_id.in_(final_ids),
                  SensorReading.sensor_name == "torque",
                  SensorReading.status == "ok")
          .order_by(SensorReading.t).statement)
    tq = pd.read_sql(rq, db.bind)
    if not tq.empty and len(tq) > 10:
        tq = tq.sort_values("t")
        tq_idx = tq.set_index(pd.to_timedelta(tq["t"], unit="s"))
        rolled = tq_idx["std"].rolling("1800s").mean()
        roll = pd.DataFrame({"t": tq["t"].to_numpy(),
                             "final_torque_std_30m": rolled.to_numpy()}).dropna()
        out["final_torque_std_30m"] = (_asof_merge(tmp, roll, "final_torque_std_30m")
                                       .reindex(out.id).fillna(0.0).to_numpy())
    else:
        out["final_torque_std_30m"] = 0.0

    # (3) recent line scrap rate (rolling 1 h) — surge-of-defects context
    done = vehicles.dropna(subset=["completed_at"])[["completed_at", "status"]] \
                   .sort_values("completed_at").copy()
    if not done.empty:
        done["fail"] = (done.status == "scrapped").astype(float)
        d_idx = done.set_index(pd.to_timedelta(done["completed_at"], unit="s"))
        rolled = d_idx["fail"].rolling("3600s").mean()
        roll = pd.DataFrame({"t": done["completed_at"].to_numpy(),
                             "recent_scrap_rate_1h": rolled.to_numpy()}).dropna()
        out["recent_scrap_rate_1h"] = (_asof_merge(tmp, roll, "recent_scrap_rate_1h")
                                       .reindex(out.id).fillna(0.0).to_numpy())
    else:
        out["recent_scrap_rate_1h"] = 0.0
    return out
