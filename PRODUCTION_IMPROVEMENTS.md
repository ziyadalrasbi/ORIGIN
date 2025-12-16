# Production Improvements Summary

This document summarizes the production-ready improvements implemented for ORIGIN.

## ✅ Completed Improvements

### 1. API Key Authentication - Scalable Prefix+Digest Lookup

**Changes:**
- Added `prefix` (first 8 chars) and `digest` (HMAC-SHA256) columns to `api_keys` table
- Replaced O(n) bcrypt loops with O(1) indexed prefix lookup
- Constant-time digest comparison using `hmac.compare_digest()`
- Legacy bcrypt fallback behind `LEGACY_APIKEY_FALLBACK` feature flag
- Added `last_used_at` tracking

**Files:**
- `apps/api/origin_api/models/tenant.py` - Updated APIKey model
- `apps/api/origin_api/auth/api_key.py` - New scalable lookup logic
- `apps/api/alembic/versions/001_add_api_key_prefix_digest.py` - Migration

**Usage:**
```python
# API keys are now stored with prefix and digest
# Lookup is O(1) with indexed prefix query
tenant = get_tenant_by_api_key(db, raw_api_key)
```

### 2. Audit Ledger - Deterministic Hash Chaining

**Changes:**
- Added `tenant_sequence` (monotonic per tenant) for deterministic ordering
- Added `event_timestamp` (fixed at creation time)
- Added `canonical_event_json` (exact object that was hashed)
- Hash computed only from `canonical_event_json` (not recomputed fields)
- Thread-safe sequence allocation using `SELECT FOR UPDATE`
- Chain verification checks sequence monotonicity and hash integrity

**Files:**
- `apps/api/origin_api/models/ledger.py` - Added TenantSequence and new fields
- `apps/api/origin_api/ledger/service.py` - Deterministic hashing logic
- `apps/api/alembic/versions/002_add_ledger_tenant_sequence.py` - Migration

**Verification:**
```python
is_valid, error = ledger_service.verify_chain(tenant_id)
# Returns (True, None) if chain is valid, (False, error_message) if tampered
```

### 3. Decision Certificates - KMS-Ready Signing (COMPLETE)

**Changes:**
- Fully implemented `KmsSigner` using boto3 with AWS KMS
- Supports `RSASSA_PSS_SHA_256` and `RSASSA_PKCS1_V1_5_SHA_256` signing algorithms
- Parses DER public keys from KMS into JWK format
- Configuration validation on startup (fails fast if KMS key missing/inaccessible)
- Key rotation support: multiple active keys, old certificates remain verifiable
- `DevLocalSigner` for local development with RSA keypair

**Files:**
- `apps/api/origin_api/ledger/signer.py` - Complete KMS implementation
- `apps/api/origin_api/routes/keys.py` - JWKS endpoint
- `apps/api/origin_api/main.py` - Startup validation

**Environment Variables:**
```bash
SIGNING_KEY_PROVIDER=aws_kms  # or "local" for dev
SIGNING_KEY_ID=arn:aws:kms:us-east-1:123456789012:key/abc-123
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...  # Optional if using IAM role
AWS_SECRET_ACCESS_KEY=...  # Optional if using IAM role
```

**Usage:**
```python
from origin_api.ledger.signer import get_signer

signer = get_signer()  # Auto-selects based on SIGNING_KEY_PROVIDER
signature = signer.sign(data_bytes)
jwk = signer.get_public_jwk()  # For JWKS endpoint
```

**Tests:**
- `apps/api/tests/test_kms_signer.py` - Mocked KMS client tests

**Changes:**
- Abstract `Signer` interface with `sign()` and `get_public_jwk()` methods
- `DevLocalSigner` - Loads RSA keypair from file for local dev
- `KmsSigner` - Placeholder for AWS KMS integration
- Added `key_id`, `alg`, `signature_encoding` fields to certificates
- JWKS endpoint: `GET /v1/keys/jwks.json`
- Certificate endpoint: `GET /v1/certificates/{certificate_id}`

