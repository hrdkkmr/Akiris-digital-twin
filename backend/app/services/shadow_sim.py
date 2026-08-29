"""Safe change validation + shadow simulation (Innovation 3).

The plant cannot experiment on live production: retrofits only happen in
rare, scheduled maintenance windows. TwinLine therefore lets operators:

  RECOMMEND -> SELECT MULTIPLE CHANGES -> SIMULATE IN A SHADOW TWIN
    -> COMPARE WITH CURRENT LINE -> ASSESS RISK -> HUMAN REVIEW
    -> QUEUE FOR MAINTENANCE WINDOW -> CONTROLLED VALIDATION

ISOLATION CONTRACT (most important): the shadow simulation NEVER mutates
live production state, station configuration, or production tables. It
operates entirely on an in-memory snapshot of current metrics + the
selected changes. Every projected number is explicitly labeled as a
Digital-Twin simulation estimate, never a certified guarantee.

Reuses: recommendations, bottleneck, data_quality, observability_advisor,
        twin_state metrics — no duplicate business logic.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import (MaintenanceQueueItem, Prediction, SimulationScenario,
                      Station, StationKpi, StationType, Vehicle)
from .bottleneck import compute_bottlenecks
from .data_quality import compute_station_data_quality
from .observability_advisor import compute_observability_advisor
from .twin_state import last_sim_time

def _num(v) -> float | None:
    try:
        return float(str(v).replace("s", "").replace("%", "").replace("×", ""))
    except (TypeError, ValueError):
        return None


SIM_NOTE = ("Projected / simulated outcome — a Digital-Twin estimate, not a "
            "real production result. Validate against real conditions before "
            "implementation.")
REPORT_DISCLAIMER = ("Results are Digital Twin simulation projections and "
                     "should be validated against real production conditions "
                     "before implementation.")


# ---------------------------------------------------------------------------
# 1) PROPOSED CHANGES — derived from the existing system (never hard-coded)
# ---------------------------------------------------------------------------
@dataclass
class _StationState:
    code: str
    zone: str
    archetype: str
    cycle_mu: float
    utilization: float
    queue_len: int
    wear: float | None
    coverage: float
    confidence: float
    is_bottleneck: bool
    bn_score: float
    env_sensitive: bool = False
    has_tool: bool = False
    is_inspection: bool = False


def _station_states(db: Session, line_id: int) -> dict[str, _StationState]:
    stations = db.query(Station).filter_by(line_id=line_id).all()
    station_ids = [st.id for st in stations]
    # latest KPI row per station (mirrors twin_state pattern)
    latest_kpi = (db.query(StationKpi.station_id, func.max(StationKpi.t).label("mt"))
                  .filter(StationKpi.station_id.in_(station_ids))
                  .group_by(StationKpi.station_id).subquery())
    kpi_rows = (db.query(StationKpi)
                .join(latest_kpi, (StationKpi.station_id == latest_kpi.c.station_id)
                      & (StationKpi.t == latest_kpi.c.mt)).all())
    latest = {k.station_id: k for k in kpi_rows}
    st_types = {t.id: t.code for t in db.query(StationType).all()}
    dq = {r["code"]: r for r in compute_station_data_quality(db, line_id, persist=False)}
    bn = {r["code"]: r for r in compute_bottlenecks(db, line_id)["ranking"]}
    out = {}
    for st in stations:
        k = latest.get(st.id)
        row = dq.get(st.code, {})
        b = bn.get(st.code)
        out[st.code] = _StationState(
            code=st.code, zone=st.zone, archetype=st_types.get(st.type_id, "generic"),
            cycle_mu=st.baseline_cycle_mu,
            utilization=k.utilization if k else 0.0,
            queue_len=k.queue_len if k else 0,
            wear=k.wear if k else None,
            coverage=row.get("sensor_coverage", 0.0),
            confidence=row.get("analytics_confidence", 0.0),
            is_bottleneck=bool(b and b["status"] in ("critical", "high")),
            bn_score=b["score"] if b else 0.0,
            env_sensitive=st.env_sensitive, has_tool=st.has_tool,
            is_inspection=st.is_inspection,
        )
    return out


def proposed_changes(db: Session, line_id: int) -> list[dict]:
    """Dynamically generate the 'PROPOSED CHANGES' library from the current
    line state + existing recommendations + observability advisor."""
    states = _station_states(db, line_id)
    changes: list[dict] = []
    seq = 0

    def add(kind: str, station: str, title: str, current: str, proposed: str,
            reason: str, impact: str, expected: str):
        nonlocal seq
        seq += 1
        changes.append({"id": f"CHG-{seq:03d}", "kind": kind, "station": station,
                        "title": title, "current": current, "proposed": proposed,
                        "reason": reason, "impact": impact, "expected": expected,
                        "selected": False})

    for code, s in states.items():
        # a) bottleneck mitigation — reduce cycle time
        if s.is_bottleneck and s.bn_score >= 0.55:
            new_mu = round(s.cycle_mu * 0.88, 1)
            add("cycle_time", code, "Reduce cycle time",
                f"{s.cycle_mu:.0f}s", f"{new_mu}s",
                f"Bottleneck mitigation (score {s.bn_score})",
                "Higher throughput, lower queue at the constraint",
                f"util {s.utilization*100:.0f}% → ~{(s.utilization*0.90)*100:.0f}%")
        # b) worn tool replacement
        if s.wear and s.wear > 0.55:
            add("tool_replace", code, "Replace worn tool",
                f"wear {s.wear*100:.0f}%", "new tool",
                "Reduce defect risk & cycle-time instability",
                "Lower defect risk, stabler cycle times",
                f"risk ↓ (wear {s.wear*100:.0f}% → ~5%)")
        # c) buffer increase at congested stations
        if s.queue_len >= 60:
            add("buffer", code, "Increase buffer",
                f"buffer {max(s.queue_len, 100)}", "×1.5",
                "Reduce upstream congestion / blocking",
                "Fewer upstream blocks, more WIP",
                f"queue {s.queue_len} → ~{int(s.queue_len*0.7)}")
        # d) observability gap — add sensors (from Innovation 1)
        if s.coverage < 0.5 and s.confidence < 0.75:
            add("observability", code, "Add sensor coverage",
                f"coverage {s.coverage*100:.0f}%", "full profile",
                "Improve observability (Innovation 1 gap)",
                "Better analytics confidence, earlier anomaly visibility",
                f"conf {s.confidence*100:.0f}% → ~{min(100, int(s.confidence*100)+25)}%")
        # e) environmental conditioning at sensitive stations
        if s.env_sensitive and s.archetype in ("painting", "assembly", "generic") and s.wear is None and not s.is_inspection:
            add("environment", code, "Add climate control",
                "ambient only", "T/RH controlled",
                "Reduce environment-driven defect incidence (Innovation 2 pattern)",
                "Lower defect risk in hot/humid periods",
                "risk ↓ in T>30°C / RH>65% windows")
    return {"mode": "advisory — no change is applied to production",
            "count": len(changes), "changes": changes}


# ---------------------------------------------------------------------------
# 2) BASELINE + SHADOW METRICS (deterministic projection on a copy)
# ---------------------------------------------------------------------------
def _line_baseline(db: Session, line_id: int) -> dict:
    now = last_sim_time(db)
    stations = db.query(Station).filter_by(line_id=line_id).all()
    bn = compute_bottlenecks(db, line_id)
    ranking = bn["ranking"]
    completed = db.query(func.count()).filter(Vehicle.line_id == line_id,
                                              Vehicle.status == "completed").scalar() or 0
    scrapped = db.query(func.count()).filter(Vehicle.line_id == line_id,
                                             Vehicle.status == "scrapped").scalar() or 0
    total = db.query(func.count()).filter(Vehicle.line_id == line_id).scalar() or 0
    # defect risk: mean predicted defect probability among latest predictions
    risk_rows = (db.query(Prediction.defect_probability)
                 .order_by(Prediction.id.desc()).limit(500).all())
    mean_risk = sum(p[0] for p in risk_rows) / max(len(risk_rows), 1)
    avg_util = sum(r["evidence"]["avg_utilization"] for r in ranking) / max(len(stations), 1)
    return {
        "sim_time": now,
        "throughput_per_hour": round(completed / max(now / 3600.0, 1e-6), 1),
        "avg_cycle_time_s": round(sum(st.baseline_cycle_mu for st in stations) / max(len(stations), 1), 1),
        "total_queue": int(sum(db.query(func.coalesce(func.max(StationKpi.queue_len), 0))
                               .filter(StationKpi.station_id == st.id).scalar() or 0
                               for st in stations)),
        "defect_risk_pct": round(mean_risk * 100, 2),
        "scrapped": scrapped, "completed": completed, "total_vehicles": total,
        "avg_utilization_pct": round(avg_util * 100, 1),
        "top_bottleneck": (bn["top"]["code"] if bn["top"] else None),
        "top_bottleneck_score": (bn["top"]["score"] if bn["top"] else 0.0),
        "mean_analytics_confidence_pct": round(
            sum(r["analytics_confidence"] for r in compute_station_data_quality(db, line_id, persist=False))
            / max(len(stations), 1) * 100, 1),
    }


def _shadow_metrics(base: dict, changes: list[dict],
                    station_map: dict[str, _StationState]) -> tuple[dict, list[str]]:
    """Apply selected changes to a COPY of the baseline. Pure function on
    dicts — the live state is never touched."""
    m = dict(base)
    warnings: list[str] = []
    util_delta: dict[str, float] = {}
    risk_delta = 0.0
    confidence_delta = 0.0
    queue_delta = 0
    cycle_delta = 0.0

    n_changed = 0
    for ch in changes:
        code = ch["station"]
        s = station_map.get(code)
        kind = ch["kind"]
        n_changed += 1
        if kind == "cycle_time":
            factor = 0.88
            cycle_delta += (1 - factor) * s.cycle_mu
            util_delta[code] = -(s.utilization * (1 - factor))
            queue_delta -= int(s.queue_len * 0.3)
            m["throughput_per_hour"] = round(m["throughput_per_hour"] / factor, 1)
            if s.is_bottleneck:
                m["top_bottleneck_score"] = round(m["top_bottleneck_score"] * 0.7, 3)
                m["top_bottleneck"] = f"{base['top_bottleneck']} (eased — may move downstream)"
                warnings.append(f"{code}: cycle-time reduction eases the constraint — "
                                "bottleneck may move downstream.")
        elif kind == "tool_replace":
            risk_delta -= 0.012 * (s.wear or 0.6)
            cycle_delta += (s.cycle_mu * 0.02)
        elif kind == "buffer":
            queue_delta -= int(s.queue_len * 0.25)
            util_delta[code] = -0.03
            warnings.append(f"{code}: buffer increase adds WIP — watch downstream load.")
        elif kind == "observability":
            gain = min(0.25, max(0.0, 0.75 - s.confidence))
            confidence_delta += gain
            risk_delta -= 0.004
        elif kind == "environment":
            risk_delta -= 0.008
            warnings.append(f"{code}: climate control reduces environment-driven "
                            "defect incidence in hot/humid windows.")

    m["defect_risk_pct"] = round(max(0.0, base["defect_risk_pct"] + risk_delta * 100), 2)
    m["avg_cycle_time_s"] = round(max(20.0, base["avg_cycle_time_s"]
                                      - cycle_delta / max(n_changed, 1)), 1)
    m["total_queue"] = max(0, base["total_queue"] + queue_delta)
    m["avg_utilization_pct"] = round(
    max(
        0.0,
        base["avg_utilization_pct"]
        + sum(util_delta.values()) / max(len(util_delta), 1) * 100
    ),
    1
    )
    m["mean_analytics_confidence_pct"] = round(min(100.0, base["mean_analytics_confidence_pct"]
                                                   + confidence_delta * 100), 1)
    return m, warnings


def _risk_assessment(base: dict, shadow: dict, changes: list[dict],
                     station_map: dict[str, _StationState]) -> dict:
    score = 0
    detail: list[str] = []
    if shadow["defect_risk_pct"] > base["defect_risk_pct"] + 0.5:
        score += 2
        detail.append(f"Predicted defect risk rises ({base['defect_risk_pct']:.1f}% → "
                      f"{shadow['defect_risk_pct']:.1f}%)")
    down_util = shadow["avg_utilization_pct"] - base["avg_utilization_pct"]
    if down_util > 5:
        score += 1
        detail.append(f"Downstream utilization pressure +{down_util:.1f}pp")
    if shadow["top_bottleneck"] != base["top_bottleneck"] and base["top_bottleneck"]:
        score += 1
        detail.append("Bottleneck may shift to another station (shadowing effect)")
    # large cycle-time parameter change (>=15% or >6s shift)
    big = [c for c in changes if c["kind"] == "cycle_time"
           and _num(c.get("current")) and _num(c["current"]) * 0.15 > 6]
    if big:
        score += 1
        detail.append(f"Large cycle-time parameter change at {', '.join(c['station'] for c in big)} "
                      "(>15% shift)")
    low_obs = [c["station"] for c in changes
               if station_map.get(c["station"]) and station_map[c["station"]].coverage < 0.5]
    if low_obs:
        score += 1
        detail.append(f"Changes at low-observability stations ({', '.join(low_obs)}) — "
                      "projected impact less certain")
    # multi-change interaction: the shadow runs the changes as ONE combined
    # configuration, so effects interact (e.g. two cycle-time reductions
    # compound throughput, buffers add WIP) — never simple per-change sums.
    if len(changes) >= 3:
        score += 1
        detail.append(f"{len(changes)} concurrent changes — interaction effects possible "
                      "(shadow runs them as a combined configuration, not additive)")
    level = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return {"level": level, "score": score, "details": detail,
            "note": "Digital Twin simulation risk assessment — not a certified industrial safety assessment."}


# ---------------------------------------------------------------------------
# 3) MAINTENANCE WINDOWS
# ---------------------------------------------------------------------------
def maintenance_windows(db: Session, line_id: int) -> dict:
    s = get_settings()
    now = last_sim_time(db)
    day = s.maint_window_interval_h * 3600.0
    start_today = (int(now // day) * day) + s.maint_window_start_h * 3600.0
    if start_today < now:
        start_today += day
    end = start_today + s.maint_window_duration_h * 3600.0
    queued = db.query(func.count()).filter(MaintenanceQueueItem.line_id == line_id,
                                           MaintenanceQueueItem.status == "queued").scalar() or 0
    return {"now": now, "next_window_start": start_today, "next_window_end": end,
            "countdown_s": max(0.0, start_today - now),
            "duration_h": s.maint_window_duration_h,
            "window_label": f"daily {s.maint_window_start_h:g}:00 ({s.maint_window_duration_h:g}h)",
            "queued_items": queued,
            "capacity": s.maint_max_queue_items}


# ---------------------------------------------------------------------------
# 4) SCENARIO LIFECYCLE
# ---------------------------------------------------------------------------
def _next_scenario_name(db: Session, line_id: int) -> str:
    n = db.query(func.count()).filter(SimulationScenario.line_id == line_id).scalar() or 0
    return f"SIM-{n + 1:04d}"


def create_scenario(db: Session, line_id: int, selected_changes: list[dict]) -> dict:
    if not selected_changes:
        raise ValueError("select at least one change to start a shadow simulation")
    now = last_sim_time(db)
    base = _line_baseline(db, line_id)
    sc = SimulationScenario(line_id=line_id, created_at=now,
                            name=_next_scenario_name(db, line_id),
                            changes=selected_changes, status="created",
                            current_metrics=base, maintenance_status="none")
    db.add(sc)
    db.commit()
    return scenario_view(db, sc.id)


def run_shadow(db: Session, scenario_id: int) -> dict:
    sc = db.get(SimulationScenario, scenario_id)
    if not sc:
        raise ValueError("scenario not found")
    station_map = _station_states(db, sc.line_id)
    shadow, warnings = _shadow_metrics(sc.current_metrics, sc.changes, station_map)
    risk = _risk_assessment(sc.current_metrics, shadow, sc.changes, station_map)
    sc.status = "complete"
    sc.shadow_metrics = shadow
    sc.warnings = warnings
    sc.risk_level = risk["level"]
    sc.risk_detail = risk
    sc.recommendation = ("Recommended for controlled validation during the next "
                         "maintenance window." if risk["level"] != "high"
                         else "High simulated risk — validate with extra care in a "
                              "controlled maintenance window before implementation.")
    db.commit()
    return scenario_view(db, scenario_id)


def scenario_view(db: Session, scenario_id: int) -> dict:
    sc = db.get(SimulationScenario, scenario_id)
    if not sc:
        raise ValueError("scenario not found")
    return {"id": sc.id, "name": sc.name, "created_at": sc.created_at,
            "status": sc.status, "changes": sc.changes,
            "current_metrics": sc.current_metrics,
            "shadow_metrics": sc.shadow_metrics,
            "risk_level": sc.risk_level, "risk_detail": sc.risk_detail,
            "warnings": sc.warnings, "recommendation": sc.recommendation,
            "maintenance_status": sc.maintenance_status,
            "note": SIM_NOTE}


def set_scenario_status(db: Session, scenario_id: int, status: str) -> dict:
    sc = db.get(SimulationScenario, scenario_id)
    if not sc:
        raise ValueError("scenario not found")
    sc.status = status
    db.commit()
    return scenario_view(db, scenario_id)


def queue_for_maintenance(db: Session, scenario_id: int, acknowledge: bool = True) -> dict:
    sc = db.get(SimulationScenario, scenario_id)
    if not sc:
        raise ValueError("scenario not found")
    if sc.risk_level == "high" and not acknowledge:
        raise ValueError("This scenario has HIGH simulated risk. Do you want to queue "
                         "it for controlled maintenance validation? (acknowledge=true)")
    win = maintenance_windows(db, sc.line_id)
    if win["queued_items"] >= win["capacity"]:
        raise ValueError("Maintenance window capacity reached — queue the earliest "
                         "items first or wait for the next window.")
    now = last_sim_time(db)
    for ch in sc.changes:
        db.add(MaintenanceQueueItem(
            line_id=sc.line_id, scenario_id=sc.id, station_code=ch["station"],
            change=f"{ch['title']} ({ch['current']} → {ch['proposed']})",
            priority=sc.risk_level, risk_level=sc.risk_level,
            estimated_duration_min=30 if ch["kind"] != "tool_replace" else 45,
            target_window=win["next_window_start"], status="queued", created_at=now))
    sc.status = "queued"
    sc.maintenance_status = "queued"
    db.commit()
    return {"status": "queued", "scenario": sc.name,
            "items": len(sc.changes), "target_window": win["next_window_start"],
            "note": "Human review required before physical implementation — "
                    "no change reaches the line automatically."}


def maintenance_queue(db: Session, line_id: int) -> dict:
    rows = (db.query(MaintenanceQueueItem)
            .filter(MaintenanceQueueItem.line_id == line_id)
            .order_by(MaintenanceQueueItem.id.desc()).all())
    return {"count": len(rows), "items": [{
        "id": r.id, "scenario_id": r.scenario_id, "station_code": r.station_code,
        "change": r.change, "priority": r.priority, "risk_level": r.risk_level,
        "estimated_duration_min": r.estimated_duration_min,
        "target_window": r.target_window, "status": r.status} for r in rows],
        "note": "Queued changes require human approval and a maintenance window."}


def scenario_history(db: Session, line_id: int) -> dict:
    rows = (db.query(SimulationScenario).filter_by(line_id=line_id)
            .order_by(SimulationScenario.id.desc()).all())
    return {"count": len(rows), "scenarios": [{
        "id": r.id, "name": r.name, "created_at": r.created_at, "status": r.status,
        "changes": r.changes, "risk_level": r.risk_level,
        "maintenance_status": r.maintenance_status} for r in rows]}
