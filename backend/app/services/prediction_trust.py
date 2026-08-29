"""Prediction validation & AI trust (Innovation 5).

Every defect-risk prediction is tracked against the ACTUAL production
outcome once it becomes available (TP / TN / FP / FN), with a pending state
while validation is impossible. From that validated corpus we compute:

- overall model trust (precision / recall / false-alarm rate — calculated,
  never arbitrary)
- station-level trust (where the model is weaker)
- false-alarm monitor (rate, worst station, trend)
- confidence-vs-outcome bins (do high-confidence predictions do better?)
- model lifecycle: production model vs candidate model, candidate
  revalidation, human approval, and controlled deployment through the
  existing maintenance-window workflow (Innovation 3).

Rules: AI predictions are never ground truth. Missing outcomes are NEVER
counted as validated. The production model is NEVER replaced silently —
a candidate must be approved and deployed via the maintenance window.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (MaintenanceQueueItem, ModelVersion, Prediction, Station,
                      StationType, Vehicle, VehicleEvent)
from .data_quality import compute_station_data_quality
from .shadow_sim import maintenance_windows
from .twin_state import last_sim_time

TRUST_NOTE = ("AI predictions are validated against actual outcomes, not treated "
              "as ground truth. Metrics are computed from the validated corpus only.")
INSUFFICIENT = "Insufficient validated outcomes"


# ---------------------------------------------------------------------------
# classification helpers
# ---------------------------------------------------------------------------
def _thresholds(db: Session) -> dict[int, float]:
    out = {}
    for m in db.query(ModelVersion).all():
        out[m.id] = m.metrics.get("decision_threshold", 0.5)
    return out


def classify(probability: float, actual: bool | None, thr: float) -> str:
    if actual is None:
        return "PENDING"
    pred = probability >= thr
    if pred and actual:
        return "TP"
    if pred and not actual:
        return "FP"
    if not pred and not actual:
        return "TN"
    return "FN"


def _metrics(rows: list[tuple[float, bool | None, float]]) -> dict | None:
    """rows = (probability, actual, threshold). Returns calculated metrics."""
    validated = [r for r in rows if r[1] is not None]
    if not validated:
        return None
    tp = sum(1 for p, a, t in validated if classify(p, a, t) == "TP")
    fp = sum(1 for p, a, t in validated if classify(p, a, t) == "FP")
    tn = sum(1 for p, a, t in validated if classify(p, a, t) == "TN")
    fn = sum(1 for p, a, t in validated if classify(p, a, t) == "FN")
    n = len(validated)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return {
        "validated": n,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 3),
        "false_alarm_rate": round(fp / max(tp + fp, 1), 3),   # of alarms raised
        "fpr": round(fp / max(fp + tn, 1), 3),                # of negatives
        "accuracy": round((tp + tn) / n, 3),
    }


# ---------------------------------------------------------------------------
# main computation
# ---------------------------------------------------------------------------
def compute_prediction_trust(db: Session, line_id: int) -> dict:
    thr = _thresholds(db)
    preds = (db.query(Prediction, Vehicle.vin)
             .join(Vehicle, Vehicle.id == Prediction.vehicle_id)
             .filter(Vehicle.line_id == line_id)
             .order_by(Prediction.created_at.desc()).all())
    versions = {m.id: m for m in db.query(ModelVersion).all()}

    # station context for each prediction = the station in the vehicle's
    # journey with the strongest anomaly signal (where risk concentrated).
    # Batched: one query for all vehicles, keep max anomaly per vehicle.
    veh_ids = [p.vehicle_id for p, _ in preds]
    anom_rows = (db.query(VehicleEvent.vehicle_id, VehicleEvent.station_id,
                          func.max(VehicleEvent.anomaly_score))
                 .filter(VehicleEvent.vehicle_id.in_(veh_ids),
                         VehicleEvent.anomaly_score.isnot(None))
                 .group_by(VehicleEvent.vehicle_id, VehicleEvent.station_id).all())
    best_anom: dict[int, tuple[int, float]] = {}
    for vid, sid, asc in anom_rows:
        if asc is None:
            continue
        if vid not in best_anom or asc > best_anom[vid][1]:
            best_anom[vid] = (sid, asc)
    st_codes = {s.id: s.code for s in db.query(Station).all()}

    def _station_of(p: Prediction) -> str | None:
        sid, asc = best_anom.get(p.vehicle_id, (None, 0.0))
        if sid and asc > 0.2:
            return st_codes.get(sid)
        return None

    rows = []
    for p, vin in preds:
        rows.append({"id": p.id, "vehicle_id": p.vehicle_id, "vin": vin,
                     "created_at": p.created_at, "probability": p.defect_probability,
                     "confidence": p.confidence, "actual": p.outcome,
                     "model_version": versions[p.model_version_id].version if p.model_version_id in versions else "?",
                     "station": _station_of(p),
                     "result": classify(p.defect_probability, p.outcome, thr.get(p.model_version_id, 0.5))})
    validated = [r for r in rows if r["actual"] is not None]
    pending = [r for r in rows if r["actual"] is None]

    def _thr_for(version: str) -> float:
        return thr.get(next((k for k, m in versions.items() if m.version == version), 0), 0.5)

    overall = _metrics([(r["probability"], r["actual"], _thr_for(r["model_version"]))
                        for r in rows])

    # ---- station-level trust (attributed to the station context at prediction time) ----
    station_rows: dict[str, list[dict]] = {}
    for r in rows:
        if r["station"]:
            station_rows.setdefault(r["station"], []).append(r)
    station_trust = []
    for code, srows in station_rows.items():
        m = _metrics([(r["probability"], r["actual"], _thr_for(r["model_version"]))
                      for r in srows])
        if not m:
            continue
        station_trust.append({"station": code,
                              "predictions": len(srows),
                              "validated": m["validated"],
                              "precision": m["precision"],
                              "recall": m["recall"],
                              "false_alarm_rate": m["false_alarm_rate"],
                              "tp": m["tp"], "fp": m["fp"]})
    station_trust.sort(key=lambda s: -s["precision"])

    # ---- false-alarm monitor + trend over time buckets ----
    far = overall["false_alarm_rate"] if overall else 0.0
    worst = max(station_trust, key=lambda s: s["false_alarm_rate"]) if station_trust else None
    far_station = worst["station"] if worst else None
    trend = []
    if validated and overall:
        tmin = min(r["created_at"] for r in rows) if rows else 0
        tmax = max(r["created_at"] for r in rows) if rows else 1
        span = max(tmax - tmin, 1.0)
        nb = 6
        for i in range(nb):
            a = tmin + span * i / nb
            b = tmin + span * (i + 1) / nb
            seg = [r for r in rows if r["actual"] is not None and a <= r["created_at"] < b]
            alarms = [r for r in seg if r["result"] in ("TP", "FP")]
            fps = [r for r in seg if r["result"] == "FP"]
            if alarms:
                trend.append({"bucket": i + 1,
                              "alarms": len(alarms),
                              "false_alarm_rate": round(len(fps) / len(alarms), 3)})
        direction = ("increasing" if len(trend) >= 2 and trend[-1]["false_alarm_rate"] > trend[-2]["false_alarm_rate"]
                     else "stable")

    # ---- confidence vs outcome bins ----
    bins = []
    if validated:
        for lo, hi in ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)):
            seg = [r for r in validated if lo <= r["probability"] < hi]
            if seg:
                correct = sum(1 for r in seg if r["result"] in ("TP", "TN"))
                bins.append({"range": f"{lo*100:.0f}–{min(hi,1)*100:.0f}%",
                             "n": len(seg),
                             "correct_rate": round(correct / len(seg), 3)})

    # ---- observability connection (may be affected, not caused) ----
    dq = {r["code"]: r for r in compute_station_data_quality(db, line_id, persist=False)}
    obs_notes = []
    for s in station_trust:
        row = dq.get(s["station"], {})
        if s["precision"] < 0.75 and row.get("sensor_coverage", 1) < 0.5:
            obs_notes.append({"station": s["station"],
                              "precision": s["precision"],
                              "coverage": row.get("sensor_coverage", 0),
                              "analytics_confidence": row.get("analytics_confidence", 0),
                              "note": ("Prediction reliability may be affected by incomplete "
                                       "sensor coverage at this station.")})

    # ---- model lifecycle ----
    prod = (db.query(ModelVersion).filter(ModelVersion.name == "defect_risk",
                                          ModelVersion.status == "production")
            .order_by(ModelVersion.id.desc()).first())
    cand = (db.query(ModelVersion).filter(ModelVersion.name == "defect_risk",
                                          ModelVersion.status.in_(["candidate", "approved"]))
            .order_by(ModelVersion.id.desc()).first())
    win = maintenance_windows(db, line_id)
    model_management = {
        "production": {"id": prod.id, "version": prod.version,
                       "metrics": prod.metrics, "trained_at": prod.trained_at,
                       "status": prod.status} if prod else None,
        "candidate": {"id": cand.id, "version": cand.version,
                      "metrics": cand.metrics, "trained_at": cand.trained_at,
                      "status": cand.status} if cand else None,
        "next_window_start": win["next_window_start"],
        "countdown_s": win["countdown_s"],
        "window_label": win["window_label"],
    }

    return {
        "generated_at": last_sim_time(db),
        "note": TRUST_NOTE,
        "overall": {**(overall or {"validated": 0}),
                    "pending": len(pending),
                    "validated": overall["validated"] if overall else 0,
                    "insufficient": overall is None},
        "history": rows[:200],
        "station_trust": station_trust,
        "false_alarm_monitor": {"rate": far, "worst_station": far_station,
                                "alarms": sum(1 for r in validated if r["result"] in ("TP", "FP")),
                                "false_alarms": sum(1 for r in validated if r["result"] == "FP"),
                                "trend": trend, "direction": direction},
        "confidence_bins": bins,
        "observability_notes": obs_notes,
        "model_management": model_management,
    }


# ---------------------------------------------------------------------------
# candidate revalidation / approval / controlled deployment
# ---------------------------------------------------------------------------
def retrain_candidate(db: Session, line_id: int) -> dict:
    """Revalidate on the validated corpus: search a decision threshold that
    improves precision/false-alarm rate. Creates a CANDIDATE model row only —
    production is untouched until approval + maintenance-window deployment."""
    prod = (db.query(ModelVersion).filter(ModelVersion.name == "defect_risk",
                                          ModelVersion.status == "production")
            .order_by(ModelVersion.id.desc()).first())
    if not prod:
        return {"error": "no production defect_risk model"}
    rows = (db.query(Prediction, Vehicle.vin)
            .join(Vehicle, Vehicle.id == Prediction.vehicle_id)
            .filter(Vehicle.line_id == line_id,
                    Prediction.outcome.isnot(None)).all())
    if len(rows) < 100:
        return {"error": INSUFFICIENT,
                "note": "Revalidation requires at least 100 validated predictions."}
    probs = [(p.defect_probability, p.outcome) for p, _ in rows]
    base_thr = prod.metrics.get("decision_threshold", 0.5)
    base = _metrics([(p, a, base_thr) for p, a in probs])

    # candidate: threshold re-tuned on the validated corpus (max F1 with
    # precision not below production's)
    best, best_m = None, None
    for thr in [round(x, 2) for x in
                [base_thr + d for d in (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15)]]:
        if not (0.15 <= thr <= 0.85):
            continue
        m = _metrics([(p, a, thr) for p, a in probs])
        if not m:
            continue
        if base is None or m["precision"] >= base["precision"] - 0.01:
            if best_m is None or m["f1"] > best_m["f1"]:
                best, best_m = thr, m
    if best is None:
        best, best_m = base_thr, base

    version = f"1.{int(prod.version.split('.')[1]) + 1}"
    mv = ModelVersion(
        name="defect_risk", algo=prod.algo, version=version,
        trained_at=last_sim_time(db),
        metrics={**best_m, "decision_threshold": best,
                 "base_threshold": base_thr,
                 "validated_samples": len(probs),
                 "candidate_note": ("candidate revalidation — decision threshold "
                                    "re-tuned on the validated outcome corpus")},
        artifact_path=prod.artifact_path,   # revalidation, not a new artifact
        notes="candidate revalidation — awaiting human approval",
        status="candidate")
    db.add(mv)
    db.commit()
    return {"candidate_version": mv.version,
            "current": {"version": prod.version, **base} if base else {"version": prod.version},
            "candidate": best_m,
            "improvement": {"precision_delta": round((best_m["precision"] - base["precision"]), 3)
                            if base else None,
                            "false_alarm_delta": round((best_m["false_alarm_rate"] - base["false_alarm_rate"]), 3)
                            if base else None},
            "note": "Production model is NOT changed. Candidate requires approval + "
                    "maintenance-window deployment."}


def approve_candidate(db: Session, line_id: int, approve: bool) -> dict:
    cand = (db.query(ModelVersion).filter(ModelVersion.name == "defect_risk",
                                          ModelVersion.status == "candidate")
            .order_by(ModelVersion.id.desc()).first())
    if not cand:
        return {"error": "no candidate model awaiting approval"}
    if not approve:
        cand.status = "superseded"
        db.commit()
        return {"status": "rejected", "candidate": cand.version,
                "note": "Candidate rejected — production model unchanged."}
    win = maintenance_windows(db, line_id)
    cand.status = "approved"
    db.add(MaintenanceQueueItem(
        line_id=line_id, scenario_id=None, station_code="—",
        change=f"Deploy AI prediction model v{cand.version} (candidate revalidation)",
        priority="medium", risk_level="low", estimated_duration_min=15,
        target_window=win["next_window_start"], status="queued", created_at=last_sim_time(db),
        item_type="model_deploy"))
    db.commit()
    return {"status": "approved",
            "candidate": cand.version,
            "message": f"Deployment scheduled for the next maintenance window ({win['window_label']}).",
            "target_window": win["next_window_start"],
            "countdown_s": win["countdown_s"],
            "note": "Approved for controlled deployment — the model will not be live "
                    "until the maintenance window executes."}


def deploy_candidate(db: Session, line_id: int, simulate_window: bool = False) -> dict:
    """Controlled deployment — backend-enforced maintenance-window gating.

    Deployment is ONLY allowed during a scheduled maintenance window.
    Outside the window the request is rejected with a clear message;
    the prototype may explicitly *simulate* window execution
    (simulate_window=True, clearly labeled) so the workflow can be
    demonstrated without pretending to control a real PLC."""
    cand = (db.query(ModelVersion).filter(ModelVersion.name == "defect_risk",
                                          ModelVersion.status == "approved")
            .order_by(ModelVersion.id.desc()).first())
    if not cand:
        return {"error": "no approved candidate awaiting deployment"}
    win = maintenance_windows(db, line_id)
    now = win["now"]
    in_window = win["next_window_start"] <= now <= win["next_window_end"]
    if not in_window and not simulate_window:
        return {"error": ("Deployment rejected — currently outside the scheduled "
                          "maintenance window. Deployment is only permitted during "
                          f"a maintenance window (next: {win['window_label']}, "
                          f"in {win['countdown_s']/3600:.1f}h)."),
                "status": "blocked"}
    prod = (db.query(ModelVersion).filter(ModelVersion.name == "defect_risk",
                                          ModelVersion.status == "production").all())
    for m in prod:
        m.status = "superseded"
    cand.status = "production"
    (db.query(MaintenanceQueueItem)
     .filter(MaintenanceQueueItem.item_type == "model_deploy",
             MaintenanceQueueItem.change.like(f"%{cand.version}%"))
     .update({"status": "complete"}))
    db.commit()
    return {"deployed": cand.version,
            "simulated": simulate_window,
            "note": ("Controlled deployment executed via the maintenance window — "
                     "candidate is now the production model." +
                     (" (window execution simulated in the prototype)" if simulate_window else ""))}
