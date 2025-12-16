# Security Assertions

This document lists the exact security requirements and behaviors that ORIGIN guarantees in production.

## Signing Algorithm

**Assertion**: ORIGIN uses **PS256** (RSA-PSS SHA-256) for all certificate signing.

- All signers (`DevLocalSigner`, `KmsSigner`) use RSA-PSS SHA-256
- JWKS endpoint (`/v1/keys/jwks.json`) advertises `alg: "PS256"` in all public keys
- Certificate `alg` field matches JWKS `alg` field (dynamically set from signer)
- Certificate model default is `PS256`
- **Do not use RS256 (PKCS1)** - ORIGIN does not use this algorithm

**Verification**: Certificate signatures must be verified using RSA-PSS SHA-256 with the public key from JWKS.

## Webhook Signing Rule

**Assertion**: Webhooks are signed using **raw body bytes**, not re-serialized JSON.

**Exact signing format**:
```
signature = HMAC-SHA256(
    secret,
    timestamp_bytes + b"." + raw_body_bytes
)
```

Where:
- `timestamp_bytes` = Unix timestamp as UTF-8 encoded bytes
- `raw_body_bytes` = Exact bytes from HTTP request body (not re-serialized)
- Signature header: `X-Origin-Signature: sha256=<hex>`
- Timestamp header: `X-Origin-Timestamp: <unix_timestamp>`

**Critical Requirements**:
- ORIGIN signs the exact bytes it sends in the HTTP body
- Receivers MUST capture raw body bytes before JSON parsing
- Receivers MUST NOT use `JSON.stringify(req.body)` or `json.dumps(payload)` for verification
- Python SDK `verify_webhook()` requires `raw_body: bytes` parameter
- Express.js example includes raw body capture middleware

**Verification**: Webhook signatures must be verified using the exact raw body bytes received, not re-serialized JSON.

## IP Allowlist Fail Mode

**Assertion**: IP allowlist behavior depends on environment and explicit configuration.

**Logic**:
```python
if IP_ALLOWLIST_FAIL_OPEN is explicitly set:
    use that value
else:
    if environment in ("development", "test", "dev"):
        fail_open = True  # Allow with warning
    else:
        fail_open = False  # Deny (fail-closed)
```

**Behavior**:
- **Development/Test**: Invalid JSON or parsing errors → allow access with warning log
- **Production/Staging**: Invalid JSON or parsing errors → deny access with warning log + metric increment
- Valid CIDR ranges and exact IPs are always checked correctly
- Metrics tracked: `ip_allowlist_parse_error`, `ip_allowlist_error`

## Required Production Environment Variables

**Assertion**: The following environment variables are REQUIRED in non-dev environments (production, staging):

1. **MinIO/S3 Credentials** (no defaults):
   - `MINIO_ACCESS_KEY` - Required, no default
   - `MINIO_SECRET_KEY` - Required, no default

2. **Signing Key Provider**:
   - `SIGNING_KEY_PROVIDER=aws_kms` - Required (local forbidden)
   - `SIGNING_KEY_ID` - Required (KMS key ID or ARN)
   - `AWS_REGION` - Required
   - `AWS_ACCESS_KEY_ID` - Required (or use IAM role)
   - `AWS_SECRET_ACCESS_KEY` - Required (or use IAM role)

3. **Webhook Encryption Provider**:
   - `WEBHOOK_ENCRYPTION_PROVIDER=aws_kms` - Required (local forbidden)
   - `WEBHOOK_ENCRYPTION_KEY_ID` - Required (KMS key ID)
   - `AWS_REGION` - Required

4. **Environment**:
   - `ENVIRONMENT=production` or `ENVIRONMENT=staging`

**Validation**: Application startup calls `settings.validate_production_settings()` which fails fast if:
- `MINIO_ACCESS_KEY` or `MINIO_SECRET_KEY` are missing in non-dev
- `SIGNING_KEY_PROVIDER=local` in non-dev
- `WEBHOOK_ENCRYPTION_PROVIDER=local` in non-dev

