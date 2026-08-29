"""Defect traceback & propagation analysis (Innovation 4).

Extends the existing vehicle genealogy: when a defect is detected at a
downstream inspection, trace BACKWARD through the vehicle's actual
production path to rank *suspected* origin/exposure points, identify the
production window during which abnormal conditions occurred, trace FORWARD
to the units that were *potentially exposed*, detect common conditions, and
estimate propagation risk with containment recommendations.

Epistemics (same rule as everywhere else in TwinLine): these are observed
associations / suspected origins from available data — never a confirmed
root cause. Ground-truth flags exist in the simulator only for evaluation
and are never used by this analysis.

Terminology: SUSPECTED ORIGIN / POTENTIAL EXPOSURE / LIKELY SOURCE /
OBSERVED ASSOCIATION / CONTRIBUTING EVIDENCE.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Anomaly, Defect, EnvironmentSample, Station, StationKpi,
                      StationType, Vehicle, VehicleEvent, ProductionBatch)
from .data_quality import compute_station_data_quality
from .genealogy import vehicle_journey
from .twin_state import last_sim_time

TRACE_CAVEAT = ("Suspected origins and potential exposures are observed "
                "associations from available data — not a confirmed root "
                "cause. A unit being potentially exposed does NOT mean it "
                "is defective.")
RISK_NOTE = "Digital twin propagation-risk estimate (not a certified safety/quality score)."

SHIFT_SECONDS = 8 * 3600.0


def _shift(t: float) -> str:
    return "ABC"[int(t // SHIFT_SECONDS) % 3]


def _strength(score: float) -> str:
    return "strong" if score >= 0.5 else "moderate" if score >= 0.25 else "weak"


def list_defects(db: Session, line_id: int, limit: int = 30,
                 vehicle_id: int | None = None) -> dict:
    q = (db.query(Defect, Vehicle.vin, Station.code)
         .join(Vehicle, Vehicle.id == Defect.vehicle_id)
         .join(Station, Station.id == Defect.station_id)
         .order_by(Defect.t.desc()))
    if vehicle_id is not None:
        q = q.filter(Defect.vehicle_id == vehicle_id)
    rows = q.limit(limit).all()
    return {"count": len(rows),
            "defects": [{"id": d.id, "vehicle_id": d.vehicle_id, "vin": vin,
                         "station": code, "t": d.t, "severity": d.severity}
                        for d, vin, code in rows]}


def _station_evidence(db: Session, station: Station, veh: Vehicle,
                      journey_steps: list[dict], detection_t: float) -> tuple[float, list[str]]:
    """Score one upstream station as a suspected origin for this vehicle's
    defect. Returns (evidence_score 0..1, evidence_strings)."""
    step = next((s for s in journey_steps if s["station"] == station.code), None)
    ev: list[str] = []
    score = 0.0

    if step is None:
        return 0.0, ["Vehicle did not pass through this station."]
    pass_t = float(step["entered_at"])

    # 1) per-vehicle anomaly at the pass
    anom = step.get("anomaly_score") or 0.0
    if anom > 0.6:
        score += 0.3
        ev.append(f"Anomaly score {anom:.2f} recorded when this vehicle passed {station.code}.")
    elif anom > 0.3:
        score += 0.12
        ev.append(f"Elevated anomaly score {anom:.2f} at this pass.")

    # 2) cycle deviation
    cdev = abs(step.get("cycle_dev") or 0.0)
    if cdev > 8:
        score += 0.2
        ev.append(f"Cycle time deviated {step['cycle_dev']:+.1f}s from baseline at {station.code}.")
    elif cdev > 4:
        score += 0.1
        ev.append(f"Mild cycle deviation {step['cycle_dev']:+.1f}s.")

    # 3) tool wear around the pass time (station KPI snapshots)
    if station.has_tool:
        kpi = (db.query(StationKpi)
               .filter(StationKpi.station_id == station.id,
                       StationKpi.t <= pass_t + 60)
               .order_by(StationKpi.t.desc()).first())
        if kpi and kpi.wear:
            if kpi.wear > 0.8:
                score += 0.25
                ev.append(f"Tool wear was {kpi.wear*100:.0f}% at {station.code} when this vehicle passed.")
            elif kpi.wear > 0.55:
                score += 0.1
                ev.append(f"Tool wear elevated ({kpi.wear*100:.0f}%) in this period.")

    # 4) station-level anomalies near the pass (abnormal period)
    n_anom = (db.query(func.count(Anomaly.id))
              .filter(Anomaly.station_id == station.id,
                      Anomaly.t.between(pass_t - 1800, pass_t + 600)).scalar() or 0)
    if n_anom >= 3:
        score += 0.2
        ev.append(f"{n_anom} station anomalies around the time this vehicle was at {station.code}.")
    elif n_anom >= 1:
        score += 0.08

    # 5) supplier batch association (batch incidence overall)
    batch = db.get(ProductionBatch, veh.batch_id)
    if batch:
        in_batch = db.query(func.count(Vehicle.id)).filter(Vehicle.batch_id == batch.id).scalar() or 0
        scrap_in_batch = (db.query(func.count(Vehicle.id))
                          .filter(Vehicle.batch_id == batch.id, Vehicle.status == "scrapped").scalar() or 0)
        if in_batch >= 3 and scrap_in_batch / in_batch >= 0.15:
            score += 0.15
            ev.append(f"Vehicle is from batch {batch.code} — {scrap_in_batch}/{in_batch} "
                      f"scrapped ({scrap_in_batch/in_batch*100:.0f}% incidence).")

    # 6) environment (temp/humidity) around the pass
    env = (db.query(EnvironmentSample)
           .filter(EnvironmentSample.t <= pass_t + 120)
           .order_by(EnvironmentSample.t.desc()).first())
    if env and (env.temp_c > 30 or env.humidity > 65):
        score += 0.1
        ev.append(f"Ambient {env.temp_c:.0f}°C / RH {env.humidity:.0f}% at pass time "
                  "(outside comfort band).")
    elif env:
        score += 0.03
        ev.append(f"Ambient {env.temp_c:.0f}°C / RH {env.humidity:.0f}% at pass time.")

    return min(score, 1.0), ev


def _exposure_window(db: Session, station: Station, pass_t: float,
                     detection_t: float) -> tuple[float, float, str, list[str]]:
    """Derive the suspected exposure window for a station from actual
    abnormal-condition timestamps (anomalies, high wear, high utilization).
    Falls back to station activity bounds when signals are sparse."""
    lo = pass_t - 3600.0
    hi = detection_t
    abnormal: list[float] = []

    anom_ts = [t for (t,) in (db.query(Anomaly.t)
                               .filter(Anomaly.station_id == station.id,
                                       Anomaly.t.between(lo, hi)).all())]
    abnormal += anom_ts
    for t, wear, util in (db.query(StationKpi.t, StationKpi.wear, StationKpi.utilization)
                          .filter(StationKpi.station_id == station.id,
                                  StationKpi.t.between(lo, hi)).all()):
        if (wear is not None and wear > 0.7) or util > 0.97:
            abnormal.append(t)
    if station.has_tool and not abnormal:
        # last maintenance-bounded window: from pass to detection (data-driven)
        abnormal = [pass_t]

    if abnormal:
        start = max(lo, min(abnormal) - 900.0)
        end = min(hi, max(abnormal) + 900.0)
        if end - start < 600:
            end = min(hi, start + 3600.0)
        reason = (f"{len(anom_ts)} anomaly event(s) and abnormal tool/utilization "
                  f"snapshots at {station.code} between {start:.0f} and {end:.0f}.")
        return start, end, "moderate" if end - start > 900 else "low", [reason]

    # sparse signal fallback — bounded by actual station activity
    first_ev, last_ev = (db.query(func.min(VehicleEvent.entered_at),
                                  func.max(VehicleEvent.entered_at))
                         .filter(VehicleEvent.station_id == station.id,
                                 VehicleEvent.entered_at.between(lo, hi)).first())
    if first_ev is not None:
        start = max(lo, first_ev)
        end = min(hi, max(last_ev, pass_t))
        return start, max(start + 600.0, end), "low", [
            f"No strongly abnormal signals at {station.code} in this period — window "
            "bounded by actual station activity (limited traceability)."]
    return lo, hi, "low", ["Insufficient station activity data to bound the window — "
                           "traceability limited."]


def trace_defect(db: Session, defect_id: int) -> dict:
    d = db.get(Defect, defect_id)
    if not d:
        return {"error": "defect not found"}
    veh = db.get(Vehicle, d.vehicle_id)
    det_station = db.get(Station, d.station_id)
    journey = vehicle_journey(db, veh.id)
    steps = journey["steps"] if journey else []
    st_by_code = {s.code: s for s in
                  db.query(Station).filter(Station.line_id == veh.line_id).all()}

    # ---- TRACE BACK — rank upstream stations the vehicle actually visited ----
    origins = []
    for step in steps:
        st = st_by_code.get(step["station"])
        if not st or st.id == d.station_id:
            continue
        if step["entered_at"] >= d.t:
            continue
        score, evidence = _station_evidence(db, st, veh, steps, d.t)
        origins.append({"station_id": st.id, "code": st.code, "zone": st.zone,
                        "score": round(score, 2),
                        "strength": _strength(score),
                        "pass_t": step["entered_at"], "evidence": evidence})
    origins.sort(key=lambda o: -o["score"])
    origins = [o for o in origins if o["score"] >= 0.05][:5]
    multi = (len([o for o in origins if o["strength"] == "strong"]) >= 2
             or (len(origins) >= 2 and origins[0]["score"] - origins[1]["score"] < 0.15))

    # ---- EXPOSURE WINDOW for the top suspected origin ----
    top = origins[0] if origins else None
    window = None
    if top:
        st = st_by_code.get(top["code"])
        ws, we, wconf, wreason = _exposure_window(db, st, top["pass_t"], d.t)
        window = {"station": top["code"], "start": round(ws, 1), "end": round(we, 1),
                  "confidence": wconf, "reason": wreason}

    # ---- TRACE FORWARD — units potentially exposed through the same station/window ----
    exposed = []
    if top and window:
        st = st_by_code[top["code"]]
        ev_rows = (db.query(VehicleEvent, Vehicle.vin, Vehicle.status, Vehicle.batch_id)
                   .join(Vehicle, Vehicle.id == VehicleEvent.vehicle_id)
                   .filter(VehicleEvent.station_id == st.id,
                           VehicleEvent.entered_at.between(window["start"], window["end"]))
                   .order_by(VehicleEvent.entered_at).all())
        batch_codes = {b.id: b.code for b in db.query(ProductionBatch).all()}
        defect_veh = {dv[0] for dv in db.query(Defect.vehicle_id).all()}
        for ev, vin, status, bid in ev_rows:
            full = window["end"] - window["start"]
            mid = (window["start"] + window["end"]) / 2
            overlap = min(ev.entered_at, window["end"]) - ev.entered_at  # time spent inside window
            if ev.entered_at <= window["start"] + full * 0.15 or ev.entered_at >= window["end"] - full * 0.15:
                level = "LOW"
            elif abs(ev.entered_at - mid) < full * 0.25:
                level = "HIGH"
            else:
                level = "MEDIUM"
            if ev.entered_at > mid:  # closer to window end still counts
                level = level if level != "HIGH" else "HIGH"
            confirmed = ev.vehicle_id in defect_veh and ev.vehicle_id != veh.id
            exposed.append({
                "vehicle_id": ev.vehicle_id, "vin": vin, "status": status,
                "batch": batch_codes.get(bid), "shift": _shift(ev.entered_at),
                "exposure_level": level,
                "exposure_ts": round(ev.entered_at, 1),
                "confirmed_defect": confirmed,
            })
    exposed.sort(key=lambda e: (-(e["confirmed_defect"]), -{"HIGH": 2, "MEDIUM": 1, "LOW": 0}[e["exposure_level"]]))

    # ---- COMMON EXPOSURE ANALYSIS ----
    n_exposed = len(exposed)
    common = []
    if n_exposed:
        from collections import Counter
        batches = Counter(e["batch"] for e in exposed if e["batch"])
        shifts = Counter(e["shift"] for e in exposed)
        if batches:
            bcode, bcount = batches.most_common(1)[0]
            common.append({"factor": "batch", "value": bcode,
                           "share": round(bcount / n_exposed, 2),
                           "label": f"Batch {bcode} ({bcount}/{n_exposed} units)"})
        if shifts:
            scode, scount = shifts.most_common(1)[0]
            common.append({"factor": "shift", "value": scode,
                           "share": round(scount / n_exposed, 2),
                           "label": f"Shift {scode} ({scount}/{n_exposed} units)"})
        if top:
            common.append({"factor": "station", "value": top["code"],
                           "share": 1.0,
                           "label": f"Station {top['code']} (all units passed through)"})
            if st_by_code[top["code"]].has_tool:
                common.append({"factor": "tool", "value": f"tool@{top['code']}",
                               "share": round(min(1.0, (bcount or 1) / n_exposed), 2),
                               "label": f"Same tool at {top['code']} during the window"})

    # ---- PROPAGATION RISK ----
    confirmed_others = sum(1 for e in exposed if e["confirmed_defect"])
    score = 0.0
    score += min(0.30, n_exposed / 100.0)
    score += min(0.25, confirmed_others * 0.08)
    score += min(0.15, (window["end"] - window["start"]) / 7200.0 if window else 0)
    common_share = max((c["share"] for c in common), default=0)
    score += common_share * 0.15
    if multi:
        score += 0.10
    # observability penalty: low-confidence stations reduce our certainty
    dq = {r["code"]: r for r in compute_station_data_quality(db, veh.line_id, persist=False)}
    obs_conf = dq.get(top["code"], {}).get("analytics_confidence", 0.5) if top else 0.5
    limited = obs_conf < 0.55 or (window and window["confidence"] == "low")
    if limited:
        score *= 0.8
    risk_level = "high" if score >= 0.55 else "medium" if score >= 0.3 else "low"

    # ---- CONTAINMENT RECOMMENDATIONS (advisory only) ----
    recs = []
    if n_exposed:
        recs.append(f"Prioritize inspection of the {n_exposed} potentially exposed units "
                    f"(start with the {sum(1 for e in exposed if e['exposure_level'] == 'HIGH')} HIGH-exposure ones).")
    if top:
        recs.append(f"Review conditions at {top['code']} during the suspected window — "
                    "tool condition, process parameters and shift logs.")
        if st_by_code[top["code"]].has_tool:
            recs.append(f"Inspect/replace the tool at {top['code']} before the next "
                        "maintenance window.")
    for c in common:
        if c["factor"] == "batch":
            recs.append(f"Inspect vehicles from batch {c['value']} at final inspection "
                        "(shared exposure condition).")
    if confirmed_others:
        recs.append(f"{confirmed_others} additional confirmed defect(s) share this exposure "
                    "— hold release of exposed units pending review.")
    recs.append("Continue monitoring the suspected station after corrective action.")
    if limited:
        recs.append("Improve observability at the suspected origin to strengthen "
                    "future traceback certainty.")

    return {
        "defect_id": d.id, "defect_severity": d.severity,
        "vehicle": veh.vin, "vehicle_id": veh.id, "batch": (
            db.get(ProductionBatch, veh.batch_id).code
            if db.get(ProductionBatch, veh.batch_id) else None),
        "detected_at": d.t, "detection_station": det_station.code,
        "journey": [s["station"] for s in steps],
        "suspected_origins": origins,
        "multiple_plausible_origins": multi,
        "exposure_window": window,
        "potentially_exposed_units": {"total": n_exposed,
                                      "confirmed_defects": confirmed_others,
                                      "potentially_affected": n_exposed - confirmed_others,
                                      "units": exposed},
        "common_exposures": common,
        "propagation_risk": {"level": risk_level, "score": round(score, 2),
                             "note": RISK_NOTE,
                             "drivers": {
                                 "exposed_units": n_exposed,
                                 "confirmed_defects": confirmed_others,
                                 "window_h": round((window["end"] - window["start"]) / 3600.0, 2) if window else 0,
                                 "common_share": common_share,
                                 "multiple_origins": multi,
                                 "observability_confidence": round(obs_conf, 2)}},
        "containment_recommendations": recs,
        "inspection_priority": {
            "HIGH": sum(1 for e in exposed if e["exposure_level"] == "HIGH" and not e["confirmed_defect"]),
            "MEDIUM": sum(1 for e in exposed if e["exposure_level"] == "MEDIUM" and not e["confirmed_defect"]),
            "LOW": sum(1 for e in exposed if e["exposure_level"] == "LOW" and not e["confirmed_defect"])},
        "data_confidence": ("LIMITED TRACEABILITY" if limited else "adequate"),
        "traceability_note": (f"Only {obs_conf*100:.0f}% analytics confidence at the suspected "
                              "origin — results are preliminary." if limited else None),
        "caveat": TRACE_CAVEAT,
        "disclaimer": "Digital twin decision-support using available production, genealogy and "
                      "synthetic observational data — not a confirmed causal determination.",
    }
