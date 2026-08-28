"""Part model with full process genealogy (digital thread).

Every station interaction is recorded; accumulated risk via `contributions` gives
us GROUND-TRUTH root-cause labels for evaluating the causal-trace engine later.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Part:
    id: str
    batch: str
    variant: str
    variant_factor: float
    born: float
    fail_threshold: float = 1.0   # latent defect draw ~U(0,1): scrapped when 1-quality exceeds it
    quality: float = 1.0
    scrapped: bool = False
    genealogy: list[dict] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def add_risk(self, station_id: str, risk: float, flags: list[str]) -> None:
        self.contributions[station_id] += risk
        self.genealogy.append({"station": station_id, "risk": round(risk, 6),
                               "flags": list(flags)})

    def top_causes(self, k: int = 3) -> list[tuple[str, float]]:
        return sorted(self.contributions.items(), key=lambda kv: -kv[1])[:k]
