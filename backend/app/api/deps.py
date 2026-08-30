"""Shared API dependencies + helpers."""
from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..db.session import get_db  # noqa: F401  (re-export for routers)
from ..models import ProductionLine, Station, TwinContext, Vehicle


def require_api_key(request: Request,
                    x_api_key: str | None = Header(default=None)) -> None:
    """Guard for mutating ops endpoints (router-level dependency).

    Only mutations are guarded: GET/HEAD/OPTIONS (e.g. /injection/kinds
    metadata for the UI) always pass. Dev default: TWIN_API_KEY unset ->
    open. Production: set TWIN_API_KEY -> every mutation must carry a
    matching `X-API-Key` header. Env is read per-request so keys can be
    rotated or toggled (tests) without restarts.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    required = os.environ.get("TWIN_API_KEY")
    if required and x_api_key != required:
        raise HTTPException(401, "mutating endpoints require a valid X-API-Key header")


def get_line_or_404(db: Session, line_id: int | None) -> ProductionLine:
    """Resolve the line an endpoint should read.

    When ``line_id`` is given it wins (explicit). When it is None the
    factory-selector context is honored (``TwinContext.active_line_id``) so the
    whole dashboard follows the selected factory; falls back to the first line
    for backward compatibility / fresh databases.
    """
    if line_id is not None:
        line = db.get(ProductionLine, line_id)
    else:
        ctx = db.get(TwinContext, 1)
        line = db.get(ProductionLine, ctx.active_line_id) if ctx and ctx.active_line_id else None
        if line is None:
            line = db.query(ProductionLine).order_by(ProductionLine.id).first()
    if not line:
        raise HTTPException(404, "production line not found — run data generation first")
    return line


def get_station_or_404(db: Session, station_id: int) -> Station:
    st = db.get(Station, station_id)
    if not st:
        raise HTTPException(404, f"station {station_id} not found")
    return st


def get_vehicle_or_404(db: Session, vehicle_id: int) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, f"vehicle {vehicle_id} not found")
    return v
