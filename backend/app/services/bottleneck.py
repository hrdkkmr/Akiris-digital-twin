"""Bottleneck service — V1 heuristic score over real evidence.

score = 0.40·utilization + 0.25·max-queue + 0.20·cycle-deviation + 0.15·downtime
(each term max-normalized across the line)

Extension points (documented, not faked):
  - KPI-paper methods: input-side WIP queue ranking & low-demand utilization
    ranking with Bottleneck-Degree ordering (Kawabata et al. 2022)
  - IEEE CASE 2024 sensitivity analysis: throughput-sensitivity ground truth
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MachineEvent, Station, StationKpi, VehicleEvent

WEIGHTS = {"utilization": 0.40, "queue": 0.25, "cycle_dev": 0.20, "downtime": 0.15}


def _downtime_by_station(db: Session, line_id: int, t0: float) -> dict[int, float]:
    events = (db.query(MachineEvent).join(Station, Station.id == MachineEvent.station_id)
              .filter(Station.line_id == line_id, MachineEvent.t >= t0)
              .order_by(MachineEvent.station_id, MachineEvent.t).all())
    open_at: dict[int, float] = {}
    total: dict[int, float] = {}
    for e in events:
        if e.event == "maintenance_start":
            open_at[e.station_id] = e.t
        elif e.event == "maintenance_end" and e.station_id in open_at:
            total[e.station_id] = total.get(e.station_id, 0.0) + e.t - open_at.pop(e.station_id)
    return total


def compute_bottlenecks(db: Session, line_id: int, window_s: float | None = None) -> dict:
    stations = (db.query(Station).filter_by(line_id=line_id)
                .order_by(Station.seq).all())
    now = db.query(func.max(StationKpi.t)).scalar() or 0.0
    t0 = max(0.0, now - window_s) if window_s else 0.0

    kpi_rows = (db.query(StationKpi.station_id,
                         func.avg(StationKpi.utilization).label("avg_util"),
                         func.max(StationKpi.queue_len).label("max_queue"),
                         func.avg(StationKpi.queue_len).label("avg_queue"))
                .filter(StationKpi.t >= t0)
                .group_by(StationKpi.station_id).all())
    kpi = {r.station_id: r for r in kpi_rows}

    dev_rows = (db.query(VehicleEvent.station_id,
                         func.avg(func.abs(VehicleEvent.cycle_dev)).label("avg_abs_dev"),
                         func.count().label("n"))
                .filter(VehicleEvent.exited_at >= t0)
                .group_by(VehicleEvent.station_id).all())
    dev = {r.station_id: r for r in dev_rows}
    downtime = _downtime_by_station(db, line_id, t0)

    max_queue = max([kpi[r.id].max_queue for r in stations if r.id in kpi] or [1])
    max_dev = max([dev[r.id].avg_abs_dev for r in stations if r.id in dev and dev[r.id].avg_abs_dev] or [1])
    max_down = max(list(downtime.values()) or [1])

    ranking = []
    for st in stations:
        k = kpi.get(st.id)
        d = dev.get(st.id)
        util = float(k.avg_util) if k else 0.0
        queue = float(k.max_queue) if k else 0.0
        avg_dev = float(d.avg_abs_dev) if d and d.avg_abs_dev else 0.0
        down = downtime.get(st.id, 0.0)
        samples = int(d.n) if d else 0

        score = (WEIGHTS["utilization"] * util
                 + WEIGHTS["queue"] * queue / max_queue
                 + WEIGHTS["cycle_dev"] * avg_dev / max_dev
                 + WEIGHTS["downtime"] * down / max_down)
        score = round(min(max(score, 0.0), 1.0), 3)

        if util >= 0.90 or score >= 0.75:
            status = "critical"
        elif score >= 0.55:
            status = "high"
        elif score >= 0.40:
            status = "watch"
        else:
            status = "ok"
        confidence = round(min(0.95, 0.70 + 0.25 * min(samples / 200.0, 1.0)), 2)

        ranking.append({
            "station_id": st.id, "seq": st.seq, "code": st.code, "zone": st.zone,
            "score": score, "status": status, "confidence": confidence,
            "evidence": {
                "avg_utilization": round(util, 3),
                "max_queue": int(queue),
                "avg_abs_cycle_dev_s": round(avg_dev, 2),
                "downtime_s": round(down, 1),
                "baseline_cycle_mu": st.baseline_cycle_mu,
                "samples": samples,
            },
        })
    ranking.sort(key=lambda r: -r["score"])
    return {
        "generated_at": round(now, 1), "window_s": window_s,
        "method": "heuristic_v1",
        "method_note": ("Evidence-weighted composite. Extension points: Kawabata 2022 "
                        "WIP-queue & low-demand utilization (Bottleneck-Degree), IEEE CASE "
                        "2024 throughput-sensitivity ground truth."),
        "top": ranking[0] if ranking else None,
        "ranking": ranking,
    }
