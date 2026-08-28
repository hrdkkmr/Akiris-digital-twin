"""SimulatorDataSource — drives the SimPy assembly-line engine and streams its
events straight into the ingestion pipeline (no intermediate files, no OOM).

Scenario files (configs/scenarios/*.yaml) can override sensor profiles and
injection rates WITHOUT touching the site config — this is how the three
coverage worlds (full / mixed / brownfield) are produced.
"""
from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from ..simulation.engine import LineSim
from .base import DataSource, EventHandler, register


class _CallbackSink:
    """EventSink-compatible adapter: no files, no MQTT — straight to handler.

    t_offset shifts every emitted timestamp (injection-window continuations:
    the ENGINE restarts its internal clock at 0, the twin's timeline must not).
    """

    def __init__(self, emit: EventHandler, t_offset: float = 0.0):
        self._emit = emit
        self.t_offset = t_offset
        self.counts: Counter = Counter()

    @property
    def mqtt_online(self) -> bool:
        return False

    def emit(self, t: float, type: str, station: str | None = None, **fields):  # noqa: A002
        rec = {"t": round(float(t) + self.t_offset, 2), "type": type}
        if station is not None:
            rec["station"] = station
        rec.update(fields)
        self.counts[type] += 1
        self._emit(rec)
        return rec

    def close(self) -> None:
        pass


@register
class SimulatorDataSource(DataSource):
    name = "simulator"

    def __init__(self, site_config: str, scenario: str | None = None,
                 seed: int = 42, vehicles: int = 2000,
                 max_seconds: float = 400_000.0):
        self.cfg = self._load_merged(site_config, scenario)
        self.scenario = scenario or "mixed"
        self.seed = seed
        self.vehicles = vehicles
        self.max_seconds = max_seconds

    @staticmethod
    def _load_merged(site_config: str, scenario: str | None) -> dict:
        cfg = yaml.safe_load(Path(site_config).read_text())
        if scenario and scenario != "mixed":
            scen_path = Path(site_config).parent / "scenarios" / f"{scenario}.yaml"
            if not scen_path.exists():
                raise FileNotFoundError(f"scenario file not found: {scen_path}")
            scen = yaml.safe_load(scen_path.read_text())
            cfg = copy.deepcopy(cfg)
            prof = (scen.get("archetype_sensor_profile") or {})
            for arch, profile in prof.items():
                if arch in cfg["archetypes"]:
                    cfg["archetypes"][arch]["sensor_profile"] = profile
            for key, val in (scen.get("injection") or {}).items():
                cfg["injection"][key] = val
            cfg.setdefault("site", {})["scenario"] = scenario
        return cfg

    def get_site_config(self) -> dict[str, Any]:
        return self.cfg

    def stream(self, emit: EventHandler) -> dict[str, Any]:
        sink = _CallbackSink(emit)
        sim = LineSim(self.cfg, seed=self.seed, sink=sink)
        summary = sim.run_target(self.vehicles, max_until=self.max_seconds)
        summary["scenario"] = self.scenario
        return summary
