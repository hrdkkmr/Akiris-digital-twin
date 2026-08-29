"""Multi-causal contributing-factor analysis (Innovation 2).

Correlates multiple evidence sources around an incident (elevated defect
risk / actual defect / bottleneck / station degradation) and produces:

  - ranked LIKELY CONTRIBUTING FACTORS  (relative evidence scores, never
    "root cause identified" — the data does not establish causality)
  - INTERMITTENT PATTERNS               (conditions under which incidents
    occur disproportionately, with min-sample guards)
  - EVIDENCE MATRIX                     (factor x station strength grid)

Epistemics: every output is labeled as an observed association, not a causal
determination. Evidence strings are built from real database rows (wear,
vibration, torque, cycle deviation, batch incidence, shift-incidence,
temperature) — nothing is hard-coded per station.

Reuses: bottleneck.compute_bottlenecks, genealogy.vehicle_journey,
         models (no new tables).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (Anomaly, Defect, EnvironmentSample, Inspection,
                      MachineEvent, ProductionBatch, SensorReading, Station,
                      StationKpi, StationType, Vehicle, VehicleEvent)
from .bottleneck import compute_bottlenecks
from .genealogy import vehicle_journey
from .twin_state import last_sim_time

CAVEAT = ("Observed associations from available data. Not a causal "
          "determination — confirmed causality requires engineering "
          "investigation.")
DISCLAIMER = ("Contributing-factor analysis ranks relative evidence from "
              "available synthetic observations; scores are not probabilities "
              "of causation.")

SHIFT_SECONDS = 8 * 3600  # 3x8h cadence (config shifts.length_hours)
MIN_PATTERN_SAMPLE = 30   # ignore patterns from tiny datasets
MIN_LIFT = 1.5            # incidence ratio to call a pattern "detected"


def _shift_of(t: float) -> str:
    return ["A", "B", "C"][int(t // SHIFT_SECONDS) % 3]


def _strength(score: float) -> str:
    return "strong" if score >= 0.5 else "moderate" if score >= 0.25 else "weak"


def _norm(scores: dict[str, float]) -> dict[str, float]:
    tot = sum(max(v, 0.0) for v in scores.values()) or 1.0
    return {k: round(v / tot, 3) for k, v in scores.items()}


# --------------------------------------------------------------------------
# per-station analysis
# --------------------------------------------------------------------------
def _station_fleet_baselines(db: Session) -> dict[str, dict]:
    """Per-sensor fleet means (used to quantify deviations at one station)."""
    rows = (db.query(SensorReading.sensor_name, func.avg(SensorReading.mean))
            .group_by(SensorReading.sensor_name).all())
    return {name: {"mean": m} for name, m in rows}


def _shift_defect_rates(db: Session, line_id: int) -> dict[str, float]:
    """Defect (scrap) rate per derived shift across the line."""
    totals = defaultdict(int)
    bad = defaultdict(int)
    for veh, in db.query(Vehicle.started_at).filter_by(line_id=line_id).all():
        totals[_shift_of(veh)] += 1
    for veh, in (db.query(Vehicle.started_at)
                 .filter(Vehicle.line_id == line_id, Vehicle.status == "scrapped").all()):
        bad[_shift_of(veh)] += 1
    return {sh: bad[sh] / max(totals[sh], 1) for sh in totals}


def _batch_stats(db: Session, line_id: int) -> dict[str, dict]:
    rows = (db.query(ProductionBatch.id, ProductionBatch.code, func.count(Vehicle.id))
            .join(Vehicle, Vehicle.batch_id == ProductionBatch.id)
            .filter(Vehicle.line_id == line_id)
            .group_by(ProductionBatch.id, ProductionBatch.code).all())
    out = {}
    for bid, code, n in rows:
        bad = (db.query(func.count()).filter(Vehicle.batch_id == bid,
                                             Vehicle.status == "scrapped").scalar() or 0)
        out[code] = {"n": n, "scrapped": bad,
                     "rate": bad / max(n, 1)}
    return out


def _station_factors(db: Session, line_id: int, st: Station,
                     since: float) -> list[dict]:
    """Compute ranked factor evidence for ONE station (no recursion — the
    shared core for both the incident analysis and the evidence matrix)."""
    fleet = _station_fleet_baselines(db)
    shift_rates = _shift_defect_rates(db, line_id)
    batches = _batch_stats(db, line_id)

    # -- station KPIs ------------------------------------------------------
    kpis = (db.query(StationKpi).filter(StationKpi.station_id == st.id,
                                        StationKpi.t >= since).all())
    wear_vals = [k.wear for k in kpis if k.wear is not None]
    utils = [k.utilization for k in kpis]
    queues = [k.queue_len for k in kpis]
    avg_wear = sum(wear_vals) / len(wear_vals) if wear_vals else 0.0
    max_wear = max(wear_vals) if wear_vals else 0.0
    avg_util = sum(utils) / len(utils) if utils else 0.0
    avg_queue = sum(queues) / len(queues) if queues else 0.0
    max_queue = max(queues) if queues else 0.0

    # -- cycle deviation at station ----------------------------------------
    cyc = (db.query(func.avg(VehicleEvent.cycle_dev), func.count())
           .filter(VehicleEvent.station_id == st.id,
                   VehicleEvent.exited_at >= since).first())
    avg_cyc_dev = float(cyc[0] or 0.0)
    n_cyc = int(cyc[1] or 0)

    # -- sensor deviations (vibration / torque / temperature / current) ----
    sensor_rows = (db.query(SensorReading.sensor_name,
                            func.avg(SensorReading.mean),
                            func.avg(SensorReading.std))
                   .filter(SensorReading.station_id == st.id)
                   .group_by(SensorReading.sensor_name).all())
    sensor_dev: list[str] = []
    max_sensor_lift = 0.0
    for name, m, std in sensor_rows:
        base = fleet.get(name, {}).get("mean") or 0.0
        if base and m:
            lift = abs(m - base) / max(base, 1e-9)
            max_sensor_lift = max(max_sensor_lift, lift)
            if lift > 0.12:
                sensor_dev.append(f"{name} {lift*100:+.0f}% vs fleet mean")

    # -- recent anomalies ----------------------------------------------------
    n_anom = (db.query(func.count()).filter(Anomaly.station_id == st.id,
                                            Anomaly.t >= since).scalar() or 0)
    # -- vehicle flow through this station: batch + shift composition --------
    veh_rows = (db.query(Vehicle.id, Vehicle.batch_id, Vehicle.started_at,
                         Vehicle.status, ProductionBatch.code)
                .join(ProductionBatch, ProductionBatch.id == Vehicle.batch_id)
                .join(VehicleEvent, VehicleEvent.vehicle_id == Vehicle.id)
                .filter(VehicleEvent.station_id == st.id,
                        VehicleEvent.exited_at >= since).all())
    seen = {v.id for v in veh_rows}
    n_veh = len(seen)
    bad_here = sum(1 for v in veh_rows if v.id in seen and v.status == "scrapped")
    batch_counts: dict[str, int] = defaultdict(int)
    for v in veh_rows:
        batch_counts[v.code] += 1

    # ----------------------------------------------------------------------
    # FACTOR SCORING  (relative evidence, not causality)
    # ----------------------------------------------------------------------
    raw: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}

    # 1) EQUIPMENT — tool wear
    ev = []
    if wear_vals and max_wear > 0.55:
        ev.append(f"Tool wear up to {max_wear*100:.0f}% (avg {avg_wear*100:.0f}%) in the last 4 shifts")
        raw["tool_wear"] = min(1.0, (max_wear - 0.55) / 0.45)
    if sensor_dev:
        ev += [f"Equipment telemetry: {s}" for s in sensor_dev[:3]]
        raw["tool_wear"] = raw.get("tool_wear", 0.0) + 0.3
    if n_anom > 0:
        ev.append(f"{n_anom} anomalies at this station in the window")
        raw["tool_wear"] = raw.get("tool_wear", 0.0) + 0.15
    if not ev and st.has_tool:
        ev.append("No tool-wear or telemetry evidence flagged in window")
    if ev:
        evidence["equipment"] = ev

    # 2) PROCESS — cycle-time variation & queue buildup
    ev = []
    if n_cyc >= MIN_PATTERN_SAMPLE and abs(avg_cyc_dev) > 2.5:
        ev.append(f"Mean |cycle deviation| {abs(avg_cyc_dev):.1f}s across {n_cyc} vehicles")
        raw["process"] = min(0.7, abs(avg_cyc_dev) / 10.0)
    if max_queue >= 15:
        ev.append(f"Queue buildup up to {max_queue} (avg {avg_queue:.0f})")
        raw["process"] = raw.get("process", 0.0) + 0.25
    if avg_util >= 0.9:
        ev.append(f"Station saturation {avg_util*100:.0f}% utilization")
        raw["process"] = raw.get("process", 0.0) + 0.2
    if ev:
        evidence["process"] = ev

    # 3) UPSTREAM — supplier batch composition at this station
    ev = []
    worst_batch = None
    worst_lift = 0.0
    for code, n in batch_counts.items():
        b = batches.get(code)
        if not b or b["n"] < 3:
            continue
        overall = b["rate"] / max(sum(1 for x in batches.values() if x["n"]), 1)
        lift = b["rate"] / max(overall, 1e-6)
        if lift > worst_lift:
            worst_lift, worst_batch = lift, code
    if worst_batch and worst_lift >= 1.5:
        b = batches[worst_batch]
        ev.append(f"Batch {worst_batch}: {b['scrapped']}/{b['n']} scrapped — {b['rate']*100:.1f}% incidence")
        ev.append(f"Vehicles from {worst_batch} passed through this station: {batch_counts[worst_batch]}")
        raw["upstream"] = min(0.9, worst_lift / 4.0)
    if n_veh and bad_here / n_veh > 0.05:
        ev.append(f"{bad_here}/{n_veh} vehicles through this station ended scrapped")
        raw["upstream"] = max(raw.get("upstream", 0.0), 0.35)
    if ev:
        evidence["upstream"] = ev

    # 4) OPERATOR — shift incidence
    ev = []
    worst_shift, worst_shift_lift = None, 0.0
    for sh, rate in shift_rates.items():
        other = [r for s, r in shift_rates.items() if s != sh]
        base = sum(other) / max(len(other), 1)
        if base > 0 and rate / base > worst_shift_lift:
            worst_shift_lift, worst_shift = rate / base, sh
    if worst_shift and worst_shift_lift >= MIN_LIFT:
        ev.append(f"Shift {worst_shift} shows {shift_rates[worst_shift]*100:.1f}% defect incidence vs "
                  f"{sum(shift_rates.values())/max(len(shift_rates),1)*100:.1f}% average")
        ev.append("Shift labels derived from timestamps (3x8h cadence)")
        raw["operator"] = min(0.6, worst_shift_lift / 5.0)
    if ev:
        evidence["operator"] = ev

    # 5) ENVIRONMENT — temperature/humidity (env-sensitive stations)
    ev = []
    env = (db.query(EnvironmentSample)
           .filter(EnvironmentSample.t >= since).all())
    if env and st.env_sensitive:
        hot = sum(1 for e in env if e.temp_c > 30.0 or e.humidity > 65.0)
        frac = hot / max(len(env), 1)
        if frac > 0.4:
            ev.append(f"{frac*100:.0f}% of environment samples outside comfort band (T>30°C / RH>65%)")
            raw["environment"] = 0.4 * frac
    elif env:
        t_mean = sum(e.temp_c for e in env) / len(env)
        if t_mean > 30.0:
            ev.append(f"Mean ambient {t_mean:.1f}°C above the 30°C paint-environment threshold")
            raw["environment"] = 0.3
    if ev:
        evidence["environment"] = ev

    # normalize to relative contribution shares
    norm = _norm(raw)

    factors = []
    for key in ("tool_wear", "process", "upstream", "operator", "environment"):
        if key in norm and norm[key] > 0:
            factors.append({
                "factor": key,
                "label": {"tool_wear": "Tool wear / equipment",
                          "process": "Process variation (cycle/queue)",
                          "upstream": "Supplier batch quality",
                          "operator": "Shift / operator variation",
                          "environment": "Environmental conditions"}[key],
                "score": norm[key],
                "strength": _strength(raw[key]),
                "evidence": evidence.get(
                    {"tool_wear": "equipment", "process": "process",
                     "upstream": "upstream", "operator": "operator",
                     "environment": "environment"}[key], []),
            })
    factors.sort(key=lambda f: -f["score"])
    return factors


def analyze_station_contributing_factors(db: Session, line_id: int,
                                         station_id: int | None = None,
                                         station_code: str | None = None) -> dict:
    """Rank likely contributing factors for an incident centered on a station
    (bottleneck / elevated defect risk / degradation)."""
    st = (db.get(Station, station_id) if station_id
          else db.query(Station).filter(Station.line_id == line_id,
                                        Station.code == station_code).first())
    if not st:
        return {"error": "station not found", "disclaimer": DISCLAIMER}
    st_type = db.get(StationType, st.type_id)
    archetype = st_type.code if st_type else "generic"
    now = last_sim_time(db)
    since = max(0.0, now - 4 * SHIFT_SECONDS)  # look back ~4 shifts
    bn_ranking = compute_bottlenecks(db, line_id)["ranking"]
    bn_row = next((r for r in bn_ranking if r["station_id"] == st.id), None)

    # observability-aware caveat (connects Innovation 1 -> 2)
    from .data_quality import compute_station_data_quality
    dq_row = next((r for r in compute_station_data_quality(db, line_id, persist=False)
                   if r["station_id"] == st.id), None)
    analysis_note = None
    if dq_row and dq_row["analytics_confidence"] < 0.55:
        analysis_note = ("Analysis confidence is limited because station "
                         f"observability is low (confidence "
                         f"{dq_row['analytics_confidence']*100:.0f}%, coverage "
                         f"{dq_row['sensor_coverage']*100:.0f}%).")

    return {
        "station": st.code, "station_id": st.id, "zone": st.zone,
        "archetype": archetype, "incident_type": "station_analysis",
        "bottleneck": bn_row,
        "factors": _station_factors(db, line_id, st, since),
        "intermittent_patterns": detect_intermittent_patterns(db, line_id, st.id),
        "evidence_matrix": evidence_matrix(db, line_id, st.id),
        "analysis_note": analysis_note,
        "disclaimer": DISCLAIMER,
        "caveat": CAVEAT,
    }


# --------------------------------------------------------------------------
# Intermittent pattern detection (line-wide or station-scoped)
# --------------------------------------------------------------------------
def _scrap_rate_in_window(db: Session, station_id: int, t0: float, t1: float) -> tuple[float, int]:
    """scrap rate + n for vehicles exiting a station within [t0, t1]."""
    q = (db.query(func.count()).select_from(VehicleEvent)
         .join(Vehicle, Vehicle.id == VehicleEvent.vehicle_id)
         .filter(VehicleEvent.station_id == station_id,
                 VehicleEvent.exited_at >= t0, VehicleEvent.exited_at <= t1))
    n = q.scalar() or 0
    bad = q.filter(Vehicle.status == "scrapped").scalar() or 0
    return (bad / max(n, 1), n)


def detect_intermittent_patterns(db: Session, line_id: int,
                                 station_id: int | None = None) -> list[dict]:
    patterns: list[dict] = []

    def _defect_rows(station: int | None):
        q = (db.query(Vehicle.started_at, Vehicle.status)
             .filter(Vehicle.line_id == line_id))
        if station:
            q = q.join(VehicleEvent, VehicleEvent.vehicle_id == Vehicle.id)\
                 .filter(VehicleEvent.station_id == station)
        return q.all()

    # --- shift pattern ---
    totals = defaultdict(int)
    bad = defaultdict(int)
    for t, status in _defect_rows(station_id):
        totals[_shift_of(t)] += 1
        if status == "scrapped":
            bad[_shift_of(t)] += 1
    overall_bad = sum(bad.values())
    overall_n = sum(totals.values())
    overall_rate = overall_bad / max(overall_n, 1)
    for sh in sorted(totals):
        if totals[sh] >= MIN_PATTERN_SAMPLE and overall_rate > 0:
            rate = bad[sh] / totals[sh]
            lift = rate / overall_rate
            if lift >= MIN_LIFT:
                patterns.append({
                    "type": "shift",
                    "title": "Shift-related pattern",
                    "description": (f"Defect incidence is ~{lift:.1f}× higher during "
                                    f"shift {sh} ({rate*100:.1f}%) than the period "
                                    f"average ({overall_rate*100:.1f}%)."),
                    "strength": _strength(min(0.5, lift / 4.0)),
                    "statistics": {"shift": sh, "rate": round(rate, 4),
                                   "overall_rate": round(overall_rate, 4),
                                   "lift": round(lift, 2), "n": totals[sh]},
                })

    # --- tool-wear band pattern (per tooled station; station-scoped if asked) ---
    wear_rows = (db.query(StationKpi.station_id, func.max(StationKpi.wear))
                 .filter(StationKpi.wear.isnot(None))
                 .group_by(StationKpi.station_id).all())
    if station_id:
        wear_rows = [r for r in wear_rows if r[0] == station_id]
    for sid, max_wear in wear_rows:
        code = db.get(Station, sid).code
        kpis = db.query(StationKpi.t, StationKpi.wear).filter(StationKpi.station_id == sid).all()
        hi_ts = [t for t, w in kpis if w and w > 0.8]
        lo_ts = [t for t, w in kpis if w is not None and w <= 0.8]
        if len(hi_ts) < 20 or len(lo_ts) < 20:
            continue
        hi_rate, hi_n = _scrap_rate_in_window(db, sid, min(hi_ts), max(hi_ts))
        lo_rate, lo_n = _scrap_rate_in_window(db, sid, min(lo_ts), max(lo_ts))
        if hi_n >= MIN_PATTERN_SAMPLE and lo_n >= MIN_PATTERN_SAMPLE \
                and hi_rate > lo_rate * MIN_LIFT and hi_rate > 0.005:
            patterns.append({
                "type": "tool_wear",
                "title": "High tool-wear condition",
                "description": (f"At {code}, defect incidence is higher when wear "
                                f"exceeds 80% ({hi_rate:.2%} vs {lo_rate:.2%} "
                                f"below 80%) — an intermittent equipment-related pattern."),
                "strength": _strength(min(0.7, hi_rate / max(lo_rate, 1e-6) / 3.0)),
                "statistics": {"station": code, "hi_rate": round(hi_rate, 4),
                               "lo_rate": round(lo_rate, 4),
                               "lift": round(hi_rate / max(lo_rate, 1e-6), 2)},
            })

    # --- supplier-batch pattern ---
    batches = _batch_stats(db, line_id)
    overall = sum(b["scrapped"] for b in batches.values()) / max(
        sum(b["n"] for b in batches.values()), 1)
    for code, b in sorted(batches.items(), key=lambda kv: -kv[1]["rate"]):
        if b["n"] >= MIN_PATTERN_SAMPLE and overall > 0 and b["rate"] / overall >= MIN_LIFT:
            patterns.append({
                "type": "batch",
                "title": "Batch-specific pattern",
                "description": (f"Batch {code} shows {b['rate']*100:.1f}% defect "
                                f"incidence vs {overall*100:.1f}% overall "
                                f"({b['scrapped']}/{b['n']} affected)."),
                "strength": _strength(min(0.7, b["rate"] / overall / 3.0)),
                "statistics": {"batch": code, "rate": round(b["rate"], 4),
                               "overall": round(overall, 4),
                               "lift": round(b["rate"] / overall, 2), "n": b["n"]},
            })
            if len(patterns) >= 6:
                break

    # --- environment pattern ---
    env = db.query(EnvironmentSample).all()
    if len(env) >= MIN_PATTERN_SAMPLE:
        hot = [e for e in env if e.temp_c > 30.0]
        if hot:
            hot_window = (hot[0].t, hot[-1].t)
            hot_bad = (db.query(func.count())
                       .select_from(Vehicle)
                       .filter(Vehicle.line_id == line_id, Vehicle.status == "scrapped",
                               Vehicle.started_at >= hot_window[0],
                               Vehicle.started_at <= hot_window[1]).scalar() or 0)
            hot_n = (db.query(func.count())
                     .select_from(Vehicle)
                     .filter(Vehicle.line_id == line_id,
                             Vehicle.started_at >= hot_window[0],
                             Vehicle.started_at <= hot_window[1]).scalar() or 0)
            cool_n = overall_n - hot_n
            cool_bad = overall_bad - hot_bad
            if hot_n >= MIN_PATTERN_SAMPLE and cool_n >= MIN_PATTERN_SAMPLE:
                hot_rate = hot_bad / hot_n
                cool_rate = cool_bad / max(cool_n, 1)
                if hot_rate > cool_rate * MIN_LIFT:
                    patterns.append({
                        "type": "environment",
                        "title": "High-temperature pattern",
                        "description": (f"Defect incidence is ~{hot_rate/cool_rate:.1f}× "
                                        f"higher during ambient T>30°C periods "
                                        f"({hot_rate*100:.1f}% vs {cool_rate*100:.1f}%)."),
                        "strength": _strength(min(0.6, hot_rate / max(cool_rate, 1e-6) / 3.0)),
                        "statistics": {"hot_rate": round(hot_rate, 4),
                                       "cool_rate": round(cool_rate, 4),
                                       "lift": round(hot_rate / max(cool_rate, 1e-6), 2),
                                       "n": hot_n},
                    })
    return patterns[:6]


# --------------------------------------------------------------------------
# Evidence matrix: factor strength across stations
# --------------------------------------------------------------------------
def evidence_matrix(db: Session, line_id: int,
                    center_station: int | None = None) -> dict:
    """factor x station strength grid. Center station + up to 3 neighbours."""
    now = last_sim_time(db)
    since = max(0.0, now - 4 * SHIFT_SECONDS)
    stations = db.query(Station).filter_by(line_id=line_id).order_by(Station.seq).all()
    center = db.get(Station, center_station) if center_station else stations[0]
    idx = stations.index(center)
    focus = [s for s in stations[max(0, idx - 1): idx + 2]]
    focus = list(dict.fromkeys([center] + focus))[:4]

    matrix = {}
    for f in ("tool_wear", "process", "upstream", "operator", "environment"):
        row = {}
        for st in focus:
            frow = next((x for x in _station_factors(db, line_id, st, since)
                         if x["factor"] == f), None)
            row[st.code] = frow["strength"].upper() if frow else "NONE"
        matrix[f] = row
    return {"legend": ["STRONG", "MEDIUM", "WEAK", "NONE"], "matrix": matrix,
            "stations": [s.code for s in focus]}


# --------------------------------------------------------------------------
# vehicle-level analysis (genealogy-based)
# --------------------------------------------------------------------------
def analyze_vehicle_contributing_factors(db: Session, vehicle_id: int) -> dict:
    journey = vehicle_journey(db, vehicle_id, include_truth=False)
    if not journey:
        return {"error": "vehicle not found", "disclaimer": DISCLAIMER}
    veh = db.get(Vehicle, vehicle_id)
    line_id = veh.line_id
    steps = journey["steps"]

    abnormal = [s for s in steps
                if (s["anomaly_score"] or 0) > 0.9 or (s["cycle_dev"] or 0) > 6
                or s["checklist"] == "NOK"]
    worst = max(abnormal, key=lambda s: (s["anomaly_score"] or 0)) if abnormal else None

    shift = _shift_of(veh.started_at)
    shift_rates = _shift_defect_rates(db, line_id)
    batches = _batch_stats(db, line_id)
    batch = db.query(ProductionBatch).filter_by(id=veh.batch_id).first()
    batch_code = batch.code if batch else None

    evidence: list[str] = []
    if worst:
        evidence.append(f"Genealogy shows anomalies/deviations at {worst['station']} "
                        f"(anom {worst['anomaly_score'] or 0:.2f}, Δcycle {worst['cycle_dev'] or 0:+.1f}s)")
    else:
        evidence.append("No abnormal upstream station events in this vehicle's journey")

    factors: list[dict] = []
    raw: dict[str, float] = {}
    ev: dict[str, list[str]] = {}

    # PROCESS — genealogy deviations
    if worst:
        raw["process"] = min(0.7, abs(worst["cycle_dev"] or 0) / 10.0)
        ev["process"] = [f"Cycle deviation {worst['cycle_dev']:+.1f}s at {worst['station']}"]
    else:
        raw["process"] = 0.3
        ev["process"] = ["No abnormal cycle deviation in this vehicle's journey"]

    # UPSTREAM — supplier batch (always present; strength follows incidence)
    if batch_code and batches.get(batch_code, {}).get("n", 0) >= 3:
        b = batches[batch_code]
        overall = sum(x["scrapped"] for x in batches.values()) / max(
            sum(x["n"] for x in batches.values()), 1)
        lift = b["rate"] / max(overall, 1e-6)
        if lift >= 1.3:
            raw["upstream"] = min(0.8, lift / 4.0)
            ev["upstream"] = [f"Vehicle is from batch {batch_code} "
                              f"({b['scrapped']}/{b['n']} scrapped, {b['rate']*100:.1f}% rate)"]
        else:
            raw["upstream"] = 0.25
            ev["upstream"] = [f"Vehicle is from batch {batch_code} "
                              f"({b['scrapped']}/{b['n']} scrapped, {b['rate']*100:.1f}% rate — "
                              "no elevation above line average)"]
    elif batch_code:
        raw["upstream"] = 0.15
        ev["upstream"] = [f"Vehicle is from batch {batch_code} (too few vehicles in "
                          "batch for reliable incidence comparison)"]

    # OPERATOR — shift (always present; strength follows shift-level rate)
    if shift_rates.get(shift, 0) > 0 and len(shift_rates):
        overall = sum(shift_rates.values()) / max(len(shift_rates), 1)
        if shift_rates[shift] / overall >= 1.4:
            raw["operator"] = 0.4
            ev["operator"] = [f"Vehicle built on shift {shift} — defect incidence "
                              f"{shift_rates[shift]*100:.1f}% vs {overall*100:.1f}% average"]
        else:
            raw["operator"] = 0.2
            ev["operator"] = [f"Vehicle built on shift {shift} — defect incidence "
                              f"{shift_rates[shift]*100:.1f}% vs {overall*100:.1f}% line average "
                              "(no elevation)"]

    norm = _norm(raw)
    for key, label in (("process", "Process / station deviation"),
                       ("upstream", "Supplier batch quality"),
                       ("operator", "Shift / operator variation")):
        if key in norm and norm[key] > 0:
            factors.append({"factor": key, "label": label, "score": norm[key],
                            "strength": _strength(raw[key]),
                            "evidence": ev.get(key, [])})
    factors.sort(key=lambda f: -f["score"])

    return {
        "vehicle": veh.vin, "vehicle_id": veh.id,
        "batch": batch_code, "shift": shift,
        "outcome": journey["outcome"],
        "factors": factors,
        "genealogy_note": ("Vehicle genealogy indicates exposure to " +
                           (f"elevated conditions at {worst['station']} " if worst else "") +
                           (f"and component batch {batch_code}." if batch_code else ".")),
        "disclaimer": DISCLAIMER,
        "caveat": CAVEAT,
    }
