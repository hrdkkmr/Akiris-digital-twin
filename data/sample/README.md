# data/sample — checked-in excerpt

`twin_excerpt.json` is a small, human-readable slice of the generated twin:

- full line topology (42 stations, sensors with units/status)
- the first **5 vehicles** with their **complete genealogy**: every station
  event (in/out times, cycle deviation, checklist, anomaly score), every
  per-cycle sensor aggregate, every inspection row, every defect

Regenerate from any existing database:

```bash
python scripts/export_sample.py    # reads the configured TWIN_DATABASE_URL
```

Use cases: schema reference for reviewers/judges, quick sanity checks without
DB tooling, template for writing external CSV/record adapters (see
`backend/app/ingestion/csv_source.py` for the normalized ingestion shape).
