"""Request payloads (POST bodies) — validated at the edge."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SimRunRequest(BaseModel):
    scenario: Literal["full", "mixed", "brownfield"] = "mixed"
    vehicles: int = Field(default=200, ge=10, le=500,
                          description="API runs are capped at 500 vehicles; use "
                                      "scripts/generate_data.py for 10k+ builds")
    seed: int = 42
    fresh: bool = Field(default=False,
                        description="true = wipe and rebuild the line from scratch")


class IngestRequest(BaseModel):
    source: Literal["csv"] = "csv"
    events_path: str = Field(..., description="path to a normalized JSONL/CSV event log")


class InjectionRequest(BaseModel):
    kind: Literal["tool_drift_surge", "supplier_batch_failure",
                  "sensor_outage", "bottleneck_shock"]
    vehicles: int = Field(default=300, ge=20, le=600,
                          description="vehicles to continue the line with "
                                      "(kept small so demos stay interactive)")
    target_station: str | None = Field(
        default=None, description="station code for bottleneck_shock (default S20)")
    seed: int | None = None


class TruthParam(BaseModel):
    truth: bool = False
