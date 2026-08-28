"""Production execution entities: batches, vehicles, events, readings,
inspections, defects, machine events, KPI snapshots, environment samples."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.session import Base


class ProductionBatch(Base):
    __tablename__ = "production_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)    # B001…
    first_seen: Mapped[float] = mapped_column(Float)
    vehicle_count: Mapped[int] = mapped_column(Integer, default=0)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), index=True)
    vin: Mapped[str] = mapped_column(String(16), index=True)     # V000001…
    variant: Mapped[str] = mapped_column(String(16), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id"), index=True)
    started_at: Mapped[float] = mapped_column(Float)
    completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="wip", index=True)  # wip/completed/scrapped
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class VehicleEvent(Base):
    """One station visit in a vehicle's genealogy (digital thread)."""
    __tablename__ = "vehicle_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    entered_at: Mapped[float] = mapped_column(Float)
    exited_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    cycle_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    cycle_dev: Mapped[float | None] = mapped_column(Float, nullable=True)   # vs archetype baseline
    queue_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checklist_result: Mapped[str | None] = mapped_column(String(8), nullable=True)  # manual stations
    inspection_result: Mapped[str | None] = mapped_column(String(8), nullable=True)  # pass/fail
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    internal_flags: Mapped[list] = mapped_column(JSON, default=list)  # SIM ground truth (judge mode only)


class SensorReading(Base):
    """Per-cycle aggregate of one sensor for one vehicle (V1 default).
    Raw per-sample stream is available via TWIN_RAW_SENSOR_STREAM=true."""
    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    sensor_name: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(16))
    t: Mapped[float] = mapped_column(Float, index=True)
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    std: Mapped[float | None] = mapped_column(Float, nullable=True)
    min: Mapped[float | None] = mapped_column(Float, nullable=True)
    max: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok/missing_random/unavailable
    raw: Mapped[list | None] = mapped_column(JSON, nullable=True)  # raw samples when enabled


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    t: Mapped[float] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(8))               # pass/fail
    defect_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Defect(Base):
    __tablename__ = "defects"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)  # where FOUND
    t: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16), default="scrap")
    true_root_causes: Mapped[list] = mapped_column(JSON, default=list)  # sim ground truth (evaluation only)


class MachineEvent(Base):
    __tablename__ = "machine_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    t: Mapped[float] = mapped_column(Float)
    event: Mapped[str] = mapped_column(String(32))               # maintenance_start/end
    wear: Mapped[float | None] = mapped_column(Float, nullable=True)


class StationKpi(Base):
    __tablename__ = "station_kpis"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    t: Mapped[float] = mapped_column(Float, index=True)
    queue_len: Mapped[int] = mapped_column(Integer)
    utilization: Mapped[float] = mapped_column(Float)
    wear: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[int] = mapped_column(Integer)


class EnvironmentSample(Base):
    __tablename__ = "environment_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    t: Mapped[float] = mapped_column(Float, index=True)
    temp_c: Mapped[float] = mapped_column(Float)
    humidity: Mapped[float] = mapped_column(Float)
