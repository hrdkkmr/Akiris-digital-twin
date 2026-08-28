"""Twin topology: Plant -> ProductionLine -> Station (+StationType, Sensor).

Station rows are generated FROM the site config (archetypes); nothing about the
42-station automotive line is hard-coded in application logic.
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.session import Base


class Plant(Base):
    __tablename__ = "plants"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    industry: Mapped[str] = mapped_column(String(64), default="automotive")
    lines: Mapped[list["ProductionLine"]] = relationship(back_populates="plant")


class ProductionLine(Base):
    __tablename__ = "production_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    takt_seconds: Mapped[float] = mapped_column(Float, default=45.0)
    scenario: Mapped[str] = mapped_column(String(32), default="mixed")
    config_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    plant: Mapped[Plant] = relationship(back_populates="lines")
    stations: Mapped[list["Station"]] = relationship(back_populates="line",
                                                     order_by="Station.seq")


class StationType(Base):
    """Station archetype (welding, torque, painting, ...) — the transfer unit
    for future cross-plant transfer learning."""
    __tablename__ = "station_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)   # welding / torque / ...
    sensors_expected: Mapped[list] = mapped_column(JSON, default=list)


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)                    # process order 1..N
    code: Mapped[str] = mapped_column(String(16), index=True)    # S01…S42
    zone: Mapped[str] = mapped_column(String(32), index=True)    # body/paint/final
    type_id: Mapped[int] = mapped_column(ForeignKey("station_types.id"), index=True)
    sensor_profile: Mapped[str] = mapped_column(String(16))      # full/mid/sparse/manual
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    has_tool: Mapped[bool] = mapped_column(Boolean, default=False)
    is_inspection: Mapped[bool] = mapped_column(Boolean, default=False)
    env_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline_cycle_mu: Mapped[float] = mapped_column(Float)
    baseline_cycle_sigma: Mapped[float] = mapped_column(Float)
    line: Mapped[ProductionLine] = relationship(back_populates="stations")


class Sensor(Base):
    """A physical sensor instance. Absence of a row = station never had the sensor
    (distinct from 'unavailable'/'malfunctioning', which have status != ok)."""
    __tablename__ = "sensors"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok/unavailable/malfunction
