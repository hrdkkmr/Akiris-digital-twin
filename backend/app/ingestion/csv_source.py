"""CSVDataSource — replays a previously recorded event log (JSONL or CSV).

Also the reference pattern for the future file-drop integrations with MES /
historian exports, and for the public-dataset ADAPTERS (Bosch / SECOM / MIMII):
those adapters only need to translate their records into this normalized event
shape to reuse the entire downstream system.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .base import DataSource, EventHandler, register


@register
class CSVDataSource(DataSource):
    name = "csv"

    def __init__(self, events_path: str, site_config: str, vehicles: int | None = None):
        self.events_path = Path(events_path)
        self.cfg = yaml.safe_load(Path(site_config).read_text())
        self.max_events: int | None = None

    def get_site_config(self) -> dict[str, Any]:
        return self.cfg

    def stream(self, emit: EventHandler) -> dict[str, Any]:
        n = 0
        if self.events_path.suffix == ".jsonl":
            with self.events_path.open() as fh:
                for line in fh:
                    if line.strip():
                        emit(json.loads(line))
                        n += 1
        else:
            with self.events_path.open() as fh:
                for row in csv.DictReader(fh):
                    rec: dict[str, Any] = dict(row)
                    for key in ("t", "cycle_time", "value", "utilization"):
                        if key in rec and rec[key] not in (None, ""):
                            rec[key] = float(rec[key])
                    emit(rec)
                    n += 1
                    if self.max_events and n >= self.max_events:
                        break
        return {"events_replayed": n, "source": str(self.events_path)}