**Files:**
- `apps/api/origin_api/ledger/signer.py` - Signer abstraction
- `apps/api/origin_api/ledger/certificate.py` - Updated to use signer
- `apps/api/origin_api/routes/keys.py` - JWKS and certificate endpoints
- `apps/api/alembic/versions/003_add_certificate_key_fields.py` - Migration

**Key Rotation:**
- Multiple active public keys supported
- New certificates use newest key
- Old certificates remain verifiable via JWKS

### 4. Ingest - Real Feature Computation

**Changes:**
- Removed placeholders for `account_age_days` and `upload_velocity`
- Created `FeatureService` to compute features from database:
  - `account_age_days` = now - accounts.created_at
  - `upload_velocity_24h` = count uploads last 24h by account_id
  - `device_velocity_24h` = count uploads last 24h by device entity
  - `prior_quarantine_count` / `prior_reject_count` for account and PVID
- Store computed features in `decision_inputs_json` for explainability
- Optimized queries using aggregates to minimize DB round trips

**Files:**
- `apps/api/origin_api/services/features.py` - Feature computation service
- `apps/api/origin_api/routes/ingest.py` - Integrated real features
- `apps/api/origin_api/models/upload.py` - Added `decision_inputs_json`
- `apps/api/alembic/versions/004_add_upload_decision_inputs.py` - Migration

### 5. Evidence Packs - Async + Object Storage

**Changes:**
- S3/MinIO storage client with presigned URLs
- Async generation via Celery tasks
- Storage metadata: `storage_keys`, `artifact_hashes`, `artifact_sizes`
- Short-lived signed URLs (configurable TTL)
- Fallback to local filesystem in dev mode

**Files:**
- `apps/api/origin_api/storage/s3.py` - S3/MinIO client
- `apps/worker/origin_worker/tasks.py` - Async evidence generation task
- `apps/api/origin_api/routes/evidence.py` - Updated to use async + storage
- `apps/api/origin_api/models/evidence.py` - Added storage fields
- `apps/api/alembic/versions/005_add_evidence_storage_fields.py` - Migration

**Flow:**
1. Client requests evidence pack → returns `status: "pending"`
2. Celery task generates artifacts → stores in S3/MinIO
3. Client polls or uses download endpoint with signed URLs

### 6. Webhooks - Durable Background Delivery

**Changes:**
- Moved webhook delivery to Celery background tasks
- HMAC-SHA256 signing with `X-Origin-Signature` header
- Includes `correlation_id` and `event_id` in headers
- Automatic retries with exponential backoff
- Dead-letter queue for failed deliveries
- Delivery history endpoint: `GET /v1/webhooks/{webhook_id}/deliveries`

**Files:**
- `apps/worker/origin_worker/tasks.py` - `deliver_webhook` task
- `apps/api/origin_api/webhooks/service.py` - Updated delivery logic
- `apps/api/origin_api/routes/webhooks.py` - Added delivery history endpoint

**Verification:**
```python
# Webhook signature verification
signature = request.headers.get("X-Origin-Signature")
expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
hmac.compare_digest(f"sha256={expected}", signature)
```

### 7. Tenant Isolation & Security Hardening

**Changes:**
- IP allowlist per tenant (CIDR notation support)
- Structured logging with correlation_id, tenant_id, ingestion_id, certificate_id
- All queries enforce tenant_id scoping
- Replaced `print()` statements with structured logging

**Files:**
- `apps/api/origin_api/middleware/auth.py` - IP allowlist enforcement
- `apps/api/origin_api/models/tenant.py` - Added `ip_allowlist` field
- All route handlers - Added structured logging

### 8. Performance - Indexes & Migrations

**Indexes Added:**
- `api_keys`: prefix, digest
- `uploads`: (tenant_id, external_id) unique, pvid, (account_id, received_at)
- `ledger_events`: (tenant_id, tenant_sequence) unique
- `risk_signals`: (tenant_id, upload_id)
- `evidence_packs`: status

