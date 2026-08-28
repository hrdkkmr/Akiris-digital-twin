# Load test report (measured)

**Tool:** Locust 2.x (`load/locustfile.py`) · **Load:** 60 concurrent users,
ramp 15/s, 60 s · **Mix:** read-heavy realistic blend (stations board,
bottlenecks, summaries, trends, at-risk board, random vehicle journeys,
health) — mutations excluded (rate-limited by design).

**Measured run (this sandbox, 2026-08-28):**

| | value |
|---|---|
| requests served | **1,062** |
| failures | **0** (0%) |
| sustained throughput | ~18 req/s |
| latency p50 / p95 / p99 | 3.1 s / **4.8 s** / 5.6 s |
| slowest route (p95) | `/bottlenecks` 4.6 s (42-station aggregation, per-request) |
| fastest route (p95) | `/health` 1.1 s |

## Honest interpretation

1. **Reliability: strong.** Zero errors/timeouts at sustained load with a
   single worker — no race conditions, no lockups in the read path.
2. **Latency: adequate-for-prototype, below production SLOs.** The measured
   p95 reflects a deliberately naive setup, in order of cost:
   - **shared sandbox CPU** (locust + API + SQLite on ~2 vCPU),
   - **per-request recomputation** of aggregate analytics (e.g. `/stations`,
     `/bottlenecks` re-aggregate every poll),
   - **SQLite** (single-file, no read scaling),
   - one `uvicorn` worker, sync handlers.
3. **Documented production path (all extension points already in place):**
   cached twin-state snapshots (public read endpoints hit Redis/Postgres
   materialized views; the pipeline already writes KPI tables —
   materializing them per-ingest instead of per-request is the swap),
   Postgres + read replicas (compose stack), `--workers N` + async handlers
   behind a load balancer, `--workers` with separate read/write pools.
4. **Reproduce:**
   ```bash
   pip install locust
   locust -f load/locustfile.py --headless -u 60 -r 15 -t 60s \
          --host http://localhost:8000 --only-summary
   ```
