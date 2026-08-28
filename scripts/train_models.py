#!/usr/bin/env python3
"""Train/evaluate models + refresh analytics (CLI equivalent of POST /ml/refresh).

  python scripts/train_models.py [--db sqlite:///data/generated/twinline.db]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.session import init_db, make_engine  # noqa: E402
from app.ml import anomaly as anomaly_service  # noqa: E402
from app.ml import defect_model  # noqa: E402
from app.models import ProductionLine  # noqa: E402
from app.services import data_quality as dq_service  # noqa: E402
from app.services import recommendations as rec_service  # noqa: E402


def _resolve_url(arg: str | None) -> str | None:
    """Accept a sqlite file path OR a full SQLAlchemy URL (mirrors generate_data.py)."""
    if arg is None:
        return None
    return arg if "://" in arg else f"sqlite:///{Path(arg).resolve()}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="sqlite path or full SQLAlchemy URL")
    args = ap.parse_args()

    url = _resolve_url(args.db)
    engine = init_db(url) if url else make_engine()
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = sf()
    line = db.query(ProductionLine).first()
    if not line:
        print("no production line found — run scripts/generate_data.py first")
        sys.exit(1)

    # anomaly pass FIRST: event anomaly scores feed defect-model features
    result = {
        "anomalies": anomaly_service.detect_anomalies(db, line.id),
        "defect_model": defect_model.train_defect_model(db, line.id),
    }
    if "error" not in result["defect_model"]:
        result["scoring"] = defect_model.score_vehicles(db, line.id)
    result["data_quality_rows"] = len(dq_service.compute_station_data_quality(db, line.id, persist=True))
    result["recommendations"] = rec_service.generate_recommendations(db, line.id)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
