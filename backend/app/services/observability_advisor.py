"""Observability Advisor — turns passive coverage/confidence monitoring into an
active, explainable instrumentation-gap advisor (Innovation 1).

Pipeline per station:
    LOW OBSERVABILITY -> IDENTIFY DATA GAP -> IDENTIFY OPERATIONAL RISK
      -> RECOMMEND INSTRUMENTATION / MANUAL CHECK
      -> ESTIMATE CONFIDENCE IMPROVEMENT (labeled estimated/projected)
      -> SHOW PRIORITY

Epistemics: every recommendation is advisory and derived from the station's
own archetype, registered sensors, missing expected signals, freshness,
completeness and anomaly density. Projected confidence is a prototype
estimate (a recomputation of the existing confidence formula under the
assumed post-action state), never a measured guarantee.

Reuses (no duplicate logic):
  - data_quality.compute_station_data_quality  (coverage/completeness/freshness/confidence)
  - bottleneck.compute_bottlenecks             (station criticality for priority)
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import Anomaly, Sensor, Station, StationType, VehicleEvent
from .bottleneck import compute_bottlenecks
from .data_quality import compute_station_data_quality
from .twin_state import last_sim_time

# Which signals materially matter per archetype (name, unit). Derived from the
# site-config archetypes (automotive_line.yaml) — NOT hard-coded per station,
# so the same advisor works for any future line configuration.
ARCHETYPE_EXPECTED: dict[str, list[tuple[str, str]]] = {
    "welding":      [("vibration", "mm/s"), ("temperature", "°C"), ("motor_current", "A")],
    "fastening":    [("torque", "Nm"), ("vibration", "mm/s")],
    "torque":       [("torque", "Nm"), ("vibration", "mm/s")],
    "alignment":    [("temperature", "°C")],
    "pretreatment": [("temperature", "°C")],
    "painting":     [("temperature", "°C"), ("vibration", "mm/s")],
    "curing":       [("temperature", "°C")],
    "electrical":   [("motor_current", "A"), ("temperature", "°C")],
    "fluid_fill":   [("temperature", "°C")],
    "trim":         [],  # manual-checklist dominant
    "inspection":   [],  # sparse profile: cycle-time / vision observation
    "final_test":   [],  # sparse profile: cycle-time / vision observation
}

DISCLAIMER = ("Advisory, simulated estimate. Projected confidence is a "
              "recomputation of the twin's analytics-confidence formula under "
              "assumed post-action observability — not a measured real-world "
              "improvement.")


def _expected_signals(archetype: str) -> list[tuple[str, str]]:
    return ARCHETYPE_EXPECTED.get(archetype, [])


def _projected_confidence(coverage: float, completeness: float,
                          anomaly_rate: float, fresh: bool = True) -> float:
    """Recompute the existing confidence formula (0.45·cov + 0.35·comp +
    0.20·fresh − 0.30·anomaly) under the assumed post-action state."""
    fresh_score = 1.0 if fresh else 0.4
    return round(min(max(0.45 * coverage + 0.35 * completeness
                         + 0.20 * fresh_score - 0.30 * anomaly_rate, 0.0), 1.0), 3)


def _classify(dq: dict, s: Settings) -> tuple[str, int]:
    """observability_level + raw priority score.

    Levels distinguish severity: CRITICAL_GAP only for compounding failures
    (near-zero coverage AND degraded confidence AND/OR stale + anomalies).
    Priority is a separate axis that folds in operational context (bottleneck
    status, recent anomalies) — a stable-but-poorly-instrumented station is
    LOW observability / MEDIUM priority, while the same station under load
    rises to HIGH. Calibrated to the mixed-scenario profile mix (17 full /
    12 mid / 9 sparse / 4 manual).
    """
    cov, conf = dq["sensor_coverage"], dq["analytics_confidence"]
    stale = dq["freshness"] == "stale"   # readings exist but are old
    no_reading = dq["freshness"] == "low"  # no telemetry at all (design gap for sparse/manual)
    anom = dq["anomaly_rate"]
    score = 0
    if cov < s.obs_critical_coverage:
        score += 2
    elif cov < s.obs_low_coverage:
        score += 1
    if conf < s.obs_critical_confidence:
        score += 2
    elif conf < s.obs_medium_confidence:
        score += 1
    # staleness is a fault only where telemetry is EXPECTED (instrumented station)
    if stale:
        score += 2
        if cov < s.obs_low_coverage:
            score += 1  # gap + stale telemetry compounds
    if anom > 0.05:
        score += 2
    elif anom > 0.02:
        score += 1
    # level
    compounding = (cov < s.obs_critical_coverage and conf < s.obs_critical_confidence)
    worse = (cov == 0.0 and (stale or anom > 0.05))  # no sensors AND can't see what's wrong
    if compounding or worse:
        level = "CRITICAL_GAP"
    elif cov < s.obs_low_coverage or conf < s.obs_medium_confidence:
        level = "LOW"
    elif conf < s.obs_high_confidence or stale:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return level, score


def compute_observability_advisor(db: Session, line_id: int) -> dict:
    """Full advisor output for every station on the line."""
    s = get_settings()
    dq_rows = compute_station_data_quality(db, line_id, persist=False)
    stations = {st.id: st for st in db.query(Station).filter_by(line_id=line_id).all()}
    st_types = {t.id: t.code for t in db.query(StationType).all()}
    # registered sensor names per station
    sensor_names: dict[int, set[str]] = {}
    for sid, name in db.query(Sensor.station_id, Sensor.name).all():
        sensor_names.setdefault(sid, set()).add(name)
    # recent anomaly counts (last hour) for operational-risk context
    now = last_sim_time(db)
    anom_recent = dict(
        db.query(Anomaly.station_id, func.count())
        .filter(Anomaly.t >= max(0.0, now - 3600.0))
        .group_by(Anomaly.station_id).all())
    # bottleneck context: is this station among the line's top constraints?
    bn_ranking = compute_bottlenecks(db, line_id)["ranking"]
    bn_top_ids = {r["station_id"] for r in bn_ranking[:5]}

    out = []
    for dq in dq_rows:
        st = stations[dq["station_id"]]
        archetype = st_types.get(st.type_id, "generic")
        cov, conf = dq["sensor_coverage"], dq["analytics_confidence"]
        level, pscore = _classify(dq, s)
        is_bn = st.id in bn_top_ids
        if is_bn:
            pscore += 2
        if anom_recent.get(st.id, 0) > 0:
            pscore += 1
        priority = ("CRITICAL" if pscore >= 8 else "HIGH" if pscore >= 5
                    else "MEDIUM" if pscore >= 2 else "LOW")

        # --- recommendations ---
        expected = _expected_signals(archetype)
        registered = sensor_names.get(st.id, set())
        recs: list[dict] = []
        if cov < s.obs_low_coverage and expected:
            missing = [(n, u) for n, u in expected if n not in registered]
            if missing:
                for n, u in missing[:2]:
                    recs.append({
                        "action_type": "ADD_SENSOR",
                        "text": f"Add {n} monitoring ({u}) — a signal the {archetype} process relies on.",
                        "detail": f"Potential instrumentation gap: '{n}' not registered at this station.",
                    })
                if len(missing) > 2:
                    recs.append({
                        "action_type": "IMPROVE_COVERAGE",
                        "text": (f"Extend coverage ({cov:.0%}) for remaining critical signals: "
                                 f"{', '.join(n for n, _ in missing[2:])}."),
                        "detail": "Instrumentation retrofits belong in a scheduled maintenance window (read-only twin).",
                    })
        elif st.sensor_profile == "sparse":
            recs.append({
                "action_type": "ADD_SENSOR",
                "text": "Add cycle-time monitoring — this station currently records cycle/part events only.",
                "detail": "Cycle-time telemetry is the minimum signal for bottleneck/quality analytics here.",
            })
        if st.sensor_profile in ("manual", "sparse") or cov < s.obs_critical_coverage:
            recs.append({
                "action_type": "MANUAL_INSPECTION",
                "text": "Manual inspection / checklist validation recommended until instrumentation is available.",
                "detail": f"Observability limited (coverage {cov:.0%}, confidence {conf:.0%}); human checks are the fallback signal.",
            })
        if dq["freshness"] == "stale":
            recs.append({
                "action_type": "FRESHNESS_ACTION",
                "text": "Sensor data is stale — validate sensor connectivity or refresh telemetry.",
                "detail": f"Newest reading {dq['freshness_s']:.0f}s old; analytics confidence is penalized by staleness.",
            })
        if dq["completeness"] < s.obs_completeness_min:
            recs.append({
                "action_type": "DATA_QUALITY_ACTION",
                "text": f"Coverage adequate but completeness is {dq['completeness']:.0%} — investigate missing telemetry.",
                "detail": "Random dropouts reduce the confidence the twin can place in this station's analytics.",
            })

        # --- projected confidence (estimated, never guaranteed) ---
        projected: float | None = None
        if recs and level != "HIGH":
            new_cov = cov
            if expected and any(r["action_type"] in ("ADD_SENSOR", "IMPROVE_COVERAGE")
                                for r in recs):
                n_expected = len(expected)
                n_reg = len([n for n, _ in expected if n in registered])
                new_cov = min(1.0, (n_reg + max(n_expected - n_reg, 0)) / max(n_expected, 1))
            new_compl = dq["completeness"]
            if any(r["action_type"] in ("DATA_QUALITY_ACTION", "FRESHNESS_ACTION") for r in recs):
                new_compl = min(1.0, new_compl + 0.15)
            raw_projected = _projected_confidence(new_cov, new_compl, dq["anomaly_rate"], fresh=True)
            # conservative, honest estimate: cap the claimed gain (prototype,
            # not a validated guarantee)
            projected = round(min(raw_projected, conf + 0.30), 3)

        # --- rationale (explainability) ---
        bits = []
        if cov < s.obs_low_coverage:
            bits.append(f"only {cov:.0%} sensor coverage")
        if dq["freshness"] == "stale":
            bits.append("stale telemetry")
        if dq["completeness"] < s.obs_completeness_min:
            bits.append(f"{dq['completeness']:.0%} completeness")
        if dq["anomaly_rate"] > 0.02:
            bits.append(f"{dq['anomaly_rate']:.1%} anomaly density")
        why = ("low sensor coverage and stale telemetry reduce confidence in "
               "station-level analytics." if not bits else
               f"{' and '.join(bits)} reduce confidence in station-level analytics.")
        if anom_recent.get(st.id, 0) > 0:
            why += (f" The station also shows {anom_recent[st.id]} recent anomaly"
                    f"{'s' if anom_recent[st.id] > 1 else ''} — instrumentation "
                    "would make the cause visible.")
        if is_bn:
            why += " It is currently among the line's top constraints, so the gap matters more."

        out.append({
            "station_id": st.id, "code": st.code, "zone": st.zone,
            "archetype": archetype, "sensor_profile": st.sensor_profile,
            "coverage": cov, "completeness": dq["completeness"],
            "freshness": dq["freshness"], "freshness_s": dq["freshness_s"],
            "anomaly_rate": dq["anomaly_rate"],
            "confidence": conf,
            "observability_level": level,
            "identified_gap": ("Instrumentation gap" if cov < s.obs_low_coverage
                               else "Data-quality gap" if dq["completeness"] < s.obs_completeness_min
                               else "Staleness gap" if dq["freshness"] == "stale"
                               else "No material gap" if level == "HIGH" else "Partial observability"),
            "recommendations": recs,
            "projected_confidence": projected,
            "priority": priority,
            "rationale": why,
            "is_bottleneck": is_bn,
        })

    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in out:
        k = r["priority"].lower()
        summary[k] = summary.get(k, 0) + 1
    return {"generated_at": now, "disclaimer": DISCLAIMER,
            "summary": summary, "stations": out}
