"""Per-IP token-bucket rate limiting for MUTATING methods (POST/PUT/DELETE).

Transparent token bucket, in-process. Limit is read from env per request
(TWIN_RATE_LIMIT_PER_MIN, default 120) so tests and ops can tune without
restarts; <= 0 disables. GET/HEAD/OPTIONS always pass (dashboard polling).

Production note: an in-process bucket is per-worker — a multi-worker or
multi-instance deployment should back this by Redis (same interface), which
is the documented swap point in README §20.
"""
from __future__ import annotations

import os
import time

from fastapi.responses import JSONResponse

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_DEFAULT_PER_MIN = 120


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self._buckets: dict[str, list[float]] = {}  # ip -> [tokens, updated]

    def _limit(self) -> int:  # per-request: env wins (testable/tunable)
        try:
            return int(os.environ.get("TWIN_RATE_LIMIT_PER_MIN", _DEFAULT_PER_MIN))
        except ValueError:
            return _DEFAULT_PER_MIN

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _MUTATING:
            await self.app(scope, receive, send)
            return
        limit = self._limit()
        if limit > 0:
            client = scope.get("client") or ("?", 0)
            key = client[0]
            now = time.monotonic()
            tokens, updated = self._buckets.get(key, [float(limit), now])
            tokens = min(float(limit), tokens + (now - updated) * (limit / 60.0))
            if tokens < 1.0:
                wait = int((1.0 - tokens) / (limit / 60.0)) + 1
                body = {"detail": f"rate limit exceeded — max {limit} mutating "
                                  f"requests/min/client", "retry_after_s": wait}
                response = JSONResponse(body, status_code=429,
                                        headers={"Retry-After": str(wait)})
                await response(scope, receive, send)
                return
            self._buckets[key] = [tokens - 1.0, now]
        await self.app(scope, receive, send)
