# Coverage-scenario experiment (measured, not asserted)

Same generator, same pipeline, same models — only the sensor-coverage world
changes (`configs/scenarios/*.yaml`). All numbers below were produced by the
scripts in §19 of the README, not edited by hand. Databases:
`data/generated/twinline_{full,twinline,twinline_brownfield}.db`.

| metric | full (~100% instrumented) | mixed (~70–85%) | brownfield (~40–60%) |
|---|---|---|---|
| vehicles generated | 1,636 | 2,717 | 1,624 |
| scrap rate | 3.97% | 3.79% | 5.17% |
| sensor readings stored | 224,624 | 187,875 | **18,971** |
| distinct sensors profiled by anomaly detector | full (+mid) | full, mid | mid only |
| anomaly alerts written | 764 | 694 | 353 |
| mean sensor coverage (DQ) | 1.00 | 0.48 | **0.08** |
| mean analytics confidence (DQ) | **0.99** | 0.67 | **0.42** |
| defect model ROC-AUC | 0.572 | 0.598 | 0.616 |
| defect model PR-AUC | 0.013 | 0.023 | 0.028 |
| flagged recall @ tuned threshold | 3.97% base | 0.80 | 0.00 |

## What the numbers actually say

1. **Analytics confidence collapses with coverage: 0.99 → 0.67 → 0.42.**
   This is the headline and the pitch for the observability feature: in a
   brownfield plant the twin must *know and SHOW* that its station-level
   judgments are weak, or operators stop trusting it. The composite covers
   coverage + completeness + freshness − anomaly density, per station.
2. **ROC-AUC does NOT fall monotonically with coverage (0.572/0.598/0.616).**
   With ~40–85 positives per split, these differences are inside sampling
   noise — we report them honestly rather than claim a trend. What coverage
   *does* reliably change is: number of usable feature channels (which
   features can even be computed), prediction *confidence/data_completeness*,
   and which stations the anomaly detector can profile (brownfield: only the
   `mid`-instrumented stations have enough signal; sparse/manual are skipped
   by design and marked in data_quality).
3. **Brownfield failure capture is structurally limited.** With a tuned
   threshold above all test positives, recall collapses to 0 — the firmware
   answer is not "flag everything" (that is FPR-washing) but to instrument
   the gap: the **value-of-information sensor advisor** extension point exists
   precisely to recommend which manual/sparse stations justify retrofit spend.
4. **Recommendation volume scales inversely with coverage** (more
   data-gap/confidence notices in brownfield), which is the intended
   behavior of an advisory engine that knows its observability limits.

## Reproduce

```bash
for s in full brownfield; do
  python scripts/generate_data.py  --fresh --scenario $s --vehicles 1200 \
      --db data/generated/twinline_$s.db
  python scripts/train_models.py   --db   data/generated/twinline_$s.db
done
# mixed world is the default: scripts/generate_data.py --fresh --vehicles 2000
```
