"""Locust load test for the TwinLine read path.

  locust -f load/locustfile.py --headless -u 60 -r 10 -t 60s \
         --host http://localhost:8000 --only-summary

Read-heavy by design: a shadow-mode twin is polled (dashboards every 15s
per persona) and rarely mutated. Mutation endpoints are excluded from the
mix (they are rate-limited by design — see core/rate_limit.py).
"""
from __future__ import annotations

import random

from locust import HttpUser, between, task


class TwinUser(HttpUser):
    wait_time = between(0.05, 0.3)

    def on_start(self) -> None:
        r = self.client.get("/vehicles?limit=200")
        self._vehicle_ids = [v["id"] for v in r.json().get("vehicles", [])] or [1]

    @task(3)
    def stations_board(self):
        self.client.get("/stations")

    @task(3)
    def bottleneck_summary(self):
        self.client.get("/bottlenecks")

    @task(2)
    def production_summary(self):
        self.client.get("/production/summary")

    @task(2)
    def trends(self):
        self.client.get("/production/trends?bucket_vehicles=50")

    @task(2)
    def at_risk_board(self):
        self.client.get("/defect-risks?threshold=0.4&limit=40")

    @task(1)
    def vehicle_journey(self):
        vid = random.choice(self._vehicle_ids)
        self.client.get(f"/vehicles/{vid}/journey")

    @task(1)
    def health(self):
        self.client.get("/health")
