"""Prometheus instrumentation: HTTP counters/histograms + twin-state gauges.

Design: request metrics are recorded in the ASGI middleware (cheap, always on).
Twin gauges are refreshed on /metrics scrape via refresh_twin_gauges() — pull
model fitted for Prometheus (scrape-time freshness, no background threads).
Production note: twin gauges read ONLY aggregate counters, so scrapes stay O(1)
and cheap even on large databases.
"""
from __future__ import annotations

import logging

from fastapi import Response
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram,
                               generate_latest)
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import DataQualityMetric, ModelVersion, Prediction, Station

access_log = logging.getLogger("twinline.access")

HTTP_REQUESTS = Counter(
    "twinline_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "twinline_http_request_duration_seconds", "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0))

ACTIVE_MODEL_VERSION = Gauge(
    "twinline_active_model_version",
    "Numeric cluster id of the currently registered defect_risk model version")
AT_RISK_VEHICLES = Gauge(
    "twinline_at_risk_vehicles",
    "Vehicles whose LATEST prediction is above the model's tuned threshold")
PREDICTIONS_RESOLVED = Gauge(
    "twinline_predictions_resolved_total", "Predictions resolved against outcomes")
TOP_BOTTLENECK_SCORE = Gauge(
    "twinline_top_bottleneck_score", "Composite score of the current top bottleneck")
TOP_BOTTLENECK_STATION = Gauge(
    "twinline_top_bottleneck_station_seq",
    "Seq id of the current top bottleneck station")
MEAN_ANALYTICS_CONFIDENCE = Gauge(
    "twinline_mean_analytics_confidence",
    "Mean per-station analytics confidence from the latest data-quality pass")


def route_template(scope) -> str:
    """Low-cardinality route label (falls back to raw path for 404s)."""
    route = scope.get("route")
    if route is not None:
        return getattr(route, "path", None) or scope.get("path", "unknown")
    return scope.get("path", "unknown")


def refresh_twin_gauges(db: Session, line_id: int) -> None:
    """Refresh twin-state gauges. Aggregate queries only — scrape stays cheap."""
    mv = (db.query(func.max(ModelVersion.id), func.max(ModelVersion.version))
          .filter(ModelVersion.name == "defect_risk").all()[0])
    if mv[0] is not None:
        ACTIVE_MODEL_VERSION.set(float(mv[1] or 0))
        thr = (db.query(ModelVersion.metrics)
               .filter(ModelVersion.id == mv[0]).scalar() or {}
               ).get("decision_threshold", 0.5)
        latest = (db.query(Prediction.vehicle_id, func.max(Prediction.id).label("mid"))
                  .group_by(Prediction.vehicle_id).subquery())
        AT_RISK_VEHICLES.set(
            db.query(Prediction).join(latest, Prediction.id == latest.c.mid)
            .filter(Prediction.defect_probability >= thr).count())
        PREDICTIONS_RESOLVED.set(
            db.query(Prediction).filter(Prediction.model_version_id == mv[0],
                                        Prediction.outcome.isnot(None)).count())

    from ..services.bottleneck import compute_bottlenecks  # local: avoid cycle
    bn = compute_bottlenecks(db, line_id)
    if bn.get("top"):
        TOP_BOTTLENECK_SCORE.set(bn["top"]["score"])
        TOP_BOTTLENECK_STATION.set(bn["top"]["seq"])

    latest_c = db.query(func.max(DataQualityMetric.computed_at)).scalar()
    if latest_c is not None:
        vals = [v for (v,) in db.query(DataQualityMetric.prediction_confidence)
                .filter(DataQualityMetric.computed_at == latest_c,
                        DataQualityMetric.prediction_confidence.isnot(None)).all()]
        if vals:
            MEAN_ANALYTICS_CONFIDENCE.set(sum(vals) / len(vals))


def metrics_response(db: Session, line_id: int) -> Response:
    try:
        refresh_twin_gauges(db, line_id)
    except Exception as exc:  # noqa: BLE001 - scrapes must never 500
        access_log.warning("twin gauge refresh failed: %s", exc)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
