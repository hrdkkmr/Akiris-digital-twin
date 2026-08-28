"""Business / ROI service — configurable assumptions, auditable math.

Never claims "AI reduces defects by X%". Computes: current-state metrics from
the twin; scenario grid where improvement % is an EXPLICIT, labeled assumption.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import (Defect, MachineEvent, Station, StationKpi, Vehicle,
                      VehicleEvent)
from .twin_state import last_sim_time


def production_summary(db: Session, line_id: int) -> dict:
    now = last_sim_time(db)
    v = db.query(Vehicle.status, func.count()).group_by(Vehicle.status).all()
    by_status = dict(v)
    total = sum(by_status.values())
    completed = by_status.get("completed", 0)
    scrapped = by_status.get("scrapped", 0)

    span = (db.query(func.max(Vehicle.completed_at)).scalar() or now) - \
           (db.query(func.min(Vehicle.started_at)).scalar() or 0)
    span = max(span, 1.0)

    lead = (db.query(func.avg(Vehicle.completed_at - Vehicle.started_at))
            .filter(Vehicle.status == "completed").scalar())

    zone_defects = (db.query(Station.zone, func.count())
                    .join(Defect, Defect.station_id == Station.id)
                    .group_by(Station.zone).all())

    # downtime from maintenance events
    events = (db.query(MachineEvent).join(Station, Station.id == MachineEvent.station_id)
              .filter(Station.line_id == line_id)
              .order_by(MachineEvent.station_id, MachineEvent.t).all())
    open_at, downtime = {}, {}
    for e in events:
        if e.event == "maintenance_start":
            open_at[e.station_id] = e.t
        elif e.event == "maintenance_end" and e.station_id in open_at:
            downtime[e.station_id] = downtime.get(e.station_id, 0.0) + e.t - open_at.pop(e.station_id)

    return {
        "generated_at": round(now, 1),
        "span_hours": round(span / 3600, 2),
        "vehicles_total": total,
        "completed": completed,
        "scrapped": scrapped,
        "wip": by_status.get("wip", 0),
        "fpy": round(1 - scrapped / max(total, 1), 4),
        "throughput_per_hour": round(completed / span * 3600, 1),
        "avg_lead_time_s": round(lead, 1) if lead else None,
        "defects_by_zone_found": dict(zone_defects),
        "maintenance_downtime_min": round(sum(downtime.values()) / 60, 1),
    }


def roi_report(db: Session, line_id: int) -> dict:
    s = get_settings()
    summary = production_summary(db, line_id)
    produced = max(summary["vehicles_total"], 1)
    scale = s.planned_annual_vehicles / produced   # extrapolation factor (labeled)

    defect_cost_sim = summary["scrapped"] * s.cost_per_scrapped_vehicle
    downtime_hours = summary["maintenance_downtime_min"] / 60
    downtime_cost_sim = downtime_hours * s.cost_downtime_per_hour

    improvement_grid = []
    for pct in (0.05, 0.10, 0.15, 0.20):
        improvement_grid.append({
            "assumed_defect_reduction": pct,
            "annual_savings_defects": round(defect_cost_sim * scale * pct, 0),
            "assumed_downtime_reduction": s.assumed_downtime_reduction_pct,
            "annual_savings_downtime": round(downtime_cost_sim * scale
                                             * s.assumed_downtime_reduction_pct, 0),
        })

    return {
        "disclaimer": ("All financial figures are SIMULATED estimates from configurable "
                       "assumptions. Improvement percentages are scenarios, not claims."),
        "assumptions": {
            "cost_per_scrapped_vehicle": s.cost_per_scrapped_vehicle,
            "cost_downtime_per_hour": s.cost_downtime_per_hour,
            "planned_annual_vehicles": s.planned_annual_vehicles,
            "extrapolation_factor": round(scale, 1),
        },
        "current_state": {
            "sim_defect_cost": round(defect_cost_sim, 0),
            "sim_downtime_cost": round(downtime_cost_sim, 0),
            "annualized_defect_cost": round(defect_cost_sim * scale, 0),
            "annualized_downtime_cost": round(downtime_cost_sim * scale, 0),
        },
        "improvement_scenarios": improvement_grid,
    }
