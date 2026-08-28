"""Production + business endpoints."""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..models import Vehicle
from ..services.business import production_summary, roi_report
from .deps import get_db, get_line_or_404

router = APIRouter(tags=["production"])


@router.get("/production/summary")
def summary(line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return production_summary(db, line.id)


@router.get("/production/roi")
def roi(line_id: int | None = None, db: Session = Depends(get_db)):
    line = get_line_or_404(db, line_id)
    return roi_report(db, line.id)


@router.get("/production/trends")
def trends(bucket_vehicles: int = Query(50, ge=10, le=500),
           line_id: int | None = None, db: Session = Depends(get_db)):
    """Chronological production trend buckets — computed from twin data only.

    Buckets group consecutive completed vehicles (default 50), reporting per
    bucket: FPY, throughput, scrap count, average lead time. Used by the
    Manager view's trend charts; suitable input for SPC/charting tools.
    """
    line = get_line_or_404(db, line_id)
    df = pd.read_sql(
        db.query(Vehicle.started_at, Vehicle.completed_at, Vehicle.status)
        .filter(Vehicle.line_id == line.id, Vehicle.completed_at.isnot(None))
        .order_by(Vehicle.completed_at).statement, db.bind)
    if df.empty:
        return {"bucket_size": bucket_vehicles, "buckets": []}
    df["bucket"] = [i // bucket_vehicles for i in range(len(df))]
    out = []
    for b, grp in df.groupby("bucket"):
        span = max(float(grp.completed_at.max() - grp.completed_at.min()), 1.0)
        n = len(grp)
        scrapped = int((grp.status == "scrapped").sum())
        out.append({
            "bucket": int(b),
            "t_start": round(float(grp.completed_at.min()), 1),
            "t_end": round(float(grp.completed_at.max()), 1),
            "vehicles": n,
            "scrapped": scrapped,
            "fpy": round((n - scrapped) / n, 4),
            "throughput_per_hour": round(n / (span / 3600.0), 1),
            "avg_lead_time_s": round(float((grp.completed_at - grp.started_at).mean()), 1),
        })
    return {"bucket_size": bucket_vehicles, "buckets": out}
