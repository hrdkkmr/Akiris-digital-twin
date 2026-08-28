"""Discrete-event assembly-line engine (SimPy).

Emits a replayable event log: part_enter/part_exit, sensor readings (per profile,
with random missingness), manual checklists, maintenance events, environment
telemetry, KPI snapshots (queue length, utilization, tool wear), and defect events
with ground-truth contributing stations.

Bottleneck realism (serial line, capacity>1 at parallel stations):
  utilization_i ~= (mu_i / capacity_i) / takt  — S17 is engineered saturated,
  S26 hides behind it (shadowing effect). Arrival throttling by the real BN
  makes the 2nd BN look healthy — exactly what the KPI paper describes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import simpy

from .emit import EventSink
from .mechanisms import MechanismEngine
from .part import Part

SENSOR_UNITS = {"torque": "Nm", "vibration": "mm/s", "temperature": "C",
                "motor_current": "A", "humidity": "%RH"}
STATION_HEAT = {"welding": 22.0, "painting": 18.0, "curing": 26.0}  # °C above ambient


@dataclass
class Station:
    id: str
    zone: str
    archetype: str
    mu: float
    sigma: float
    capacity: int
    profile: str
    tool: str | None
    base_defect: float
    env_sensitive: bool
    is_inspection: bool
    sensors: list[str]

    @classmethod
    def from_config(cls, entry: dict, archetypes: dict, profiles: dict) -> "Station":
        a = dict(archetypes[entry["archetype"]])
        a.update(entry.get("overrides", {}))
        profile = a["sensor_profile"]
        return cls(
            id=entry["id"], zone=entry["zone"], archetype=entry["archetype"],
            mu=float(a["cycle_mu"]), sigma=float(a["cycle_sigma"]),
            capacity=int(a.get("capacity", 1)), profile=profile,
            tool=a.get("tool"), base_defect=float(a.get("base_defect", 0.0)),
            env_sensitive=bool(a.get("env_sensitive", False)),
            is_inspection=bool(a.get("is_inspection", False)),
            sensors=list(profiles.get(profile, [])),
        )


class LineSim:
    def __init__(self, cfg: dict, seed: int, sink: EventSink):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.env = simpy.Environment()
        self.sink = sink
        self.mech = MechanismEngine(cfg, self.rng)
        self.stations = [Station.from_config(e, cfg["archetypes"], cfg["sensor_profiles"])
                         for e in cfg["stations"]]
        self.res = {s.id: simpy.Resource(self.env, capacity=s.capacity) for s in self.stations}
        self.proc_time: dict[str, float] = defaultdict(float)
        self.maint_time: dict[str, float] = defaultdict(float)
        self.parts_spawned = 0
        self.parts_completed = 0
        self.defects: list[dict] = []
        self.miss_p = cfg["injection"]["sensor_dropout_prob"]
        self.maint_trigger = cfg["mechanisms"]["tool_wear"]["maintenance_trigger"]
        self.maint_min = cfg["mechanisms"]["tool_wear"]["maintenance_minutes"]
        self._variant_map = {v["id"]: v["factor"] for v in cfg["demand"]["product_variants"]}
        self._variant_ids = [v["id"] for v in cfg["demand"]["product_variants"]]
        self._variant_p = [v["share"] for v in cfg["demand"]["product_variants"]]

    # ---------------- processes ----------------
    def source(self):
        dem = self.cfg["demand"]
        while True:
            ia = max(1.0, self.rng.normal(dem["interarrival_sec"],
                                          dem.get("interarrival_sigma", 2.0)))
            yield self.env.timeout(ia)
            self.parts_spawned += 1
            batch = f"B{(self.parts_spawned - 1) // dem['batch_size_parts'] + 1:03d}"
            variant = self.rng.choice(self._variant_ids, p=self._variant_p)
            part = Part(id=f"V{self.parts_spawned:06d}", batch=batch, variant=str(variant),
                        variant_factor=self._variant_map[str(variant)], born=self.env.now,
                        fail_threshold=float(self.rng.random()))
            self.env.process(self.process_part(part))

    def kpi_logger(self, interval: float = 60.0):
        while True:
            yield self.env.timeout(interval)
            now = self.env.now
            self.sink.emit(now, "environment", temp_c=round(self.mech.ambient_temp(now), 2),
                           humidity=round(self.mech.humidity(now), 1))
            for st in self.stations:
                res = self.res[st.id]
                busy = self.proc_time[st.id] + self.maint_time[st.id]
                self.sink.emit(now, "kpi", station=st.id,
                               queue_len=len(res.queue),
                               utilization=round(busy / max(now * st.capacity, 1e-9), 4),
                               wear=round(self.mech.tool_wear_level(st.id), 4) if st.tool else None,
                               completed=self.parts_completed)

    # ---------------- part flow ----------------
    def process_part(self, part: Part):
        for st in self.stations:
            res = self.res[st.id]
            with res.request() as req:
                yield req
                if part.scrapped:
                    return
                # --- scheduled maintenance (tool wear) — holds the resource like real life
                wear = self.mech.tool_wear_level(st.id) if st.tool else 0.0
                if st.tool and wear >= self.maint_trigger:
                    t_m = self.env.now
                    self.sink.emit(t_m, "machine_event", station=st.id,
                                   event="maintenance_start", wear=round(wear, 3), part=part.id)
                    yield self.env.timeout(self.maint_min * 60.0)
                    self.mech.reset_tool(st.id)
                    self.maint_time[st.id] += self.env.now - t_m
                    self.sink.emit(self.env.now, "machine_event", station=st.id,
                                   event="maintenance_end", part=part.id)
                # --- processing
                t0 = self.env.now
                shift_var = self.mech.shift_variance_factor(t0)
                cycle = max(1.0, self.rng.normal(st.mu * part.variant_factor,
                                                 st.sigma * shift_var))
                self.sink.emit(t0, "part_enter", station=st.id, part=part.id,
                               batch=part.batch, variant=part.variant,
                               queue_seen=len(res.queue))
                yield self.env.timeout(cycle)
                self.proc_time[st.id] += cycle
                t1 = self.env.now
                # --- defect mechanisms hit quality; genealogy remembers everything
                f = self.mech.factors(st, part, t0)
                risk = min(st.base_defect * f["tool"] * f["batch"] * f["shift"] * f["env"], 0.5)
                if risk > 0:
                    part.add_risk(st.id, risk, f["flags"])
                part.quality *= (1.0 - risk)
                self.mech.step_wear(st.id, bool(st.tool))
                self.sink.emit(t1, "part_exit", station=st.id, part=part.id,
                               cycle_time=round(cycle, 2), risk=round(risk, 6),
                               flags=f["flags"], part_quality=round(part.quality, 5))
                self._emit_sensors(st, t0, cycle, wear, part)
                if st.profile == "manual":
                    self._emit_checklist(st, t1, risk, part)
                # --- delayed defect surfacing (PS complexity #4)
                if st.is_inspection and not part.scrapped:
                    # latent-defect model: ONE Bernoulli draw (fail_threshold) per part at
                    # birth; defect surfaces at the FIRST inspection whose accumulated
                    # quality loss exceeds it -> delayed surfacing, correct marginal P(defect)
                    if (1.0 - part.quality) > part.fail_threshold:
                        part.scrapped = True
                        causes = [{"station": s, "contribution": round(c, 5)}
                                  for s, c in part.top_causes(3)]
                        self.sink.emit(t1, "defect", station=st.id, part=part.id,
                                       batch=part.batch, zone=st.zone, top_causes=causes)
                        self.defects.append({"part": part.id, "at": st.id, "t": round(t1, 1),
                                             "causes": causes})
                        return
        self.parts_completed += 1
        self.sink.emit(self.env.now, "part_complete", part=part.id,
                       lead_time=round(self.env.now - part.born, 1),
                       quality=round(part.quality, 5))

    # ---------------- emissions ----------------
    def _emit_sensors(self, st: Station, t0: float, cycle: float,
                      wear: float, part: Part) -> None:
        if not st.sensors:
            return
        for frac in (0.15, 0.55, 0.9):  # samples within the cycle
            ts = t0 + frac * cycle
            for name in st.sensors:
                if self.rng.random() < self.miss_p:  # random missingness
                    continue
                val = self._sensor_value(name, st, wear, ts)
                self.sink.emit(ts, "sensor", station=st.id, sensor=name,
                               value=round(val, 3), unit=SENSOR_UNITS[name], part=part.id)

    def _sensor_value(self, name: str, st: Station, wear: float, ts: float) -> float:
        amb = self.mech.ambient_temp(ts) + STATION_HEAT.get(st.archetype, 8.0)
        if name == "torque":
            return self.rng.normal(34.0 + 6.0 * wear, 1.8 * (1.0 + 6.0 * wear))
        if name == "vibration":
            return abs(self.rng.normal(1.8 + 2.5 * wear, 0.35 * (1.0 + 3.0 * wear)))
        if name == "temperature":
            return self.rng.normal(amb, 0.8)
        if name == "motor_current":
            return self.rng.normal(12.0 + 4.0 * wear, 0.6)
        return self.rng.normal(0, 1)

    def _emit_checklist(self, st: Station, t1: float, risk: float, part: Part) -> None:
        nok_p = min(risk * 4.0, 0.30)  # operators catch a fraction of problems
        result = "NOK" if self.rng.random() < nok_p else "OK"
        self.sink.emit(t1, "checklist", station=st.id, part=part.id, result=result,
                       operator=f"OP{int(t1 // self.mech.shift_len) % 6 + 1}")

    # ---------------- run ----------------
    def run(self, until: float) -> dict:
        self.env.process(self.source())
        self.env.process(self.kpi_logger(60.0))
        self.env.run(until=until)
        return self._summary(max(self.env.now, 1.0))

    def run_target(self, target_finished: int, max_until: float = 400_000.0) -> dict:
        """Run until `target_finished` vehicles leave the line (completed or
        scrapped), so dataset size is expressed in vehicles, not sim-seconds."""
        self.env.process(self.source())
        self.env.process(self.kpi_logger(60.0))
        finished = lambda: self.parts_completed + len(self.defects)  # noqa: E731
        while self.env.peek() < max_until and finished() < target_finished:
            self.env.step()
        summary = self._summary(max(self.env.now, 1.0))
        summary["sim_seconds"] = round(self.env.now, 1)
        return summary

    def _summary(self, until: float) -> dict:
        util = {st.id: round((self.proc_time[st.id] + self.maint_time[st.id])
                             / (until * st.capacity), 4)
                for st in self.stations}
        return {
            "spawned": self.parts_spawned,
            "completed": self.parts_completed,
            "scrapped": len(self.defects),
            "bad_batches": self.mech.bad_batches,
            "utilization": dict(sorted(util.items(), key=lambda kv: -kv[1])),
            "defects_sample": self.defects[:5],
            "event_counts": dict(self.sink.counts),
        }


def load_config(path: str) -> dict:
    import yaml
    with open(path) as fh:
        return yaml.safe_load(fh)
