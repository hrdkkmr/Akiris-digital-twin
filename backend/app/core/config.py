"""Central configuration — every value env-overridable (req: env-based config)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # digital-twin/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), env_prefix="TWIN_", extra="ignore")

    # database: sqlite zero-config locally; postgres in docker (DATABASE_URL)
    database_url: str = f"sqlite:///{ROOT / 'data' / 'generated' / 'twinline.db'}"

    # paths
    site_config: str = str(ROOT / "configs" / "automotive_line.yaml")
    scenario_dir: str = str(ROOT / "configs" / "scenarios")
    model_dir: str = str(ROOT / "data" / "models")

    # generator defaults (all overridable via API/CLI too)
    default_seed: int = 42
    default_vehicles: int = 2000
    max_sim_seconds: float = 400_000.0

    # ingest tuning
    bulk_chunk: int = 5000
    raw_sensor_stream: bool = False  # True = store every raw reading (heavy)

    # api hardening (production posture)
    cors_origins: str = "*"      # comma-separated; tighten per deployment
    api_key: str | None = None   # set TWIN_API_KEY to require X-API-Key on mutating ops endpoints
    log_level: str = "INFO"

    # business assumptions (configurable — never hard-coded claims)
    cost_per_scrapped_vehicle: float = 1500.0
    cost_downtime_per_hour: float = 260_000.0 * 0.005  # line segment share of plant-level benchmark
    planned_annual_vehicles: int = 250_000
    assumed_defect_reduction_pct: float = 0.15   # scenario knob, labeled as assumption
    assumed_downtime_reduction_pct: float = 0.05


@lru_cache
def get_settings() -> Settings:
    return Settings()