**Development**: Default credentials and local providers are allowed when `ENVIRONMENT=development`.

## Scope Enforcement

**Assertion**: All API endpoints enforce scope requirements via `ScopeMiddleware`.

**Required Scopes**:
- `POST /v1/ingest` → `ingest:write`
- `POST /v1/evidence-packs` → `evidence:write`
- `GET /v1/evidence-packs/*` → `evidence:read`
- `GET /v1/certificates/*` → `certificates:read`
- `GET /v1/keys/*` → `certificates:read`
- `POST /v1/webhooks` → `webhooks:write`
- `GET /v1/webhooks/*` → `webhooks:read`
- `/admin/**` (all methods) → `admin`

**Enforcement**:
- `ScopeMiddleware` is added to middleware chain in `main.py`
- Cannot be skipped by route ordering (runs after `AuthMiddleware`)
- Missing scope → 403 Forbidden response
- Public endpoints (`/health`, `/ready`, `/metrics`, `/docs`) skip scope checks

## Readiness Checks

**Assertion**: `/ready` endpoint performs real dependency checks.

**Checks Performed**:
1. **Database**: Connects and runs `SELECT 1`
2. **Migrations**: Verifies Alembic migrations are at head (current_rev == head_rev)
3. **Redis**: Pings Redis server
4. **Object Storage**: Verifies MinIO/S3 connectivity and bucket existence
5. **KMS**: Validates KMS access if `aws_kms` provider is configured (non-dev only)

**Response**:
- All checks pass → 200 OK with `{"status": "ready", "checks": {...}}`
- Any check fails → 503 Service Unavailable with `{"status": "not_ready", "checks": {...}}`

**No TODOs**: All checks are implemented, no placeholder logic.

## Settings Consolidation

**Assertion**: There is exactly one canonical Settings class per service.

**API Service**:
- `apps/api/origin_api/settings.py` - Single canonical Settings class
- All API code imports from `origin_api.settings`

**Worker Service**:
- `apps/worker/origin_worker/settings.py` - Single canonical Settings class
- All worker code imports from `origin_worker.settings`
- Consistent fields with API settings (no default MinIO credentials)

**No Duplicates**: No legacy or duplicate Settings classes exist.

## Certificate Algorithm Matching

**Assertion**: Certificate `alg` field always matches the actual signing algorithm.

- Certificate generation uses `signer.get_public_jwk().get("alg")` to set `alg` field
- JWKS advertises the same algorithm
- Verification must use the algorithm specified in `certificate.alg`
- Default is `PS256` if algorithm cannot be determined

## Webhook Raw Body Requirement

**Assertion**: Webhook verification requires raw body bytes, no fallback to re-serialized JSON.

- Python SDK `verify_webhook()` signature: `verify_webhook(headers, raw_body: bytes, secret)`
- Express.js example refuses to verify if `req.rawBody` is not available
- All tests use raw bytes, not re-serialized JSON
- ORIGIN's webhook sender uses `content=payload_bytes` (not `json=payload`)

## CI Test Requirements

The following CI tests must pass:

1. **No Default Credentials**: Fail if any Settings class contains `minioadmin` or `minioadmin123`
2. **Readiness Real Checks**: Fail if `/ready` contains "TODO" or doesn't perform real checks
3. **Webhook Raw Bytes**: Fail if webhook signing tests use `json.dumps()` or `JSON.stringify()` for verification
4. **Scope Enforcement**: Fail if endpoints don't reject requests with missing scopes

## References

- Certificate signing: `apps/api/origin_api/ledger/signer.py`
- Webhook signing: `apps/api/origin_api/webhooks/service.py`
- Webhook verification: `packages/sdk-python/origin_sdk/webhook.py`
- IP allowlist: `apps/api/origin_api/middleware/auth.py`
- Scope enforcement: `apps/api/origin_api/middleware/scopes.py`
- Settings: `apps/api/origin_api/settings.py`, `apps/worker/origin_worker/settings.py`
- Readiness: `apps/api/origin_api/main.py` (readiness_check endpoint)

