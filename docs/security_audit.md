# Dependency security audit

**Tool:** pip-audit 2.x (PyPA advisory DB) · **Scope:** `backend/requirements.txt`
closure (44 packages) · **Date:** 2026-08-28 · **result: ✅ 0 known
vulnerabilities**

Re-run anytime:

```bash
pip install pip-audit
pip-audit -r backend/requirements.txt --format=json -o audit.json
```

The CI `security-audit` job runs this on every push and fails on newly
disclosed advisories (`--ignore-vuln` entries must be added deliberately,
with justification in a comment — none needed today).

## Hardening measures in place (v0.3.0)

| control | where | config |
|---|---|---|
| API-key guard on mutating ops endpoints | `api/deps.py::require_api_key` | `TWIN_API_KEY` |
| Per-IP token-bucket rate limit (mutations only; GET polling unaffected) | `core/rate_limit.py` | `TWIN_RATE_LIMIT_PER_MIN` (default 120; ≤0 disables) |
| Security headers (nosniff, DENY framing, no-referrer, permissions-policy, HSTS, CSP tuned for Swagger CDN) | `main.py::_SECURITY_HEADERS` | — |
| Env-driven CORS allowlist | `main.py` | `TWIN_CORS_ORIGINS` |
| Request-id + structured access logs (PII-free: method/path/status/latency only) | `main.py` | `TWIN_LOG_LEVEL` |
| Liveness `/health` + readiness `/ready` (probes must not share fate) | `main.py` | — |
| Reproducible installs | `backend/requirements.lock` (pip-compile), `frontend/package-lock.json` | — |
| Schema migrations with verified downgrade path | `backend/alembic/` | `alembic upgrade head` |

**Not built here (needs real infra):** OIDC/SSO + RBAC, Redis-backed
distributed rate limiting (the middleware interface is the swap point),
secret manager (Vault/KMS), TLS termination at the platform layer, WAF.
