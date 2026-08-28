"""API + ML-refresh tests (against the 60-vehicle session fixture DB)."""
from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_stations_endpoint(client):
    r = client.get("/stations")
    assert r.status_code == 200
    d = r.json()
    assert len(d["stations"]) == 42
    s = d["stations"][0]
    assert {"code", "status", "utilization", "sensor_coverage"} <= set(s)


def test_station_detail(client):
    stations = client.get("/stations").json()["stations"]
    r = client.get(f"/stations/{stations[16]['id']}")  # S17
    assert r.status_code == 200
    d = r.json()
    assert d["code"] == "S17"
    assert "bottleneck" in d and "sensors" in d


def test_vehicles_and_journey(client):
    r = client.get("/vehicles?status=scrapped&limit=3")
    assert r.status_code == 200
    vehicles = r.json()["vehicles"]
    assert vehicles, "fixture must contain scrapped vehicles"
    jid = vehicles[0]["id"]
    r = client.get(f"/vehicles/{jid}/journey")
    assert r.status_code == 200
    assert len(r.json()["steps"]) >= 10
    r = client.get(f"/vehicles/{jid}/contributing-factors")
    assert r.status_code == 200
    assert "caveat" in r.json()


def test_bottleneck_and_dq_endpoints(client):
    r = client.get("/bottlenecks")
    assert r.status_code == 200
    assert r.json()["top"]["code"] == "S17"
    r = client.get("/data-quality")
    assert r.status_code == 200
    assert len(r.json()["stations"]) == 42


def test_ml_refresh_and_performance(client):
    """Small fixture may lack labels for training; the pipeline must still run
    gracefully (either trains or returns a documented error) and never 500."""
    r = client.post("/ml/refresh")
    assert r.status_code == 200
    body = r.json()
    assert "defect_model" in body and "anomalies" in body
    r = client.get("/model-performance")
    assert r.status_code == 200
    assert "registered_models" in r.json()
    r = client.get("/recommendations")
    assert r.status_code == 200
    assert r.json()["mode"].startswith("advisory-only")


def test_simulation_run_conflict_guard(client):
    r = client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30})
    assert r.status_code == 409  # populated DB must refuse non-fresh reruns


def test_readiness_and_trends(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    r = client.get("/production/trends?bucket_vehicles=20")
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    assert buckets, "fixture has completed vehicles — trends must not be empty"
    assert {"fpy", "throughput_per_hour", "vehicles"} <= set(buckets[0])
    assert all(0.0 <= b["fpy"] <= 1.0 for b in buckets)


def test_api_key_guard(client, monkeypatch):
    """TWIN_API_KEY set -> mutations 401 without header, pass with it.
    Cheap probe: the 409 conflict path (guard evaluated before handler)."""
    monkeypatch.setenv("TWIN_API_KEY", "s3cr3t")
    r = client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30})
    assert r.status_code == 401
    r = client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30},
                    headers={"X-API-Key": "s3cr3t"})
    assert r.status_code == 409  # passed the guard, hit the business guard
    monkeypatch.delenv("TWIN_API_KEY")
    r = client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30})
    assert r.status_code == 409  # dev default: open


def test_metrics_endpoint_and_security_headers(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "twinline_http_requests_total" in body
    assert "twinline_active_model_version" in body
    assert "twinline_mean_analytics_confidence" in body
    h = client.get("/health")
    assert h.headers["x-content-type-options"] == "nosniff"
    assert h.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in h.headers


def test_mutation_rate_limit(client, monkeypatch):
    """TWIN_RATE_LIMIT_PER_MIN=1 -> first mutation passes, second gets 429."""
    monkeypatch.setenv("TWIN_RATE_LIMIT_PER_MIN", "1")
    r1 = client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30})
    assert r1.status_code == 409   # consumed the single token
    r2 = client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30})
    assert r2.status_code == 429 and "Retry-After" in r2.headers
    # teardown: refill the shared token bucket deterministically so later
    # mutation tests (injection) are not throttled by this test's budget
    monkeypatch.setenv("TWIN_RATE_LIMIT_PER_MIN", "1000000")
    client.post("/simulation/run", json={"scenario": "mixed", "vehicles": 30})
    monkeypatch.delenv("TWIN_RATE_LIMIT_PER_MIN")
    # GETs are never limited (dashboard polling pattern)
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_injection_kinds_and_validation(client):
    r = client.get("/injection/kinds")
    assert r.status_code == 200
    assert len(r.json()["kinds"]) == 4
    r = client.post("/injection/inject", json={"kind": "not_a_kind"})
    assert r.status_code == 422  # pydantic Literal guard


def test_injection_continuation(client, twin_db):
    """The crown test: the twin CONTINUES without a wipe, analytics refresh,
    and history stays intact. Runs last in this file by design (mutates the
    shared fixture with 60 more vehicles)."""
    import app.api.routes_ops as ops_mod

    from app.models import Vehicle
    orig_sf = ops_mod.SessionLocal          # ops routes use this session factory
    ops_mod.SessionLocal = twin_db["sf"]    # point them at the fixture engine
    try:
        s = twin_db["sf"]()
        before = s.query(Vehicle).count(); s.close()
        r = client.post("/injection/inject",
                        json={"kind": "supplier_batch_failure", "vehicles": 60})
        assert r.status_code == 200
        rep = r.json()
        assert rep["status"] == "injected"
        assert rep["vehicles"]["injected_spawned"] >= 60        # spawned offset fixed
        assert rep["sim_window"]["t_end"] > rep["sim_window"]["t_start"]
        s = twin_db["sf"]()
        after = s.query(Vehicle).count(); s.close()
        assert after >= before + 60                            # appended, not replaced
        assert rep["vehicles"]["fleet_total"] == after
        assert rep["analytics_refresh"]["data_quality_rows"] == 42
        # twin still answers coherently after continuation
        assert client.get("/bottlenecks").json()["top"]["code"] == "S17"
        assert client.get("/production/summary").json()["vehicles_total"] == after
    finally:
        ops_mod.SessionLocal = orig_sf
