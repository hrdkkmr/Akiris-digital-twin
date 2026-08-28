"""Ops endpoints: run simulation, ingest files, refresh ML/analytics."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.config import ROOT, get_settings
from ..db.session import Base, SessionLocal, make_engine
from ..ingestion.csv_source import CSVDataSource
from ..ingestion.pipeline import IngestionPipeline
from ..ingestion.simulator_source import SimulatorDataSource
from ..models import Station
from ..ml import anomaly as anomaly_service
from ..ml import defect_model
from ..schemas.payloads import IngestRequest, InjectionRequest, SimRunRequest
from ..services import data_quality as dq_service
from ..services import injection as injection_service
from ..services import recommendations as rec_service
from .deps import get_db, get_line_or_404, require_api_key

# guard applies only to MUTATIONS (GET metadata like /injection/kinds stays open)
router = APIRouter(tags=["ops"],
                   dependencies=[Depends(require_api_key)])


def _wipe(db: Session, line_id: int) -> None:
    """Demo-grade reset: drop + recreate all tables (fresh scenario run)."""
    engine = db.bind
    db.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@router.post("/simulation/run")
def run_simulation(req: SimRunRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    line = None
    try:
        line = get_line_or_404(db, None)
    except HTTPException:
        pass
    if line and not req.fresh:
        raise HTTPException(409, "database already contains a production run — "
                                 "pass fresh=true to wipe and rebuild")
    if line and req.fresh:
        _wipe(db, line.id)
    src = SimulatorDataSource(settings.site_config, scenario=req.scenario,
                              seed=req.seed, vehicles=req.vehicles,
                              max_seconds=settings.max_sim_seconds)
    pipeline = IngestionPipeline(SessionLocal)
    summary = pipeline.ingest(src)
    return {"status": "ingested", **{k: summary[k] for k in
            ("scenario", "spawned", "completed", "scrapped", "bad_batches",
             "ingest_stats", "wall_seconds") if k in summary}}


@router.post("/data/ingest")
def ingest_file(req: IngestRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    path = Path(req.events_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise HTTPException(404, f"events file not found: {path}")
    try:
        get_line_or_404(db, None)
        raise HTTPException(409, "database already populated — use a fresh database")
    except HTTPException as e:
        if e.status_code == 409:
            raise
    src = CSVDataSource(str(path), settings.site_config)
    summary = IngestionPipeline(SessionLocal).ingest(src)
    return {"status": "ingested", "summary": summary}


@router.post("/ml/refresh")
def ml_refresh(db: Session = Depends(get_db)):
    """Train/evaluate defect model, score vehicles, resolve outcomes, run
    anomaly detection, recompute observability, regenerate recommendations."""
    line = get_line_or_404(db, None)
    result: dict = {}
    # anomaly pass first: event anomaly scores feed defect-model features
    result["anomalies"] = anomaly_service.detect_anomalies(db, line.id)
    result["defect_model"] = defect_model.train_defect_model(db, line.id)
    if "error" not in result["defect_model"]:
        result["scoring"] = defect_model.score_vehicles(db, line.id)
    result["data_quality_rows"] = len(
        dq_service.compute_station_data_quality(db, line.id, persist=True))
    result["recommendations"] = rec_service.generate_recommendations(db, line.id)
    return result


@router.get("/injection/kinds")
def injection_kinds():
    """Metadata for the UI's scenario-injection buttons (open read path)."""
    return {"kinds": injection_service.describe_kinds()}


@router.post("/injection/inject")
def inject(req: InjectionRequest, db: Session = Depends(get_db)):
    """Live twin continuation with an injected disruption (demo/drill layer).

    Appends a continuation run to the existing database (no wipe), then
    refreshes anomalies, data quality and recommendations so the twin reacts.
    Defect-model retrain stays a deliberate step (POST /ml/refresh).
    """
    line = get_line_or_404(db, None)
    try:
        return injection_service.run_injection(
            db, line.id, session_factory=SessionLocal,
            kind=req.kind, vehicles=req.vehicles, seed=req.seed,
            target_station=req.target_station)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
