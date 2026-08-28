"""The four causal defect mechanisms from the solution design.

A - tool degradation : tool age -> torque/vibration variance -> fastening quality
B - supplier batch   : degraded component batch -> correlated multi-station defects
C - operator shift   : shift change -> cycle-time variance + quality dip (learning curve)
D - environment      : ambient temp/humidity -> paint-process quality

Everything is deterministic given the seed (replayable demos for judges).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

DAY = 24 * 3600.0


class MechanismEngine:
    def __init__(self, cfg: dict, rng: np.random.Generator):
        self.m = cfg["mechanisms"]
        self.env_cfg = cfg["environment"]
        self.rng = rng
        self.tool_wear: dict[str, float] = defaultdict(float)
        self._batch_cache: dict[str, bool] = {}
        self.shift_len = cfg["shifts"]["length_hours"] * 3600.0
        self.learn_window = cfg["shifts"]["learning_window_min"] * 60.0

    # ---- mechanism A: tool wear ----
    def step_wear(self, station_id: str, has_tool: bool) -> None:
        if has_tool and self.m["tool_wear"]["enabled"]:
            self.tool_wear[station_id] += self.m["tool_wear"]["wear_per_cycle"]

    def tool_wear_level(self, station_id: str) -> float:
        return self.tool_wear[station_id]

    def reset_tool(self, station_id: str) -> None:
        self.tool_wear[station_id] = 0.0

    # ---- mechanism B: supplier batch ----
    def batch_is_bad(self, batch_id: str) -> bool:
        if batch_id not in self._batch_cache:
            p = self.m["supplier_batch"]["bad_batch_prob"] if self.m["supplier_batch"]["enabled"] else 0.0
            self._batch_cache[batch_id] = bool(self.rng.random() < p)
        return self._batch_cache[batch_id]

    @property
    def bad_batches(self) -> list[str]:
        return sorted(b for b, bad in self._batch_cache.items() if bad)

    # ---- mechanism C: operator shift (learning curve after shift change) ----
    def _shift_ramp(self, now: float) -> float:
        """1.0 = fully ramped; 0.0 = the moment the shift changed."""
        return min((now % self.shift_len) / self.learn_window, 1.0)

    def shift_variance_factor(self, now: float) -> float:
        if not self.m["operator_shift"]["enabled"]:
            return 1.0
        k = self.m["operator_shift"]["variance_multiplier_new"]
        return 1.0 + (k - 1.0) * (1.0 - self._shift_ramp(now))

    def shift_defect_factor(self, now: float) -> float:
        if not self.m["operator_shift"]["enabled"]:
            return 1.0
        k = self.m["operator_shift"]["defect_multiplier_new"]
        return 1.0 + (k - 1.0) * (1.0 - self._shift_ramp(now))

    # ---- mechanism D: environment ----
    def ambient_temp(self, now: float) -> float:
        phase = (now % DAY) / DAY
        return (self.env_cfg["temp_base_c"]
                + self.env_cfg["temp_amplitude_c"] * np.sin(2 * np.pi * (phase - 0.35)))

    def humidity(self, now: float) -> float:
        phase = (now % DAY) / DAY
        return (self.env_cfg["humidity_base"]
                + self.env_cfg["humidity_amplitude"] * np.sin(2 * np.pi * phase + 1.2)
                + self.rng.normal(0, 1.5))

    # ---- combined multiplicative factors for one station-part interaction ----
    def factors(self, st, part, now: float) -> dict:
        out = {"tool": 1.0, "batch": 1.0, "shift": 1.0, "env": 1.0, "flags": []}
        if st.tool and self.m["tool_wear"]["enabled"]:
            w = self.tool_wear[st.id]
            out["tool"] = 1.0 + self.m["tool_wear"]["risk_growth"] * w * w
            if w > 0.5:
                out["flags"].append("tool_wear")
        if self.m["supplier_batch"]["enabled"] and self.batch_is_bad(part.batch):
            out["batch"] = self.m["supplier_batch"]["defect_multiplier"]
            out["flags"].append("bad_batch")
        sf = self.shift_defect_factor(now)
        if sf > 1.05:
            out["shift"] = sf
            out["flags"].append("shift_change")
        if st.env_sensitive and self.m["paint_environment"]["enabled"]:
            pe = self.m["paint_environment"]
            t_excess = max(0.0, self.ambient_temp(now) - pe["temp_threshold_c"])
            h_excess = max(0.0, self.humidity(now) - pe["humidity_threshold"])
            env_f = 1.0 + pe["temp_sensitivity"] * t_excess + pe["humidity_sensitivity"] * h_excess
            if env_f > 1.05:
                out["env"] = env_f
                out["flags"].append("environment")
        return out
