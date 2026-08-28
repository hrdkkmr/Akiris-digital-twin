"""Data-generation / genealogy / bottleneck / missing-data tests."""
from __future__ import annotations

from sqlalchemy import func  # noqa: F401

from app.models import Station, Vehicle, VehicleEvent
from app.services.bottleneck import compute_bottlenecks
from app.services.data_quality import compute_station_data_quality
from app.services.genealogy import root_cause_candidates, vehicle_journey


def test_topology_and_uneven_coverage(db):
    stations = db.query(Station).all()
    assert len(stations) == 42
    zones = {s.zone for s in stations}
    assert zones == {"body", "paint", "final"}
    profiles = {s.sensor_profile for s in stations}
    assert profiles == {"full", "mid", "sparse", "manual"}     # uneven by design
    assert any(s.is_inspection for s in stations)


def test_generation_produces_linked_entities(db, twin_db):
    s = twin_db["summary"]
    assert s["completed"] > 0
    vehicles = db.query(func.count(Vehicle.id)).scalar()
    # >= not == : scenario injection (test_api, runs first) intentionally
    # APPENDS vehicles to the same database — count only grows from the seed build
    assert vehicles >= s["spawned"] > 0
    n_events = db.query(func.count(VehicleEvent.id)).scalar()
    assert n_events > vehicles * 20  # scrapped vehicles exit early (~29 avg)


def test_genealogy_ordering_and_defect_trace(db, scrapped_vehicle_id):
    journey = vehicle_journey(db, scrapped_vehicle_id, include_truth=True)
    assert journey is not None
    steps = journey["steps"]
    times = [s["entered_at"] for s in steps]
    assert times == sorted(times), "genealogy must be time-ordered"
    assert journey["vehicle"]["status"] == "scrapped"
    found_at = journey["outcome"]["defect_found_at"]
    assert found_at is not None
    last = steps[-1]
    assert last["station"] == found_at, "defect must surface AT an inspection"
    assert last["inspection"] == "fail"
    assert journey["outcome"]["true_root_causes"], "truth mode must reveal causes"
    factors = root_cause_candidates(db, scrapped_vehicle_id)
    assert factors["candidates"], "ranked contributing factors expected"
    assert "not causal proof" in factors["caveat"]


def test_bottleneck_identifies_engineered_bn(db):
    """S17 is engineered saturated (mu 58s takt 45s, single-booth). The detector
    must recover it — this guards against 'random bottleneck' regressions."""
    line_id = db.query(Station.line_id).first()[0]
    result = compute_bottlenecks(db, line_id)
    assert result["top"]["code"] == "S17"
    assert result["top"]["status"] in ("critical", "high")
    assert result["top"]["score"] > 0.5
    assert result["top"]["confidence"] > 0.6


def test_missing_data_metadata_preserved(db):
    line_id = db.query(Station.line_id).first()[0]
    rows = compute_station_data_quality(db, line_id, persist=False)
    assert len(rows) == 42
    by_profile: dict[str, list] = {}
    for r in rows:
        by_profile.setdefault(r["sensor_profile"], []).append(r)
    assert all(r["sensor_coverage"] == 1.0 for r in by_profile["full"])
    assert all(r["sensor_coverage"] == 0.0 for r in by_profile["manual"])
    assert all(0.0 <= r["completeness"] <= 1.0 for r in rows)
    sparse = by_profile["sparse"][0]
    assert sparse["sensor_coverage"] == 0.0 or sparse["sensor_coverage"] < 1.0