**Migrations:**
- 001: API key prefix/digest
- 002: Ledger tenant_sequence
- 003: Certificate key fields
- 004: Upload decision_inputs + unique constraint
- 005: Evidence storage fields

## 🔄 Migration Path

### For Existing Deployments

1. **API Keys:**
   - Run migration 001
   - Existing keys will need to be re-created with prefix/digest
   - Legacy bcrypt keys will work if `LEGACY_APIKEY_FALLBACK=true`

2. **Ledger:**
   - Migration 002 will backfill `event_timestamp` from `created_at`
   - New events will use deterministic sequencing

3. **Certificates:**
   - Existing certificates remain valid
   - New certificates include key_id for rotation support

## 📝 Configuration

### Environment Variables

```bash
# API Key Auth
LEGACY_APIKEY_FALLBACK=false  # Set to true for legacy bcrypt support

# Signing
SIGNING_KEY_PATH=./secrets/origin_signing_key.pem
SIGNING_KEY_PROVIDER=local  # local, aws_kms
SIGNING_KEY_ID=  # Required for aws_kms

# Object Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=origin-evidence
EVIDENCE_SIGNED_URL_TTL=3600  # 1 hour
```

## 🧪 Testing

### Auth Performance Test
```python
# Should be O(1) lookup, not O(n)
import time
start = time.time()
for _ in range(1000):
    get_tenant_by_api_key(db, api_key)
elapsed = time.time() - start
assert elapsed < 1.0  # Should be fast
```

### Ledger Verification Test
```python
# Verify chain integrity
is_valid, error = ledger_service.verify_chain(tenant_id)
assert is_valid, f"Chain invalid: {error}"

# Mutate a payload and verify it fails
event.payload_json["tampered"] = True
db.commit()
is_valid, error = ledger_service.verify_chain(tenant_id)
assert not is_valid
```

### Certificate Verification Test
```python
# Get JWKS and verify signature
jwks = client.get("/v1/keys/jwks.json").json()
cert = client.get(f"/v1/certificates/{cert_id}").json()
# Verify signature using JWKS public key
```

## 📊 Performance Targets

- **Ingest P95**: < 3 seconds
- **API Key Lookup**: < 10ms (O(1) with index)
- **Evidence Generation**: Async, < 30s for PDF
- **Webhook Delivery**: Async, < 5s per attempt

## 🔐 Security Notes

1. **API Keys**: Never log raw keys, only prefixes
2. **Webhook Secrets**: Encrypted at rest using AWS KMS (production) or Fernet (dev with per-installation salt)
3. **Signing Keys**: Use KMS in production, never commit keys
4. **IP Allowlists**: Fail-closed in production/staging, fail-open in development (configurable via `IP_ALLOWLIST_FAIL_OPEN`)
5. **Webhook Signing**: Uses raw body bytes (not re-serialized JSON) for signature computation
6. **Certificate Algorithm**: PS256 (RSA-PSS SHA-256) - matches JWKS and certificate `alg` field

## ✅ Recent Security Fixes

### IP Allowlist Fail-Closed
- Production/staging: Invalid JSON denies access (fail-closed)
- Development: Invalid JSON allows access with warning (fail-open)
- Configurable via `IP_ALLOWLIST_FAIL_OPEN` environment variable
- Metrics tracked for parse errors

### Webhook Raw Body Signing
- Webhooks signed using raw body bytes (not re-serialized JSON)
- Signature: `HMAC-SHA256(timestamp + "." + raw_body_bytes)`
- SDK `verify_webhook()` accepts raw bytes
- Express.js example includes raw body capture middleware

### Certificate Algorithm Consistency
- All signers use PS256 (RSA-PSS SHA-256)
- JWKS advertises `alg: "PS256"`
- Certificate `alg` field matches JWKS
- Verification docs specify PS256 algorithm

