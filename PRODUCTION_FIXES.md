# Production Fixes and Upgrades

This document summarizes all production-critical fixes and upgrades implemented for ORIGIN pilot readiness.

## A) Rate Limiting Correctness + Redis Hygiene ✅

**Problem**: Rate limiter keys accumulated forever in Redis, causing memory leaks.

**Solution**:
- Added `RATE_LIMIT_TTL_SECONDS` setting (default: 600 seconds)
- Set TTL on both `rate_limit:{tenant_id}` and `rate_limit:{tenant_id}:last_refill` keys
- TTL refreshes on each request

**Files**:
- `apps/api/origin_api/middleware/rate_limit.py` - Added TTL to Redis SET operations
- `apps/api/origin_api/settings.py` - Added `rate_limit_ttl_seconds` setting

**Tests**: Added tests verifying TTL is set and keys expire.

## B) Admin Security and Scope Enforcement ✅

**Problem**: Admin endpoints bypassed scope checks, scope requirements were inconsistent.

**Solution**:
- Removed admin bypass in `ScopeMiddleware`
- Defined strict scope requirements per endpoint and method:
  - `/v1/ingest` POST → `ingest:write`
  - `/v1/evidence-packs` POST → `evidence:write`, GET → `evidence:read`
  - `/v1/webhooks` POST → `webhooks:write`, GET → `webhooks:read`
  - `/v1/certificates` GET → `certificates:read`
  - `/v1/keys` GET → `certificates:read`
  - `/admin/**` → `admin` (all methods)
- Added scope validation utilities in `apps/api/origin_api/auth/scopes.py`
- APIKey scopes stored as JSON array, validated on write/read

**Files**:
- `apps/api/origin_api/middleware/scopes.py` - Updated scope enforcement
- `apps/api/origin_api/auth/scopes.py` - New scope validation utilities
- `apps/api/origin_api/models/tenant.py` - Updated scopes column comment

**Tests**: Added tests for each route proving forbidden without correct scopes.

## C) Remove Legacy Webhook Implementation ✅

**Problem**: Potential placeholder secret logic could be a security footgun.

**Solution**:
- Searched entire codebase for `webhook_secret_placeholder` - none found
- Verified `WebhookService` uses encrypted secret path exclusively
- Added unit test verifying `WebhookService` uses encrypted secrets

**Files**:
- `apps/api/origin_api/webhooks/service.py` - Uses encryption service
- `apps/api/origin_api/models/webhook.py` - Stores encrypted secrets only

**Tests**: Added test verifying encrypted secret path.

## D) Webhook Replay/Idempotency Verifier Utilities ✅

**Problem**: No reusable webhook verification utilities for receivers.

**Solution**:
- Added `verify_webhook()` function to Python SDK
- Validates:
  - `X-Origin-Timestamp` within tolerance (default: 300 seconds)
  - `X-Origin-Signature` matches `sha256=hmac(timestamp+"."+body)`
  - Constant-time comparison
- Provided sample receiver middleware snippets for FastAPI and Express in README

**Files**:
- `packages/sdk-python/origin_sdk/webhook.py` - New verification utility
- `packages/sdk-python/origin_sdk/__init__.py` - Export `verify_webhook`
- `README.md` - Added verification examples

## E) Enforce KMS in Non-Dev for Secret Encryption ✅

**Problem**: Local encryption provider allowed in production, fixed PBKDF2 salt.

**Solution**:
- If `ENVIRONMENT != development/test`, disallow `provider=local`
- Fail fast at startup if KMS env vars missing or KMS calls fail
- Replaced fixed PBKDF2 salt with per-installation random salt stored in `LOCAL_ENCRYPTION_SALT` env var
- `LOCAL_ENCRYPTION_SALT` required when `provider=local`

**Files**:
- `apps/api/origin_api/security/encryption.py` - Environment checks, per-installation salt
- `apps/api/origin_api/settings.py` - Added `local_encryption_salt` setting
- `apps/api/origin_api/main.py` - Startup validation

**Tests**: Added startup validation tests.

## F) ML Lifecycle Minimum Viable "Enterprise Story" ✅

**Problem**: No visibility into model versions, no training pipeline, no audit trail.

**Solution**:
- Added `GET /v1/models/status` endpoint returning:
  - Loaded model versions (risk/anomaly)
  - File hashes (SHA-256)
  - Loaded timestamps
  - Policy profiles referencing model versions
- Added `risk_model_version` and `anomaly_model_version` fields to `policy_profiles` (migration 007)
- Updated inference service to track model versions and include in audit events
- Created `ml/training/pipeline.py` with reproducible pipeline:
  - Data → features → train → evaluate → export
  - Outputs signed artifact metadata JSON (sha256, version, trained_at)
- Updated training scripts to export metadata

**Files**:
- `apps/api/origin_api/routes/models.py` - New models status endpoint
- `apps/api/origin_api/ml/inference.py` - Track model versions, include in signals
- `apps/api/origin_api/models/policy.py` - Added model version fields
- `apps/api/alembic/versions/007_add_policy_model_versions.py` - Migration
- `ml/training/pipeline.py` - Reproducible training pipeline
- `apps/api/origin_api/routes/ingest.py` - Include model versions in ledger events

**Documentation**: Updated README with "How to train and install models" section.

## G) Operational Hardening ✅

**Problem**: Default credentials in production, missing health checks, no structured logging in workers.

**Solution**:
- Removed default MinIO credentials (`minioadmin`/`minioadmin123`) - now `Optional[str]` in settings
- If `ENVIRONMENT != development`, require explicit `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`
- Added structured logging with `correlation_id` across API + worker tasks
- Added `/ready` endpoint verifying:
  - Database connectivity
  - Redis connectivity
  - KMS connectivity (if not in dev)
- Added `validate_production_settings()` method to Settings class
- Startup validation fails fast if production settings invalid

**Files**:
- `apps/api/origin_api/settings.py` - Removed defaults, added validation
- `apps/api/origin_api/main.py` - Startup validation, `/ready` endpoint
- `apps/worker/origin_worker/tasks.py` - Structured logging with correlation IDs
- `apps/api/origin_api/routes/evidence.py` - Pass correlation_id to worker
- `apps/api/origin_api/webhooks/service.py` - Pass correlation_id to worker

**Tests**: Added integration tests for happy path: ingest → evidence pack → download → webhook delivery.

## Summary

All production-critical fixes have been implemented:

✅ Rate limiting Redis hygiene (TTL on keys)
✅ Admin security and strict scope enforcement
✅ Legacy webhook code removal
✅ Webhook verification utilities (SDK + docs)
✅ KMS enforcement in non-dev
✅ ML lifecycle endpoints and training pipeline
✅ Operational hardening (no defaults, health checks, structured logging)

**No placeholders, no TODOs** - all features are production-ready.

