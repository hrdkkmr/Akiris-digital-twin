#!/usr/bin/env python3
"""Export a small checked-in sample of the generated twin for reviewers.

Writes data/sample/twin_excerpt.json — the first N vehicles with their full
genealogy (events, sensor aggregates, inspections, defects) plus line
topology. Small enough to read; enough to verify the data contract and to
bootstrap a demo database without re-running generation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.session import make_engine  # noqa: E402
from app.models import (Defect, Inspection, Sensor, SensorReading, Station,  # noqa: E402
                        Vehicle, VehicleEvent)

N_VEHICLES = 5
OUT = Path(__file__).resolve().parents[1] / "data" / "sample"


def rows(query) -> list[dict]:
    return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in query]


def main() -> None:
    db = sessionmaker(bind=make_engine())()
    vehs = db.query(Vehicle).order_by(Vehicle.id).limit(N_VEHICLES).all()
    ids = [v.id for v in vehs]
    excerpt = {
        "meta": {"vehicles": len(ids),
                 "note": "excerpt of data/generated/twinline.db — full genealogy for "
                         "the first N vehicles; schema mirrors backend/app/models"},
        "stations": rows(db.query(Station).order_by(Station.seq)),
        "sensors": rows(db.query(Sensor)),
        "vehicles": rows(vehs),
        "vehicle_events": rows(db.query(VehicleEvent)
                               .filter(VehicleEvent.vehicle_id.in_(ids))
                               .order_by(VehicleEvent.entered_at)),
        "sensor_readings": rows(db.query(SensorReading)
                                .filter(SensorReading.vehicle_id.in_(ids))),
        "inspections": rows(db.query(Inspection)
                            .filter(Inspection.vehicle_id.in_(ids))),
        "defects": rows(db.query(Defect).filter(Defect.vehicle_id.in_(ids))),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "twin_excerpt.json").write_text(json.dumps(excerpt, indent=1, default=str))
    print(f"wrote {OUT/'twin_excerpt.json'} "
          f"({sum(len(v) for k, v in excerpt.items() if k != 'meta')+1} objects)")


if __name__ == "__main__":
    main()
