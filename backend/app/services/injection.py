"""Scenario injection layer — LIVE TWIN CONTINUATION for demos and drills.

Not a mock, not a re-run: the assembly line continues from its last simulated
timestamp with one disruption knob turned up. New vehicles flow through the
same SimPy engine (fresh seeds derived per injection, so the log stays
replayable from any DB state), ingest appends to the existing database
(append-mode topology reuse), and analytics refresh: anomalies rescore, data
quality recomputes, recommendations regenerate. The dashboards then update on
their normal polling cycle — the twin visibly REACTS.

Four injected disruptions map to the thesis mechanisms:
  tool_drift_surge      -> mechanism A (tool wear) — torque instability, maintenance downtime
  supplier_batch_failure-> mechanism B — correlated scrap cluster + batch-cluster RCA evidence
  sensor_outage         -> observability/completeness collapse (data-quality story)
  bottleneck_shock      -> shadowing-effect reveal: full-history BN stays S17,
                           windowed BN top flips to the shocked station
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from ..ingestion.base import DataSource
from ..ingestion.pipeline import IngestionPipeline
from ..ingestion.simulator_source import _CallbackSink
from ..models import Station, Vehicle, VehicleEvent
from ..simulation.engine import LineSim
from ..ml import anomaly as anomaly_service
from . import data_quality as dq_service
from . import recommendations as rec_service

DEFAULT_TARGET = "S20"

INJECTION_KINDS: list[dict[str, Any]] = [
    {"kind": "tool_drift_surge", "title": "Tool drift surge",
     "description": "Torque tools start 80% worn and wear accelerates 8×. Expect: "
                    "torque instability, anomaly alerts, maintenance downtime events, "
                    "new wear-based advisory recommendations."},
    {"kind": "supplier_batch_failure", "title": "Bad supplier batches",
     "description": "The next 4 component batches are deterministically bad (+35% "
                    "baseline bad-batch rate after). Expect: correlated scrap cluster, "
                    "batch-cluster evidence in contributing factors, quarantine advice."},
    {"kind": "sensor_outage", "title": "Plant-wide sensor outage",
     "description": "60% of sensor samples dropped during the injection window. Expect: "
                    "falling completeness/freshness and visible analytics-confidence loss "
                    "— the twin reports its own blind spots."},
    {"kind": "bottleneck_shock", "title": "Flow shock at one station",
     "description": "Target station slowed to ~2.6× nominal cycle (enough to sit above "
                    "takt, like a machine fault). Expect: the full-history ranking keeps "
                    "S17 on top, while the WINDOWED view crowns the shocked station — "
                    "the shadowing effect, demonstrated live."},
]


def describe_kinds() -> list[dict[str, Any]]:
    return INJECTION_KINDS


class _InjectionSource(DataSource):
    """Simulator-backed continuation run (fresh engine, absolute-timestamped events)."""

    name = "simulator"

    def __init__(self, cfg: dict, kind: str, seed: int, vehicles: int,
                 max_seconds: float, t_offset: float, part_offset: int,
                 target_station: str | None):
        self.cfg = cfg
        self.kind = kind
        self.seed = seed
        self.vehicles = vehicles
        self.max_seconds = max_seconds
        self.t_offset = t_offset
        self.part_offset = part_offset
        self.target_station = target_station

    def get_site_config(self) -> dict[str, Any]:
        return self.cfg

    def stream(self, emit) -> dict[str, Any]:
        sink = _CallbackSink(emit, t_offset=self.t_offset)
        sim = LineSim(self.cfg, seed=self.seed, sink=sink)
        sim.parts_spawned = self.part_offset  # VIN/batch numbering continues
        batch_size = self.cfg["demand"]["batch_size_parts"]
        next_batch = self.part_offset // batch_size + 1

        if self.kind == "tool_drift_surge":
            sim.mech.m["tool_wear"]["wear_per_cycle"] *= 8.0
            for st in sim.stations:
                if st.tool:
                    sim.mech.tool_wear[st.id] = 0.8  # arrive worn (like a bad tool vendor lot)
        elif self.kind == "supplier_batch_failure":
            sim.mech.m["supplier_batch"]["bad_batch_prob"] = 0.35
            for i in range(4):
                sim.mech._batch_cache[f"B{next_batch + i:03d}"] = True
        elif self.kind == "sensor_outage":
            sim.miss_p = 0.6
        elif self.kind == "bottleneck_shock":
            target = self.target_station or DEFAULT_TARGET
            hits = [st for st in sim.stations if st.id == target]
            if not hits:
                raise ValueError(f"unknown target station for shock: {target}")
            # 2.6x pushes even mid-headroom stations above takt (fault-like
            # slowdown); a milder shock on a low-util station can't beat S17's
            # engineered saturation inside the window (verified live).
            hits[0].mu *= 2.6

        summary = sim.run_target(self.vehicles, max_until=self.max_seconds)
        # LineSim counts from part_offset (set pre-run) — report ONLY this window
        summary["spawned"] = int(summary.get("spawned", 0)) - self.part_offset
        summary["injection_kind"] = self.kind
        summary["t_offset"] = self.t_offset
        return summary


def run_injection(db: Session, line_id: int, session_factory: sessionmaker,
                  kind: str, vehicles: int = 300, seed: int | None = None,
                  target_station: str | None = None) -> dict[str, Any]:
    """Continue the twin with an injected disruption + refresh analytics.

    Raises ValueError for invalid inputs (translated to 400 by the API layer).
    """
    if kind not in {k["kind"] for k in INJECTION_KINDS}:
        raise ValueError(f"unknown injection kind '{kind}'")

    settings = get_settings()
    cfg = yaml.safe_load(Path(settings.site_config).read_text())
    cfg = copy.deepcopy(cfg)

    # validate target station against the ACTUAL line in the DB
    if kind == "bottleneck_shock":
        target = target_station or DEFAULT_TARGET
        known = {c for (c,) in db.query(Station.code)
                 .filter(Station.line_id == line_id).all()}
        if target not in known:
            raise ValueError(f"target station '{target}' not on this line "
                             f"(valid: S01..S{len(known):02d})")
        target_station = target

    t_max = db.query(func.max(VehicleEvent.exited_at)).scalar() or 0.0
    t_offset = float(t_max) + 60.0
    part_offset = db.query(func.count(Vehicle.id)).scalar() or 0
    eff_seed = (seed if seed is not None else 10_000 + int(part_offset))
    max_seconds = min(settings.max_sim_seconds, 250_000.0)

    src = _InjectionSource(cfg, kind, eff_seed, vehicles, max_seconds,
                           t_offset, part_offset, target_station)
    summary = IngestionPipeline(session_factory).ingest(src, append=True)

    # refresh analytics so the twin "reacts" immediately
    db2 = session_factory()
    try:
        anomalies = anomaly_service.detect_anomalies(db2, line_id)
        dq_rows = len(dq_service.compute_station_data_quality(db2, line_id,
                                                              persist=True))
        recs = rec_service.generate_recommendations(db2, line_id)
        new_t_max = db2.query(func.max(VehicleEvent.exited_at)).scalar() or t_offset
        total_vehicles = db2.query(func.count(Vehicle.id)).scalar()
    finally:
        db2.close()

    guides = {
        "tool_drift_surge": "Supervisor: anomaly feed lights up at torque stations; "
                            "station drawer shows torque std rising; recommendations "
                            "add tool-service advisories.",
        "supplier_batch_failure": "Open a scrapped vehicle from the injected window → "
                                  "contributing factors → batch-cluster evidence; "
                                  "recommendations advise quarantine of remaining batch stock.",
        "sensor_outage": "Manager → observability column 'conf' drops; data-quality "
                         "banners explain WHY confidence fell (no silent gaps).",
        "bottleneck_shock": "Manager tab → bottleneck panel → switch window to "
                            "'last 2h': the shocked station tops the ranking while "
                            "full history still crowns S17 (shadowing effect).",
    }
    return {
        "status": "injected",
        "kind": kind,
        "target_station": target_station,
        "seed": eff_seed,
        "sim_window": {"t_start": round(t_offset, 1), "t_end": round(float(new_t_max), 1)},
        "vehicles": {"injected_spawned": summary.get("spawned"),
                     "injected_completed": summary.get("completed"),
                     "injected_scrapped": summary.get("scrapped"),
                     "fleet_total": total_vehicles},
        "events_added": summary.get("event_counts", {}),
        "analytics_refresh": {
            "anomalies_written": anomalies.get("anomalies_written"),
            "events_scored": anomalies.get("events_scored"),
            "data_quality_rows": dq_rows,
            "recommendations": recs,
        },
        "demo_guides": {
            "what_to_show": guides[kind],
            "defect_risk_note": "Defect-risk predictions are NOT rescored by injection "
                                "(fast demo path). Use the Retrain & rescore button "
                                "(POST /ml/refresh) to train v-next and rescore the fleet.",
        },
    }
