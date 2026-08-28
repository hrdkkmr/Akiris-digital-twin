"""Analytics entities: anomalies, predictions (+outcome resolution for trust),
recommendations, model registry, data-quality/observability metrics."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.session import Base


class Anomaly(Base):
    __tablename__ = "anomalies"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True, index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    t: Mapped[float] = mapped_column(Float, index=True)
    detector: Mapped[str] = mapped_column(String(32), default="isolation_forest")
    score: Mapped[float] = mapped_column(Float)                  # 0..1 (higher = stranger)
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    features: Mapped[dict] = mapped_column(JSON, default=dict)


class Prediction(Base):
    """Every defect-risk prediction, resolved later against the actual outcome
    (PS: 'predictive claims must be validated against real outcomes over time')."""
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    created_at: Mapped[float] = mapped_column(Float)             # sim time of prediction
    as_of_seq: Mapped[int] = mapped_column(Integer)              # line position when predicted
    defect_probability: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)             # 0..1
    data_completeness: Mapped[float] = mapped_column(Float)      # 0..1
    top_features: Mapped[list] = mapped_column(JSON, default=list)
    outcome: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # resolved later
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[float] = mapped_column(Float)
    scope: Mapped[str] = mapped_column(String(16))               # station/vehicle/batch/line
    ref_code: Mapped[str] = mapped_column(String(32), index=True)
    issue: Mapped[str] = mapped_column(String(256))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8), default="medium")   # low/medium/high
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="advisory")  # always advisory in V1


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    algo: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16))
    trained_at: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)    # precision/recall/F1/FPR/FNR/AUC
    artifact_path: Mapped[str] = mapped_column(String(256))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataQualityMetric(Base):
    """Station observability snapshot — groundwork for the future
    Observability Score / Sensor-ROI advisor."""
    __tablename__ = "data_quality_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    computed_at: Mapped[float] = mapped_column(Float)
    sensor_coverage: Mapped[float] = mapped_column(Float)        # have vs full instrumentation
    completeness: Mapped[float] = mapped_column(Float)           # ok vs expected readings
    freshness_s: Mapped[float] = mapped_column(Float)            # age of newest reading
    anomaly_rate: Mapped[float] = mapped_column(Float)
    prediction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
