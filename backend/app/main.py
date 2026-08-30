"""TwinLine Digital Twin — FastAPI entrypoint.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000   (from backend/)
Docs: /docs (Swagger)  ·  /redoc  ·  /metrics (Prometheus)

Production posture: structured access logging with request-ids, env-toggled
CORS, health + readiness probes, optional API-key guard on mutating ops
endpoints (TWIN_API_KEY), per-IP mutation rate limiting (TWIN_RATE_LIMIT_PER_MIN),
security headers, Prometheus metrics, Alembic migrations under backend/alembic/.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .api import (routes_analytics, routes_factory, routes_fleet, routes_meta,
                  routes_ops, routes_production)
from .api.deps import get_db, get_line_or_404
from .core import metrics as prom
from .core.config import get_settings
from .core.rate_limit import RateLimitMiddleware
from .db.session import SessionLocal, init_db

__version__ = "0.3.0"

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
access_log = logging.getLogger("twinline.access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # dev convenience; production path: alembic upgrade head
    yield


app = FastAPI(
    title="TwinLine — Brownfield-Aware Digital Twin API",
    version=__version__,
    description=("Digital twin for a mixed-model vehicle assembly line: bottleneck "
                 "evidence, defect-risk prediction with confidence, production "
                 "genealogy, advisory recommendations. Read-only/shadow-mode by design."),
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)  # mutations only; env-tunable

_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "strict-transport-security": "max-age=86400",  # preview/tunnel is TLS; raise in prod
    # Swagger UI loads its assets from jsDelivr by default (FastAPI /docs)
    "content-security-policy": ("default-src 'self'; "
                                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                "img-src 'self' data:; connect-src 'self'"),
}


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request-id propagation + access logging + Prometheus + security headers."""
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - t0
    response.headers["x-request-id"] = rid
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    route = request.scope.get("path", "unknown")  # set after routing: prefer template
    access_log.info("%s %s %s -> %d %.1fms", rid, request.method, route,
                    response.status_code, elapsed * 1000)
    prom.HTTP_REQUESTS.labels(request.method, prom.route_template(request.scope),
                              str(response.status_code)).inc()
    prom.HTTP_LATENCY.labels(request.method, prom.route_template(request.scope)) \
                     .observe(elapsed)
    return response


for r in (routes_meta.router, routes_fleet.router, routes_analytics.router,
          routes_production.router, routes_ops.router, routes_factory.router):
    app.include_router(r)


@app.get("/", include_in_schema=False)
def root():
    """Service root -> Swagger UI (the API's front door)."""
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    """Liveness: process is up."""
    return {"status": "ok", "service": "twinline-api", "version": __version__}


@app.get("/ready")
def ready():
    """Readiness: database reachable (container orchestrator gate)."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready", "version": __version__}
    except Exception as exc:  # noqa: BLE001 - readiness must answer, not crash
        access_log.error("readiness probe failed: %s", exc)
        return JSONResponse({"status": "not_ready", "detail": str(exc)},
                            status_code=503)


@app.get("/metrics", include_in_schema=False)
def metrics(db: Session = Depends(get_db)):
    """Prometheus scrape endpoint (HTTP + twin-state gauges)."""
    line = get_line_or_404(db, None)
    return prom.metrics_response(db, line.id)
