"""Factory Setup API — configure any factory, then use it as the Digital Twin.

Endpoints
  GET    /factories                -> list all factories (+ line/coverage summary)
  POST   /factories                -> create a factory (validate + persist + provision)
  GET    /factories/active         -> currently active factory/line
  GET    /factories/{factory_id}   -> full detail (stations, sensors, coverage)
  POST   /factories/{factory_id}/activate  -> switch the whole dashboard to this factory
  POST   /factories/{factory_id}/simulate  -> labeled simulation-data generation

The configured factory becomes part of the EXISTING twin: Plant/ProductionLine/
Station/Sensor rows are provisioned through the ingestion pipeline, and every
analytics endpoint that resolves a line by default follows TwinContext (the
factory selector). Mutations are guarded by the same API-key dependency as ops.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..services import factory_config as fc
from .deps import get_db, require_api_key

router = APIRouter(tags=["factory"],
                   prefix="/factories",
                   dependencies=[Depends(require_api_key)])


def _resolve(fn, *args):
    """Map service errors to HTTP errors with human-readable messages."""
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
def list_factories(db: Session = Depends(get_db)):
    return fc.list_factories(db)


@router.get("/active")
def active_factory(db: Session = Depends(get_db)):
    return fc.active_context(db)


@router.post("")
def create_factory(payload: dict, db: Session = Depends(get_db)):
    if not isinstance(payload, dict) or "factory" not in payload or "lines" not in payload:
        raise HTTPException(422, "Payload must include 'factory' and 'lines'.")
    return _resolve(fc.provision_factory, db, payload)


@router.get("/{factory_id}")
def factory_detail(factory_id: str, db: Session = Depends(get_db)):
    return _resolve(fc.factory_detail, db, factory_id.upper())


@router.post("/{factory_id}/activate")
def activate(factory_id: str, db: Session = Depends(get_db)):
    return _resolve(fc.activate_factory, db, factory_id.upper())


@router.post("/{factory_id}/simulate")
def simulate(factory_id: str,
             vehicles: int = Query(400, ge=50, le=5000),
             seed: int = Query(42),
             db: Session = Depends(get_db)):
    return _resolve(fc.simulate_factory, db, factory_id.upper(), vehicles, seed)
