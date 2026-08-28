#!/usr/bin/env bash
# Container entrypoint: seed (if empty) -> train (best effort) -> serve API.
set -u

echo "[bootstrap] TwinLine API starting…"
echo "[bootstrap] DATABASE_URL=${TWIN_DATABASE_URL:-<default sqlite>}"

python scripts/generate_data.py --scenario "${TWIN_SCENARIO:-mixed}" \
        --vehicles "${TWIN_SEED_VEHICLES:-1500}" --seed "${TWIN_DEFAULT_SEED:-42}" \
  || echo "[bootstrap] dataset already present — skipping generation"

python scripts/train_models.py \
  || echo "[bootstrap] model training skipped (dataset may be too small)"

cd backend && exec uvicorn app.main:app --host 0.0.0.0 --port 8000
