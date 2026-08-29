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

    # --- Observability Advisor (Innovation 1) — classification thresholds ---
    obs_high_confidence: float = 0.75     # >= this => high observability (absent other gaps)
    obs_medium_confidence: float = 0.55   # >= this => medium; below => low
    obs_critical_confidence: float = 0.35  # below => critical observability gap
    obs_low_coverage: float = 0.5         # coverage below this => instrumentation gap
    obs_critical_coverage: float = 0.3    # coverage below this => critical gap
    obs_completeness_min: float = 0.75    # below this => data-quality action
    obs_stale_s: float = 600.0            # freshness beyond this => stale (matches data_quality)

    # --- Safe change validation / shadow simulation (Innovation 3) ---
    maint_window_start_h: float = 6.0     # next maintenance window begins at 06:00 (sim clock)
    maint_window_duration_h: float = 2.0  # window length
    maint_window_interval_h: float = 24.0  # windows repeat daily
    maint_max_queue_items: int = 8        # queue capacity per window (capacity check in UI)


@lru_cache
def get_settings() -> Settings:
    return Settings()
