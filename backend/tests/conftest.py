"""Test fixtures: build a small twin database once per session (60 vehicles),
then expose both a session factory and a TestClient wired to it."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.ingestion.pipeline import IngestionPipeline  # noqa: E402
from app.ingestion.simulator_source import SimulatorDataSource  # noqa: E402
from app.models import Vehicle  # noqa: E402


@pytest.fixture(scope="session")
def twin_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("twindata") / "test.db"
    url = f"sqlite:///{db_file}"
    engine = init_db(url)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = get_settings()
    src = SimulatorDataSource(settings.site_config, scenario="mixed",
                              seed=7, vehicles=60, max_seconds=120_000)
    summary = IngestionPipeline(sf).ingest(src)
    return {"url": url, "sf": sf, "engine": engine, "summary": summary}


@pytest.fixture(scope="session")
def db(twin_db):
    s = twin_db["sf"]()
    yield s
    s.close()


@pytest.fixture(scope="session")
def scrapped_vehicle_id(db):
    v = db.query(Vehicle).filter_by(status="scrapped").first()
    assert v is not None, "fixture run must contain at least one scrapped vehicle"
    return v.id


@pytest.fixture(scope="session")
def client(twin_db):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override():
        db = twin_db["sf"]()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)
