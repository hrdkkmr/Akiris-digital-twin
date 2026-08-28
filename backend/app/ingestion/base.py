"""DataSource abstraction — the seam for future PLC / OPC-UA / MQTT / MES feeds.

V1 sources:  SimulatorDataSource (SimPy line), CSVDataSource (event-log replay).
Future sources (FuturePLCDataSource, FutureMQTTDataSource, FutureOPCUADataSource)
implement the same two-method contract; nothing downstream of `stream()` changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

EventHandler = Callable[[dict], None]


class DataSource(ABC):
    """A DataSource knows its site config and emits normalized event dicts:

    part_enter / part_exit / sensor / checklist / defect / kpi /
    machine_event / environment / part_complete
    """
    name: str = "abstract"

    @abstractmethod
    def get_site_config(self) -> dict[str, Any]:
        """Site configuration (stations/archetypes) so the pipeline can
        upsert plant/line/station/sensor topology before consuming events."""

    @abstractmethod
    def stream(self, emit: EventHandler) -> dict[str, Any]:
        """Feed events to `emit` until the run ends. Returns a run summary."""


_REGISTRY: dict[str, type[DataSource]] = {}


def register(cls: type[DataSource]) -> type[DataSource]:
    _REGISTRY[cls.name] = cls
    return cls


def get_source_class(name: str) -> type[DataSource]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown data source '{name}'. registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]
