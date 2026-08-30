"""Factory Setup — configure-any-factory (backend tests).

Runs on a dedicated, function-scoped database so the shared session fixture
(the 42-station demo twin used by the existing tests) is never mutated.

Covers: validation (human errors), topology provisioning, sensor-poor /
manual-only stations, coverage computation, factory selector (active context
switches the default line), labeled simulation-data generation.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_line_or_404
from app.db.session import init_db
from app.models import Plant, ProductionLine, Sensor, Station, Vehicle
from app.services import factory_config as fc


def _payload(factory_id: str = "PLANT-B", factory_name: str = "Plant B - Chennai") -> dict:
    return {
        "factory": {"name": factory_name, "id": factory_id,
                    "location": "Chennai, India",
                    "description": "Mixed-model vehicle assembly plant"},
        "lines": [
            {"id": "FA-01", "name": "Final Assembly", "type": "Final Assembly",
             "description": "Main line",
             "stations": [
                 {"id": "S01", "name": "Body Joining", "process": "welding",
                  "equipment_type": "welding", "equipment_generation": "modern",
                  "criticality": "critical", "manual_inspection": False,
                  "sensors": ["cycle_time", "torque", "vibration", "temperature",
                              "motor_current"]},
                 {"id": "S02", "name": "Torque Assembly", "process": "torque",
                  "equipment_type": "torque_tool", "equipment_generation": "legacy",
                  "criticality": "high", "manual_inspection": True,
                  "sensors": ["cycle_time"]},
                 {"id": "S03", "name": "Manual Check", "process": "trim",
                  "equipment_type": "conveyor", "equipment_generation": "mid",
                  "criticality": "normal", "manual_inspection": True, "sensors": []},
             ]},
            {"id": "PA-01", "name": "Paint Shop", "type": "Paint", "description": "",
             "stations": [
                 {"id": "P01", "name": "Paint Booth", "process": "painting",
                  "equipment_type": "paint", "equipment_generation": "modern",
                  "criticality": "high", "manual_inspection": False,
                  "sensors": ["cycle_time", "temperature", "vibration"]},
             ]},
        ],
    }


@pytest.fixture()
def factory_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "FACTORY_DIR", tmp_path / "factories")
    return tmp_path / "factories"


@pytest.fixture()
def fdb(tmp_path):
    """Fresh, empty twin database per test (schema only — no demo data)."""
    engine = init_db(f"sqlite:///{tmp_path / 'f.db'}")
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_validation_errors_are_human_readable(fdb, factory_dir):
    db = fdb()
    try:
        # duplicate station id within a line
        p = _payload()
        p["lines"][0]["stations"][1]["id"] = "S01"
        assert "Station S01 already exists on this production line." in fc.validate_factory(db, p)

        # empty line + missing factory name
        p = _payload()
        p["factory"]["name"] = ""
        p["lines"][0]["stations"] = []
        errs = fc.validate_factory(db, p)
        assert "Factory name is required." in errs
        assert any("needs at least one station" in e for e in errs)

        # invalid sensor
        p = _payload()
        p["lines"][0]["stations"][0]["sensors"] = ["torque", "alien_signal"]
        errs = fc.validate_factory(db, p)
        assert any("unknown sensor type" in e for e in errs)

        # duplicate sensors
        p = _payload()
        p["lines"][0]["stations"][0]["sensors"] = ["torque", "torque"]
        errs = fc.validate_factory(db, p)
        assert any("duplicate sensor" in e for e in errs)
    finally:
        db.close()


def test_create_factory_provisions_real_topology(fdb, factory_dir):
    db = fdb()
    try:
        res = fc.provision_factory(db, _payload())
        assert res["active_line_id"] is not None
        assert res["factory"]["code"] == "PLANT-B"

        plant = db.query(Plant).filter_by(code="PLANT-B").first()
        assert plant is not None and plant.location == "Chennai, India"
        lines = plant.lines
        assert {l.code for l in lines} == {"FA-01", "PA-01"}

        fa = next(l for l in lines if l.code == "FA-01")
        stations = db.query(Station).filter(Station.line_id == fa.id).order_by(Station.seq).all()
        assert len(stations) == 3
        s01, s02, s03 = stations

        # full-instrumentation station
        assert s01.equipment_generation == "modern" and s01.criticality == "critical"
        assert {s.name for s in db.query(Sensor).filter(Sensor.station_id == s01.id).all()} == \
            {"torque", "vibration", "temperature", "motor_current"}
        assert not s01.is_inspection

        # legacy + manual-only station
        assert s02.equipment_generation == "legacy" and s02.is_inspection is True
        assert db.query(Sensor).filter(Sensor.station_id == s02.id).count() == 0

        # manual-only, no sensors at all
        assert s03.equipment_generation == "mid" and s03.is_inspection is True
        assert db.query(Sensor).filter(Sensor.station_id == s03.id).count() == 0

        # coverage summary: 1 high (S01), 1 medium (P01), 0 low, 2 none
        lst = fc.list_factories(db)
        pb = next(f for f in lst["factories"] if f["code"] == "PLANT-B")
        fa_summary = next(l for l in pb["lines"] if l["code"] == "FA-01")
        assert fa_summary["coverage"] == {"high": 1, "medium": 0, "low": 0, "none": 2}
        assert fa_summary["equipment"] == {"modern": 1, "mid": 1, "legacy": 1}
        assert fa_summary["manual_stations"] == 2
        assert fa_summary["has_data"] is False  # no data fabricated
    finally:
        db.close()


def test_factory_duplicate_id_rejected(fdb, factory_dir):
    db = fdb()
    try:
        fc.provision_factory(db, _payload())
        errs = fc.validate_factory(db, _payload())
        assert "Factory ID PLANT-B already exists." in errs
    finally:
        db.close()


def test_activate_switches_default_line_and_dashboard(fdb, factory_dir):
    db = fdb()
    try:
        fc.provision_factory(db, _payload())
        # default (no explicit line_id) must now resolve to the new factory's line
        line = get_line_or_404(db, None)
        assert line.code == "FA-01" and line.plant.code == "PLANT-B"
        st = db.query(Station).filter(Station.line_id == line.id).count()
        assert st == 3

        # switching back to the demo factory (first line in DB)
        demo_line = db.query(ProductionLine).order_by(ProductionLine.id).first()
        fc.set_active_line(db, demo_line.id)
        assert get_line_or_404(db, None).id == demo_line.id

        ctx = fc.active_context(db)
        assert ctx["line_id"] == demo_line.id
    finally:
        db.close()


def test_simulate_generates_labeled_data(fdb, factory_dir):
    db = fdb()
    try:
        fc.provision_factory(db, _payload())
        line_id = fc.active_context(db)["line_id"]
        assert db.query(Vehicle).filter(Vehicle.line_id == line_id).count() == 0

        res = fc.simulate_factory(db, "PLANT-B", vehicles=40, seed=7,
                                  session_factory=fdb)
        assert res["simulated"] is True
        assert "Simulation data" in res["note"]
        assert db.query(Vehicle).filter(Vehicle.line_id == res["line_id"]).count() > 0
        assert fc.active_context(db)["has_data"] is True
        assert fc.list_factories(db)["factories"][0]["has_data"] is True
    finally:
        db.close()


def test_factory_endpoints_via_api(fdb, factory_dir):
    """API surface wired to an isolated DB (dedicated client override)."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override():
        db = fdb()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        p = _payload(factory_id="PLANT-C", factory_name="Plant C - Pune")
        r = client.post("/factories", json=p)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["factory"]["code"] == "PLANT-C"
        assert body["warnings"], "sensor-poor stations must produce warnings"

        lst = client.get("/factories").json()
        assert any(f["code"] == "PLANT-C" for f in lst["factories"])

        act = client.get("/factories/active").json()
        assert act["factory_code"] == "PLANT-C"

        det = client.get("/factories/PLANT-C").json()
        assert len(det["lines"]) == 2

        # the dashboard follows the active factory: data feeds are empty for a
        # newly configured factory (no historical data is fabricated)
        assert client.get("/anomalies").json()["count"] == 0
        assert client.get("/recommendations").json()["count"] == 0
        assert client.get("/production/summary").json()["vehicles_total"] == 0
        assert client.get("/production/summary").json()["fpy"] is None

        # validation error path via API (duplicate id)
        r = client.post("/factories", json=p)
        assert r.status_code == 422
        assert "already exists" in r.text
    finally:
        app.dependency_overrides.pop(get_db, None)
