"""IngestionPipeline: normalized event stream  ->  relational digital twin state.

Design rules:
  - topology comes FROM the site config (no hard-coded stations)
  - genealogy is assembled by pairing part_enter/part_exit statefully
  - sensor samples collapse to per-cycle aggregates (raw kept behind a flag)
  - inspection pass/fail is resolved when the vehicle's fate at that station
    is known (defect events arrive right after the part_exit)
  - writes are chunked bulk inserts (10k+ vehicle runs stay practical)
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from ..models import (Defect, EnvironmentSample, Inspection, MachineEvent,
                      Plant, ProductionBatch, ProductionLine, Sensor,
                      SensorReading, Station, StationKpi, StationType,
                      Vehicle, VehicleEvent)
from ..simulation.engine import Station as SimStation
from .base import DataSource


class IngestionPipeline:
    def __init__(self, session_factory: sessionmaker):
        self.sf = session_factory
        self.settings = get_settings()
        self.chunk = self.settings.bulk_chunk

    # ---------------- topology ----------------
    def _upsert_topology(self, db: Session, cfg: dict,
                         append: bool = False,
                         plant_code: str = "PLANT_A",
                         line_code: str = "LINE_A",
                         line_name: str | None = None) -> tuple[Plant, ProductionLine, dict]:
        plant = db.query(Plant).filter_by(code=plant_code).first()
        if not plant:
            plant = Plant(code=plant_code, name=cfg["site"]["name"].split("—")[0].strip(),
                          industry=cfg["site"].get("industry", "automotive"),
                          location=cfg["site"].get("location"),
                          description=cfg["site"].get("description"))
            db.add(plant)
            db.flush()
        line = (db.query(ProductionLine)
                .filter_by(plant_id=plant.id, code=line_code).first())
        if not line:
            line = ProductionLine(
                plant_id=plant.id, code=line_code,
                name=line_name or cfg["site"]["name"],
                description=cfg["site"].get("line_description"),
                takt_seconds=cfg["demand"]["interarrival_sec"],
                scenario=cfg["site"].get("scenario", "mixed"),
                config_path=cfg.get("_config_path"))
            db.add(line)
            db.flush()
        if db.query(Station).filter_by(line_id=line.id).count():
            if append:
                # continuation (scenario injection): reuse the existing
                # topology — topology must match the site config by station code
                stations = {s.code: s for s in db.query(Station)
                            .filter(Station.line_id == line.id).all()}
                missing = [e["id"] for e in cfg["stations"] if e["id"] not in stations]
                if missing:
                    raise RuntimeError(f"append mode: site config has stations absent "
                                       f"from the twin DB: {missing}")
                return plant, line, stations
            raise RuntimeError("line already populated — ingest into a fresh database "
                               "(drop data/generated/twinline.db) or use a new line code")

        sim_stations = [SimStation.from_config(e, cfg["archetypes"], cfg["sensor_profiles"])
                        for e in cfg["stations"]]
        types: dict[str, StationType] = {}
        stations: dict[str, Station] = {}
        for idx, (s, entry) in enumerate(zip(sim_stations, cfg["stations"]), start=1):
            st_type = types.get(s.archetype)
            if st_type is None:
                st_type = db.query(StationType).filter_by(code=s.archetype).first()
                if st_type is None:
                    st_type = StationType(code=s.archetype, sensors_expected=list(s.sensors))
                    db.add(st_type)
                    db.flush()
                types[s.archetype] = st_type
            row = Station(line_id=line.id, seq=idx, code=s.id, zone=s.zone,
                          name=entry.get("name"), type_id=st_type.id,
                          sensor_profile=s.profile,
                          capacity=s.capacity, has_tool=bool(s.tool),
                          is_inspection=s.is_inspection, env_sensitive=s.env_sensitive,
                          equipment_generation=entry.get("equipment_generation"),
                          criticality=entry.get("criticality"),
                          baseline_cycle_mu=s.mu, baseline_cycle_sigma=s.sigma)
            db.add(row)
            db.flush()
            for name in s.sensors:
                from ..simulation.engine import SENSOR_UNITS
                db.add(Sensor(station_id=row.id, name=name, unit=SENSOR_UNITS.get(name, "")))
            stations[s.id] = row
        db.commit()
        return plant, line, stations

    def provision_topology(self, db: Session, cfg: dict,
                           plant_code: str = "PLANT_A",
                           line_code: str = "LINE_A",
                           line_name: str | None = None,
                           config_path: str | None = None) -> tuple[Plant, ProductionLine, dict]:
        """Provision ONLY the topology (plant/line/stations/sensors) for a
        factory configuration — no production data is generated. Used by the
        Factory Setup workflow so a configured factory exists in the twin
        immediately, with an explicit 'no historical data yet' state."""
        if config_path:
            cfg = {**cfg, "_config_path": config_path}
        return self._upsert_topology(db, cfg, append=False,
                                     plant_code=plant_code,
                                     line_code=line_code,
                                     line_name=line_name)

    # ---------------- consume ----------------
    def ingest(self, source: DataSource, append: bool = False,
               plant_code: str = "PLANT_A", line_code: str = "LINE_A",
               line_name: str | None = None) -> dict[str, Any]:
        cfg = source.get_site_config()
        t_start = time.time()
        db = self.sf()
        plant, line, stations = self._upsert_topology(db, cfg, append=append,
                                                      plant_code=plant_code,
                                                      line_code=line_code,
                                                      line_name=line_name)
        variant_factor = {v["id"]: v["factor"] for v in cfg["demand"]["product_variants"]}
        raw_stream = self.settings.raw_sensor_stream

        vehicles: dict[str, Vehicle] = {}
        batches: dict[str, int] = {}
        open_visit: dict[str, dict] = {}
        last_quality: dict[str, float] = {}
        stats: Counter = Counter()

        buf_events: list[dict] = []
        buf_readings: list[dict] = []
        buf_kpis: list[dict] = []
        buf_env: list[dict] = []
        buf_mach: list[dict] = []

        def flush(force: bool = False) -> None:
            for buf, model in ((buf_events, VehicleEvent), (buf_readings, SensorReading),
                               (buf_kpis, StationKpi), (buf_env, EnvironmentSample),
                               (buf_mach, MachineEvent)):
                while buf and (force or len(buf) >= self.chunk):
                    batch, buf[:] = buf[: self.chunk], buf[self.chunk:]
                    db.bulk_insert_mappings(model, batch)
            if force:
                db.commit()
            else:
                db.flush()

        def finalize_visit(vin: str, fail_at_station: str | None = None) -> None:
            v = open_visit.pop(vin, None)
            if v is None or "exited_at" not in v:
                open_visit.pop(vin, None)
                return
            st_row = stations[v["station"]]
            base = st_row.baseline_cycle_mu * variant_factor.get(
                vehicles[vin].variant, 1.0)
            is_insp = st_row.is_inspection
            insp_result = None
            if is_insp:
                insp_result = "fail" if fail_at_station == v["station"] else "pass"
            buf_events.append({
                "vehicle_id": vehicles[vin].id, "station_id": st_row.id,
                "entered_at": v["entered_at"], "exited_at": v["exited_at"],
                "cycle_time": v.get("cycle_time"),
                "cycle_dev": (None if v.get("cycle_time") is None
                              else round(v["cycle_time"] - base, 3)),
                "queue_seen": v.get("queue_seen"),
                "checklist_result": v.get("checklist"),
                "inspection_result": insp_result,
                "internal_flags": v.get("flags", []),
            })
            for sensor, vals in v.get("readings", {}).items():
                import numpy as np
                arr = np.asarray(vals, dtype=float)
                rec = {"vehicle_id": vehicles[vin].id, "station_id": st_row.id,
                       "sensor_name": sensor,
                       "unit": v.get("units", {}).get(sensor, ""),
                       "t": v["exited_at"], "n_samples": int(arr.size),
                       "mean": float(arr.mean()), "std": float(arr.std()),
                       "min": float(arr.min()), "max": float(arr.max()),
                       "status": "ok",
                       "raw": [round(float(x), 3) for x in vals] if raw_stream else None}
                buf_readings.append(rec)
            stats["vehicle_events"] += 1

        def handle(ev: dict) -> None:  # noqa: C901
            t, etype = ev["t"], ev["type"]
            if etype == "part_enter":
                vin = ev["part"]
                if vin not in vehicles:
                    bcode = ev["batch"]
                    if bcode not in batches:
                        b = ProductionBatch(line_id=line.id, code=bcode, first_seen=t)
                        db.add(b)
                        db.flush()
                        batches[bcode] = b.id
                    veh = Vehicle(line_id=line.id, vin=vin, variant=ev["variant"],
                                  batch_id=batches[bcode], started_at=t)
                    db.add(veh)
                    db.flush()
                    vehicles[vin] = veh
                    stats["vehicles"] += 1
                finalize_visit(vin)  # previous station visit closes here
                open_visit[vin] = {"station": ev["station"], "entered_at": t,
                                   "queue_seen": ev.get("queue_seen"), "flags": ev.get("flags", [])}
            elif etype == "part_exit":
                vin = ev["part"]
                v = open_visit.get(vin)
                if v is not None:
                    v.update({"exited_at": t, "cycle_time": ev.get("cycle_time"),
                              "flags": ev.get("flags", [])})
                    last_quality[vin] = ev.get("part_quality", 1.0)
            elif etype == "sensor":
                v = open_visit.get(ev["part"])
                if v is not None:
                    sensor_unit = ev.get("unit", "")
                    v.setdefault("readings", defaultdict(list))[ev["sensor"]].append(ev["value"])
                    v.setdefault("units", {})[ev["sensor"]] = sensor_unit
            elif etype == "checklist":
                v = open_visit.get(ev["part"])
                if v is not None:
                    v["checklist"] = ev["result"]
            elif etype == "defect":
                vin = ev["part"]
                finalize_visit(vin, fail_at_station=ev["station"])
                defect = Defect(vehicle_id=vehicles[vin].id,
                                station_id=stations[ev["station"]].id, t=t,
                                true_root_causes=ev.get("top_causes", []))
                db.add(defect)
                db.flush()
                db.add(Inspection(vehicle_id=vehicles[vin].id,
                                  station_id=stations[ev["station"]].id, t=t,
                                  result="fail", defect_id=defect.id))
                veh = vehicles[vin]
                veh.status = "scrapped"
                veh.completed_at = t
                veh.quality_score = last_quality.get(vin)
                stats["defects"] += 1
            elif etype == "part_complete":
                vin = ev["part"]
                finalize_visit(vin)
                veh = vehicles[vin]
                veh.status = "completed"
                veh.completed_at = t
                veh.quality_score = ev.get("quality")
            elif etype == "kpi":
                buf_kpis.append({"station_id": stations[ev["station"]].id, "t": t,
                                 "queue_len": ev["queue_len"], "utilization": ev["utilization"],
                                 "wear": ev.get("wear"), "completed": ev["completed"]})
            elif etype == "machine_event":
                buf_mach.append({"station_id": stations[ev["station"]].id, "t": t,
                                 "event": ev["event"], "wear": ev.get("wear")})
            elif etype == "environment":
                buf_env.append({"t": t, "temp_c": ev["temp_c"], "humidity": ev["humidity"]})
            if sum(map(len, (buf_events, buf_readings, buf_kpis))) >= self.chunk:
                flush()

        summary = source.stream(handle)

        # resolve dangling visits (vehicles mid-line at run end)
        for vin in list(open_visit):
            finalize_visit(vin)
        # create pass Inspections from finalized vehicle events not having one yet
        insp_events = (db.query(VehicleEvent)
                       .filter(VehicleEvent.inspection_result == "pass").all())
        have_pass = {(r[0], r[1]) for r in
                     db.query(Inspection.vehicle_id, Inspection.station_id).all()}
        for ve in insp_events:
            if (ve.vehicle_id, ve.station_id) not in have_pass:
                db.add(Inspection(vehicle_id=ve.vehicle_id, station_id=ve.station_id,
                                  t=ve.exited_at or 0.0, result="pass"))
        flush(force=True)
        db.close()

        return {**summary, "plant_id": plant.id, "line_id": line.id,
                "ingest_stats": dict(stats),
                "wall_seconds": round(time.time() - t_start, 1)}
