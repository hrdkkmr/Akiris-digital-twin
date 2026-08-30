"""Factory Setup — configure-any-factory workflow.

A non-technical user defines a factory (plant -> production lines -> stations ->
equipment -> sensors) through the UI. This service:

  - validates the payload with human-readable errors (never raw SQL/Python),
  - writes ONE site-config YAML per production line (the SAME format the twin
    core already consumes — `configs/automotive_line.yaml` is the demo's), so a
    configured factory is a first-class twin configuration, not a fake JSON blob,
  - provisions the real Plant / ProductionLine / Station / Sensor rows through
    the existing ingestion pipeline (topology only — no data is fabricated),
  - exposes coverage/observability summaries and a factory selector context
    (TwinContext.active_line_id) that every existing analytics endpoint follows.

Equipment generation (modern/mid/legacy) and sensor coverage are independent:
a Legacy station can be fully instrumented, a Modern station can be manual-only.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..core.config import ROOT, get_settings
from ..db.session import SessionLocal
from ..ingestion.pipeline import IngestionPipeline
from ..models import Plant, ProductionLine, Sensor, Station, StationType, TwinContext, Vehicle
from ..simulation.engine import SENSOR_UNITS

FACTORY_DIR = ROOT / "configs" / "factories"
DEMO_SITE = ROOT / "configs" / "automotive_line.yaml"

# --------------------------------------------------------------------------
# Vocabulary (reuses the existing project taxonomy)
# --------------------------------------------------------------------------

# UI equipment types -> existing station archetypes (engine + analytics reuse)
EQUIPMENT_TO_ARCHETYPE: dict[str, str] = {
    "welding": "welding",
    "torque_tool": "torque",
    "robot": "fastening",        # robotized fastening
    "paint": "painting",
    "inspection": "inspection",
    "conveyor": "trim",          # conveyor-fed manual assembly
    "other": "alignment",
}
EQUIPMENT_TYPES = list(EQUIPMENT_TO_ARCHETYPE.keys())
ARCHETYPES = ["welding", "fastening", "alignment", "pretreatment", "painting",
              "curing", "torque", "electrical", "fluid_fill", "trim",
              "inspection", "final_test"]
EQUIPMENT_GENERATIONS = ["modern", "mid", "legacy"]
CRITICALITIES = ["critical", "high", "normal", "low"]

# UI sensor checklist -> engine sensor names (None = event/KPI-derived, always
# present as cycle/part events, not a Sensor row). Coverage is the count of
# Sensor rows / FULL_SENSOR_REFERENCE(4) — identical semantics to data_quality.
UI_SENSORS: dict[str, str | None] = {
    "cycle_time": None,          # derived from part_enter/part_exit events
    "torque": "torque",
    "vibration": "vibration",
    "temperature": "temperature",
    "motor_current": "motor_current",
    "throughput": None,          # derived from part_exit events
    "quality": None,             # inspection/checklist capability (event-derived)
}
UI_SENSOR_LABELS: dict[str, str] = {
    "cycle_time": "Cycle Time", "torque": "Torque", "vibration": "Vibration",
    "temperature": "Temperature", "motor_current": "Motor / Current",
    "throughput": "Throughput", "quality": "Quality / Inspection",
}

ZONE_BY_ARCHETYPE: dict[str, str] = {
    "welding": "body", "fastening": "body", "alignment": "body",
    "pretreatment": "paint", "painting": "paint", "curing": "paint",
    "torque": "final", "electrical": "final", "fluid_fill": "final",
    "trim": "final", "inspection": "final", "final_test": "final",
}

# coverage buckets mirror data_quality (count(Sensor)/FULL_SENSOR_REFERENCE)
COVERAGE_HIGH = 0.75
COVERAGE_MEDIUM = 0.5

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def coverage_bucket(coverage: float) -> str:
    if coverage >= COVERAGE_HIGH:
        return "high"
    if coverage >= COVERAGE_MEDIUM:
        return "medium"
    if coverage > 0:
        return "low"
    return "none"


def sanitize_id(value: str, max_len: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", value or "").upper()
    return cleaned[:max_len]


# --------------------------------------------------------------------------
# Validation (human-readable errors only)
# --------------------------------------------------------------------------

def validate_factory(db, payload: dict) -> list[str]:
    errors: list[str] = []
    factory = payload.get("factory") or {}
    name = (factory.get("name") or "").strip()
    fid = sanitize_id(factory.get("id") or "", 32)
    if not name:
        errors.append("Factory name is required.")
    if not factory.get("id"):
        errors.append("Factory ID is required.")
    elif not fid or not _ID_RE.match(factory.get("id") or ""):
        errors.append("Factory ID may contain only letters, digits, dashes and underscores.")
    elif db.query(Plant).filter_by(code=fid).first():
        errors.append(f"Factory ID {fid} already exists.")

    lines = payload.get("lines") or []
    if not lines:
        errors.append("Add at least one production line.")
    seen_lines: set[str] = set()
    for line in lines:
        lid = sanitize_id(line.get("id") or "", 32)
        lname = (line.get("name") or "").strip()
        if not line.get("id"):
            errors.append("Every production line needs an ID.")
        elif not lid or not _ID_RE.match(line.get("id") or ""):
            errors.append(f"Line ID {line.get('id') or ''} may contain only letters, digits, dashes and underscores.")
        elif lid in seen_lines:
            errors.append(f"Line ID {lid} already used in this factory.")
        else:
            seen_lines.add(lid)
        if not lname:
            errors.append(f"Line {lid or line.get('id') or '(no id)'} needs a name.")
        stations = line.get("stations") or []
        if not stations:
            errors.append(f"Line {lid or line.get('id') or '(no id)'} needs at least one station.")
        seen_stations: set[str] = set()
        for st in stations:
            sid = sanitize_id(st.get("id") or "", 16)
            if not st.get("id"):
                errors.append("Every station needs an ID.")
            elif not sid or not _ID_RE.match(st.get("id") or ""):
                errors.append(f"Station ID {st.get('id') or ''} may contain only letters, digits, dashes and underscores.")
            elif sid in seen_stations:
                errors.append(f"Station {sid} already exists on this production line.")
            else:
                seen_stations.add(sid)
            if not (st.get("name") or "").strip():
                errors.append(f"Station {sid or st.get('id') or '(no id)'} needs a name.")
            eq = st.get("equipment_type")
            if eq not in EQUIPMENT_TYPES:
                errors.append(f"Station {sid}: invalid equipment type.")
            gen = st.get("equipment_generation")
            if gen not in EQUIPMENT_GENERATIONS:
                errors.append(f"Station {sid}: invalid equipment generation.")
            crit = st.get("criticality")
            if crit not in CRITICALITIES:
                errors.append(f"Station {sid}: invalid criticality.")
            sensors = st.get("sensors") or []
            if len(sensors) != len(set(sensors)):
                dupes = sorted({s for s in sensors if sensors.count(s) > 1})
                errors.append(f"Station {sid}: duplicate sensor {dupes[0]}.")
            for s in sensors:
                if s not in UI_SENSORS:
                    errors.append(f"Station {sid}: unknown sensor type '{s}'.")
    return errors


# --------------------------------------------------------------------------
# Site-config generation (the EXACT format the twin core consumes)
# --------------------------------------------------------------------------

def _load_demo_base() -> dict:
    return yaml.safe_load(Path(DEMO_SITE).read_text())


def build_site_config(factory_id: str, line: dict, factory: dict,
                      line_index: int) -> dict:
    """One site config per production line (same shape as automotive_line.yaml)."""
    demo = _load_demo_base()
    used_archetypes: dict[str, dict] = {}
    zones: list[str] = []
    sensor_profiles: dict[str, list[str]] = {}
    stations_cfg: list[dict] = []

    for idx, st in enumerate(line.get("stations") or [], start=1):
        code = sanitize_id(st.get("id") or "", 16)
        eq = st.get("equipment_type") or "other"
        archetype = st.get("process") or EQUIPMENT_TO_ARCHETYPE.get(eq, "alignment")
        if archetype not in demo["archetypes"]:
            archetype = EQUIPMENT_TO_ARCHETYPE.get(eq, "alignment")
        arch = dict(demo["archetypes"][archetype])
        used_archetypes[archetype] = arch

        zone = ZONE_BY_ARCHETYPE.get(archetype, "final")
        if zone not in zones:
            zones.append(zone)

        sensors_ui = st.get("sensors") or []
        sensor_names = [UI_SENSORS[s] for s in sensors_ui
                        if s in UI_SENSORS and UI_SENSORS[s]]
        manual = bool(st.get("manual_inspection"))
        # profile naming: reuse the standard names where semantics match so the
        # existing observability logic (manual/sparse branches) applies
        if len(sensor_names) >= 4:
            prof = "full"
        elif not sensor_names:
            prof = "manual" if manual else "sparse"
        else:
            prof = f"st{line_index:02d}{idx:02d}"   # short, collision-free
        sensor_profiles[prof] = list(dict.fromkeys(sensor_names))

        is_inspection = manual or "quality" in sensors_ui or archetype in ("inspection", "final_test")
        stations_cfg.append({
            "id": code,
            "name": (st.get("name") or "").strip(),
            "zone": zone,
            "archetype": archetype,
            "equipment_generation": st.get("equipment_generation") or "modern",
            "criticality": st.get("criticality") or "normal",
            "overrides": {"sensor_profile": prof, "is_inspection": is_inspection},
        })

    return {
        "site": {
            "name": (factory.get("name") or "").strip(),
            "industry": "automotive",
            "zones": zones,
            "plant_code": factory_id,
            "line_code": sanitize_id(line.get("id") or "", 32),
            "line_name": (line.get("name") or "").strip(),
            "line_description": (line.get("description") or "").strip() or None,
            "location": (factory.get("location") or "").strip() or None,
            "description": (factory.get("description") or "").strip() or None,
            "scenario": "mixed",
        },
        "demand": demo["demand"],
        "shifts": demo["shifts"],
        "environment": demo["environment"],
        "mechanisms": demo["mechanisms"],
        "injection": demo["injection"],
        "sensor_profiles": sensor_profiles,
        "archetypes": used_archetypes,
        "stations": stations_cfg,
    }


# --------------------------------------------------------------------------
# Persistence + provisioning
# --------------------------------------------------------------------------

def save_line_config(factory_id: str, line_code: str, cfg: dict) -> Path:
    d = FACTORY_DIR / factory_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{line_code}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    return path


def _provision_line(db, cfg: dict, path: Path,
                    factory_id: str, line_code: str, line_name: str):
    pipeline = IngestionPipeline(SessionLocal)
    return pipeline.provision_topology(db, cfg, plant_code=factory_id,
                                       line_code=line_code, line_name=line_name,
                                       config_path=str(path))


def provision_factory(db, payload: dict) -> dict:
    """Validate -> persist YAML -> provision Plant/Lines/Stations/Sensors.

    Returns {factory, lines, active_line_id, warnings}. No production data is
    generated here — a fresh factory starts with an explicit 'no historical
    data yet' state; simulation data is an opt-in, clearly labeled step.
    """
    errors = validate_factory(db, payload)
    if errors:
        raise ValueError(errors)
    factory = payload["factory"]
    factory_id = sanitize_id(factory.get("id") or "", 32)
    lines = payload["lines"]
    warnings: list[str] = []

    provisioned: list[dict] = []
    active_line_id: int | None = None
    for li, line in enumerate(lines, start=1):
        line_code = sanitize_id(line.get("id") or "", 32)
        line_name = (line.get("name") or "").strip()
        cfg = build_site_config(factory_id, line, factory, li)
        path = save_line_config(factory_id, line_code, cfg)
        plant, line_row, stations = _provision_line(
            db, cfg, path, factory_id, line_code, line_name)
        if active_line_id is None:
            active_line_id = line_row.id
        # per-station warnings for sensor-poor / manual-only stations
        for st in line.get("stations") or []:
            sid = sanitize_id(st.get("id") or "", 16)
            sensors = st.get("sensors") or []
            engine_sensors = [UI_SENSORS[s] for s in sensors if s in UI_SENSORS and UI_SENSORS[s]]
            if not engine_sensors:
                if st.get("manual_inspection"):
                    warnings.append(
                        f"Station {sid} has no electronic sensors — manual inspection enabled. "
                        "Limited instrumentation: the twin reasons with reduced confidence here.")
                else:
                    warnings.append(
                        f"Station {sid} has no electronic sensors and no manual inspection — "
                        "very limited visibility. The twin will flag this as a critical observability gap.")
            elif len(engine_sensors) < 4:
                warnings.append(
                    f"Station {sid} has partial sensor coverage "
                    f"({len(engine_sensors)}/{4} expected signals). Observability is reduced.")
        provisioned.append({"line_id": line_row.id, "line_code": line_code,
                            "line_name": line_name,
                            "stations": len(stations)})

    # the first line becomes the active context so the dashboard opens on it
    if active_line_id is not None:
        set_active_line(db, active_line_id)

    return {
        "factory": _factory_summary(db, factory_id),
        "lines": provisioned,
        "active_line_id": active_line_id,
        "warnings": warnings,
    }


def set_active_line(db, line_id: int) -> None:
    ctx = db.get(TwinContext, 1)
    if ctx is None:
        ctx = TwinContext(id=1, active_line_id=line_id)
        db.add(ctx)
    else:
        ctx.active_line_id = line_id
    db.commit()


def active_context(db) -> dict:
    ctx = db.get(TwinContext, 1)
    line = db.get(ProductionLine, ctx.active_line_id) if ctx and ctx.active_line_id else None
    if line is None:
        line = db.query(ProductionLine).order_by(ProductionLine.id).first()
    plant = db.get(Plant, line.plant_id) if line else None
    return {
        "factory_code": plant.code if plant else None,
        "factory_name": plant.name if plant else None,
        "line_id": line.id if line else None,
        "line_code": line.code if line else None,
        "line_name": line.name if line else None,
        "has_data": _line_has_data(db, line.id) if line else False,
    }


def _line_has_data(db, line_id: int) -> bool:
    return db.query(Vehicle.id).filter(Vehicle.line_id == line_id).limit(1).first() is not None


# --------------------------------------------------------------------------
# Reads (factory selector + detail)
# --------------------------------------------------------------------------

def _station_coverage(db, station: Station) -> float:
    n = db.query(Sensor.id).filter(Sensor.station_id == station.id).count()
    from ..services.twin_state import FULL_SENSOR_REFERENCE
    return round(n / FULL_SENSOR_REFERENCE, 2)


def _line_summary(db, line: ProductionLine) -> dict:
    stations = db.query(Station).filter(Station.line_id == line.id).order_by(Station.seq).all()
    counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    equipment = {"modern": 0, "mid": 0, "legacy": 0}
    for st in stations:
        cov = _station_coverage(db, st)
        counts[coverage_bucket(cov)] += 1
        gen = st.equipment_generation or "modern"
        equipment[gen] = equipment.get(gen, 0) + 1
    return {
        "id": line.id, "code": line.code, "name": line.name,
        "description": line.description,
        "stations": len(stations),
        "has_data": _line_has_data(db, line.id),
        "coverage": counts,
        "equipment": equipment,
        "manual_stations": sum(1 for st in stations if st.is_inspection),
    }


def _factory_summary(db, factory_id: str) -> dict:
    plant = db.query(Plant).filter_by(code=factory_id).first()
    if not plant:
        raise KeyError(f"factory {factory_id} not found")
    ctx = db.get(TwinContext, 1)
    active_line = ctx.active_line_id if ctx else None
    lines = (db.query(ProductionLine).filter(ProductionLine.plant_id == plant.id)
             .order_by(ProductionLine.id).all())
    return {
        "code": plant.code, "name": plant.name, "location": plant.location,
        "description": plant.description,
        "lines": [_line_summary(db, l) for l in lines],
        "is_active": any(l.id == active_line for l in lines),
    }


def list_factories(db) -> dict:
    ctx = db.get(TwinContext, 1)
    if ctx and ctx.active_line_id is not None:
        active_line_id = ctx.active_line_id
    else:
        # fresh DB / no selection yet — same fallback as get_line_or_404
        first = db.query(ProductionLine).order_by(ProductionLine.id).first()
        active_line_id = first.id if first else None
    plants = db.query(Plant).order_by(Plant.id).all()
    out = []
    for p in plants:
        lines = (db.query(ProductionLine).filter(ProductionLine.plant_id == p.id)
                 .order_by(ProductionLine.id).all())
        line_summaries = [_line_summary(db, l) for l in lines]
        out.append({
            "code": p.code, "name": p.name, "location": p.location,
            "description": p.description,
            "lines": line_summaries,
            "is_active": any(l["id"] == active_line_id for l in line_summaries),
            "has_data": any(l["has_data"] for l in line_summaries),
        })
    return {"factories": out}


def factory_detail(db, factory_id: str) -> dict:
    plant = db.query(Plant).filter_by(code=factory_id).first()
    if not plant:
        raise KeyError(f"factory {factory_id} not found")
    from ..services import data_quality as dq_service
    lines_out = []
    _ARCHETYPE_TO_EQUIPMENT = {v: k for k, v in EQUIPMENT_TO_ARCHETYPE.items()}
    for line in (db.query(ProductionLine).filter(ProductionLine.plant_id == plant.id)
                 .order_by(ProductionLine.id).all()):
        stations = (db.query(Station).filter(Station.line_id == line.id)
                    .order_by(Station.seq).all())
        st_types = {t.id: t.code for t in db.query(StationType).all()} \
            if stations else {}
        dq_rows = {r["code"]: r for r in
                   dq_service.compute_station_data_quality(db, line.id, persist=False)}
        stations_out = []
        for st in stations:
            sensors = [s.name for s in db.query(Sensor).filter(Sensor.station_id == st.id).all()]
            dq = dq_rows.get(st.code) or {}
            cov = dq.get("sensor_coverage", _station_coverage(db, st))
            archetype = st_types.get(st.type_id)
            stations_out.append({
                "id": st.id, "code": st.code, "name": st.name,
                "archetype": archetype,
                "equipment_type": _ARCHETYPE_TO_EQUIPMENT.get(archetype or "", "other"),
                "zone": st.zone,
                "equipment_generation": st.equipment_generation or "modern",
                "criticality": st.criticality or "normal",
                "sensors": sensors,
                "manual_inspection": bool(st.is_inspection),
                "coverage": cov,
                "observability": coverage_bucket(cov),
                "analytics_confidence": dq.get("analytics_confidence"),
            })
        lines_out.append({
            "id": line.id, "code": line.code, "name": line.name,
            "description": line.description, "stations": stations_out,
        })
    return {"factory": _factory_summary(db, factory_id), "lines": lines_out}


def activate_factory(db, factory_id: str) -> dict:
    plant = db.query(Plant).filter_by(code=factory_id).first()
    if not plant:
        raise KeyError(f"factory {factory_id} not found")
    line = (db.query(ProductionLine).filter(ProductionLine.plant_id == plant.id)
            .order_by(ProductionLine.id).first())
    if not line:
        raise ValueError(f"factory {factory_id} has no production lines")
    set_active_line(db, line.id)
    return {"status": "ok", "active": active_context(db)}


def simulate_factory(db, factory_id: str, vehicles: int = 400,
                     seed: int = 42, scenario: str = "mixed",
                     session_factory=None) -> dict:
    """Explicit, clearly-labeled simulation-data generation for a configured
    factory (reuses the existing simulator + ingestion pipeline; nothing is
    presented as real historical data)."""
    sf = session_factory or SessionLocal
    plant = db.query(Plant).filter_by(code=factory_id).first()
    if not plant:
        raise KeyError(f"factory {factory_id} not found")
    line = (db.query(ProductionLine).filter(ProductionLine.plant_id == plant.id)
            .order_by(ProductionLine.id).first())
    if not line:
        raise ValueError(f"factory {factory_id} has no production lines")
    cfg_path = Path(line.config_path) if line.config_path else None
    if not cfg_path or not cfg_path.exists():
        raise ValueError("factory configuration file missing — recreate the factory")

    settings = get_settings()
    src = _SimSource(cfg_path, scenario=scenario, seed=seed, vehicles=vehicles,
                     max_seconds=settings.max_sim_seconds)
    pipeline = IngestionPipeline(sf)
    summary = pipeline.ingest(src, append=True, plant_code=plant.code,
                              line_code=line.code, line_name=line.name)

    # refresh the twin's analytics so dashboards react (anomalies, data quality,
    # recommendations) — model retraining stays an explicit step in the UI
    db2 = sf()
    try:
        from ..ml import anomaly as anomaly_service
        from ..services import data_quality as dq_service
        from ..services import recommendations as rec_service
        anomaly_service.detect_anomalies(db2, line.id)
        dq_service.compute_station_data_quality(db2, line.id, persist=True)
        rec_service.generate_recommendations(db2, line.id)
    finally:
        db2.close()

    return {
        "status": "simulated", "simulated": True, "line_id": line.id,
        "scenario": scenario, "seed": seed, "vehicles": vehicles,
        "ingested": {k: summary.get(k) for k in
                     ("spawned", "completed", "scrapped", "bad_batches",
                      "wall_seconds") if k in summary},
        "note": "Simulation data — clearly labeled, not claimed as historical production data.",
    }


class _SimSource:
    """Thin wrapper so simulate_factory can build the source with a custom path."""
    def __init__(self, site_config, scenario, seed, vehicles, max_seconds):
        from ..ingestion.simulator_source import SimulatorDataSource
        self._impl = SimulatorDataSource(str(site_config), scenario=scenario,
                                         seed=seed, vehicles=vehicles,
                                         max_seconds=max_seconds)

    def get_site_config(self):
        return self._impl.get_site_config()

    def stream(self, emit):
        return self._impl.stream(emit)
