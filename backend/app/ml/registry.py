"""Model registry — artifacts on disk, versions + metrics in DB (model_versions)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import joblib
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import ModelVersion


def save_model(db: Session, model: object, name: str, algo: str,
               metrics: dict, notes: str = "") -> ModelVersion:
    model_dir = Path(get_settings().model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    prev = (db.query(ModelVersion).filter_by(name=name)
            .order_by(ModelVersion.id.desc()).first())
    version = f"1.{(int(prev.version.split('.')[1]) + 1) if prev else 0}"
    path = model_dir / f"{name}_v{version}_{ts}.joblib"
    joblib.dump(model, path)
    mv = ModelVersion(name=name, algo=algo, version=version, trained_at=ts and
                      float(datetime.now(timezone.utc).timestamp()),
                      metrics=metrics, artifact_path=str(path), notes=notes)
    db.add(mv)
    db.commit()
    return mv


def load_latest(db: Session, name: str):
    mv = (db.query(ModelVersion).filter_by(name=name)
          .order_by(ModelVersion.id.desc()).first())
    if not mv:
        return None, None
    return mv, joblib.load(mv.artifact_path)
